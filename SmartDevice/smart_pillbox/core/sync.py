"""Backend sync: device identity, registration, heartbeat, telemetry flush and
config pull/ack. Network errors never raise: events stay queued in SQLite
(that IS the offline-first behaviour) and send_heartbeat reports what happened
(HeartbeatResult) so the window can show it.

Identity: every device has a device_code (shown to the caregiver, typed into
the mobile app to pair) and a secret sent as X-Device-Key. Both are issued by
the backend when you press "Daftarkan Perangkat" and are stored in the local
`device_state` table. PILLCARE_DEVICE_CODE / PILLCARE_DEVICE_KEY env vars
override them (e.g. to reuse an identity provisioned elsewhere).

Contract: docs/DEVICE_CONTRACT.md in the repository root.
"""

from __future__ import annotations

import logging
import os
import random
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from http import HTTPStatus
from typing import Callable, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from smart_pillbox import config
from smart_pillbox.db.database import ConfigError, Database
from smart_pillbox.models import Compartment, is_int

logger = logging.getLogger(__name__)

# Telemetry answers that mean "keep the events and retry later" (docs/DEVICE_CONTRACT.md §2.4,
# §5.4): 401 = this identity is not accepted (re-register), 408/429 = try again later. Any other
# 4xx is final for the batch only when it carries the PillCare error body {"error": {"code": ...}}:
# retrying it forever would block every later event. A 4xx without that body (wrong URL, proxy,
# captive portal) and a status outside 2xx/4xx/5xx did not come from the backend: events are kept.
_RETRY_LATER = {HTTPStatus.UNAUTHORIZED, HTTPStatus.REQUEST_TIMEOUT, HTTPStatus.TOO_MANY_REQUESTS}
_BATCH_TOO_LARGE = HTTPStatus.REQUEST_ENTITY_TOO_LARGE


def _is_success(status: int) -> bool:
    return HTTPStatus.OK <= status < HTTPStatus.MULTIPLE_CHOICES


def _is_client_error(status: int) -> bool:
    return HTTPStatus.BAD_REQUEST <= status < HTTPStatus.INTERNAL_SERVER_ERROR


def _has_error_envelope(response: requests.Response) -> bool:
    """True when the body is the backend's error envelope {"error": {"code": "..."}}."""
    try:
        body = response.json()
    except ValueError:
        return False
    error = body.get("error") if isinstance(body, dict) else None
    return isinstance(error, dict) and isinstance(error.get("code"), str)


class HeartbeatResult(str, Enum):
    OK = "ok"
    NOT_REGISTERED = "not_registered"  # no identity yet: nothing was sent
    OFFLINE = "offline"                # Wi-Fi switched off in the lab: nothing was sent
    UNAUTHORIZED = "unauthorized"      # 401: the backend does not accept this device key
    HTTP_ERROR = "http_error"          # any other answer than 200 (5xx, unreadable body, ...)
    NETWORK = "network"                # timeout, refused, DNS: the server was not reached
    ERROR = "error"                    # the sync failed on the device itself (see the log)

    @property
    def server_unreachable(self) -> bool:
        """A failure that a later retry may fix (drives the sync backoff)."""
        return self in (HeartbeatResult.HTTP_ERROR, HeartbeatResult.NETWORK)


@dataclass(frozen=True)
class HeartbeatOutcome:
    result: HeartbeatResult
    server_time: str | None = None      # heartbeat response server_time (UTC ISO 8601)
    received_at: float | None = None    # time.monotonic() when it arrived, to age server_time
    config_update: bool = False         # a newer config is waiting: pull it (after the flush)


def backoff_delay(failures: int, rand: Callable[[], float] = random.random) -> float:
    """Seconds before the next sync after `failures` failed ones in a row: exponential, capped,
    with +/- SYNC_BACKOFF_JITTER so many pillboxes do not retry in the same second."""
    if failures <= 0:
        return 0.0
    base = min(config.SYNC_BACKOFF_MAX_SECONDS, config.SYNC_BACKOFF_MIN_SECONDS * 2 ** (failures - 1))
    return base * (1 + config.SYNC_BACKOFF_JITTER * (2 * rand() - 1))


def chamber_report(compartments: Iterable[Compartment]) -> list[dict]:
    """Heartbeat `chambers` from the scheduler's LIVE compartments: door state exists only in
    memory (the reed switch), never in the database."""
    return [
        {"slot_number": c.slot_number, "door": "OPEN" if c.door_open else "CLOSED", "stock_count": c.stock_count}
        for c in sorted(compartments, key=lambda c: c.slot_number)
    ]


def applied_config_version(db: Database) -> int:
    """The applied config_version, 0 when unknown or unreadable (0 makes the next pull a full one)."""
    try:
        return int(db.get_device_state(config.STATE_CONFIG_VERSION) or config.INITIAL_CONFIG_VERSION)
    except ValueError:
        return config.INITIAL_CONFIG_VERSION


def device_timezone(db: Database) -> str:
    return db.get_device_state(config.STATE_TIMEZONE) or config.DEFAULT_DEVICE_TIMEZONE


def device_zone(name: str | None) -> ZoneInfo:
    """ZoneInfo for the device timezone, the default zone when the name is unknown."""
    try:
        return ZoneInfo(name or config.DEFAULT_DEVICE_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Unknown device timezone %r; using %s.", name, config.DEFAULT_DEVICE_TIMEZONE)
        return ZoneInfo(config.DEFAULT_DEVICE_TIMEZONE)


_local = threading.local()


def _http() -> requests.Session:
    """One keep-alive session per thread (requests.Session is not thread-safe), so
    each sync reuses its TCP connection instead of opening one per request."""
    session = getattr(_local, "session", None)
    if session is None:
        session = _local.session = requests.Session()
    return session


class RegistrationError(Exception):
    """Registration failed; the message is shown to the user as-is."""


# --- identity -------------------------------------------------------------------

def get_identity(db: Database) -> tuple[str | None, str | None]:
    # The env overrides apply to the default profile only: exported once in a shell, they would
    # otherwise give every virtual pillbox the SAME identity.
    use_env = config.PROFILE == config.DEFAULT_PROFILE
    code = (use_env and os.environ.get("PILLCARE_DEVICE_CODE")) or db.get_device_state(config.STATE_DEVICE_CODE)
    key = (use_env and os.environ.get("PILLCARE_DEVICE_KEY")) or db.get_device_state(config.STATE_DEVICE_SECRET)
    return code, key


def is_registered(db: Database) -> bool:
    code, key = get_identity(db)
    return bool(code and key)


def is_paired(db: Database) -> bool:
    return db.get_device_state(config.STATE_IS_PAIRED) == config.STATE_TRUE


def forget_identity(db: Database) -> None:
    """Back to factory state for the server side: no identity, and nothing that belonged to the
    old one (its config version, timezone, refill mode and unsent events)."""
    db.update_device_states(
        {
            config.STATE_DEVICE_CODE: "",
            config.STATE_DEVICE_SECRET: "",
            config.STATE_IS_PAIRED: "",
            config.STATE_CONFIG_VERSION: str(config.INITIAL_CONFIG_VERSION),
            config.STATE_TIMEZONE: "",
            config.STATE_IS_REFILL_MODE: config.STATE_FALSE,
        }
    )
    dropped = db.delete_unsynced_events()
    if dropped:
        logger.info("Identity reset: dropped %d unsent event(s) of the old identity.", dropped)


def _pending_identity(db: Database) -> tuple[str, str]:
    """The code + secret this emulator asks the backend to register. Created once and
    kept until registration is confirmed, so retrying after a timeout re-sends the SAME
    identity instead of creating a second device on the server."""
    code = db.get_device_state(config.STATE_PENDING_DEVICE_CODE)
    secret = db.get_device_state(config.STATE_PENDING_DEVICE_SECRET)
    if not (code and secret):
        code = f"PB-{secrets.token_hex(4).upper()}"
        secret = secrets.token_urlsafe(32)
        db.update_device_state(config.STATE_PENDING_DEVICE_CODE, code)
        db.update_device_state(config.STATE_PENDING_DEVICE_SECRET, secret)
    return code, secret


def _server_accepts(code: str, secret: str) -> bool:
    try:
        response = _http().get(
            f"{config.BACKEND_BASE_URL}/devices/{code}/config",
            headers={"X-Device-Key": secret},
            timeout=config.REGISTER_HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        return False
    return response.status_code in (HTTPStatus.OK, HTTPStatus.NOT_MODIFIED)


def register_device(db: Database, provisioning_token: str) -> str:
    """Registers this emulator with the backend (factory provisioning) and stores
    its device_code + secret locally. Returns the device_code."""
    code, secret = _pending_identity(db)
    try:
        response = _http().post(
            f"{config.BACKEND_BASE_URL}/admin/devices",
            json={"device_code": code, "device_secret": secret},
            headers={"X-Provisioning-Token": provisioning_token},
            timeout=config.REGISTER_HTTP_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        raise RegistrationError(
            "Server terlalu lama merespons. Tekan 'Daftarkan Perangkat' lagi untuk melanjutkan."
        ) from exc
    except requests.RequestException as exc:
        raise RegistrationError(f"Server tidak dapat dihubungi ({config.BACKEND_BASE_URL}).") from exc
    if response.status_code == HTTPStatus.UNAUTHORIZED:
        raise RegistrationError("Provisioning token salah (cek PROVISIONING_TOKEN di Backend/.env).")
    if response.status_code == HTTPStatus.NOT_FOUND:
        raise RegistrationError("Registrasi dinonaktifkan: PROVISIONING_TOKEN belum diisi di Backend/.env.")
    if response.status_code == HTTPStatus.CONFLICT:
        # Code already exists: our earlier attempt succeeded on the server but the
        # response was lost. Confirm the server knows OUR secret before adopting it.
        if not _server_accepts(code, secret):
            for key in (config.STATE_PENDING_DEVICE_CODE, config.STATE_PENDING_DEVICE_SECRET):
                db.update_device_state(key, "")
            raise RegistrationError("Kode bentrok dengan perangkat lain. Tekan 'Daftarkan Perangkat' lagi.")
    elif response.status_code != HTTPStatus.CREATED:
        raise RegistrationError(f"Registrasi gagal (HTTP {response.status_code}).")

    db.update_device_states(
        {
            config.STATE_DEVICE_CODE: code,
            config.STATE_DEVICE_SECRET: secret,
            config.STATE_PENDING_DEVICE_CODE: "",
            config.STATE_PENDING_DEVICE_SECRET: "",
            config.STATE_IS_PAIRED: config.STATE_FALSE,
            # A brand-new server identity starts its config history from scratch, so pull
            # the first config even if this local DB was synced before.
            config.STATE_CONFIG_VERSION: str(config.INITIAL_CONFIG_VERSION),
        }
    )
    logger.info("Registered as %s.", code)
    return code


def _auth(db: Database) -> tuple[str, dict[str, str]] | None:
    code, key = get_identity(db)
    if not (code and key):
        return None
    return code, {"X-Device-Key": key}


# --- telemetry ------------------------------------------------------------------

def flush_pending_events(
    db: Database,
    offline_flush: bool = False,
    device_time: str | None = None,
    stop: threading.Event | None = None,
) -> int:
    """Sends unsynced events (oldest first, in chunks). Returns how many were
    synced (0 if not registered or the backend is unreachable). offline_flush
    marks the batches sent right after Wi-Fi returns (contract §2.4, §5.3).
    device_time: the RTC reading, used for config-ack if a newer config is pulled.
    stop: set while the app shuts down; checked between chunks."""
    auth = _auth(db)
    if auth is None:
        return 0
    code, headers = auth
    synced = 0
    chunk_size = config.FLUSH_CHUNK_SIZE
    while stop is None or not stop.is_set():
        pending = db.get_unsynced_events(limit=chunk_size)
        if not pending:
            return synced
        payload = {
            "batch_id": str(uuid.uuid4()),
            "is_offline_flush": offline_flush,
            "events": [
                {
                    "event_id": row["event_id"],
                    "event_type": row["event_type"],
                    "slot_number": row["slot_number"],
                    "schedule_id": None,  # the backend matches events by slot and time
                    "occurred_at": row["occurred_at"],
                    "chime_count": row["chime_count"],
                }
                for row in pending
            ],
        }
        try:
            response = _http().post(
                f"{config.BACKEND_BASE_URL}/devices/{code}/telemetry",
                json=payload,
                headers=headers,
                timeout=config.SYNC_HTTP_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            logger.info("Backend unreachable, buffering %d event(s) locally: %s", len(pending), exc)
            return synced
        status = response.status_code
        # 413 BATCH_TOO_LARGE or PAYLOAD_TOO_LARGE: both mean "send fewer events per batch".
        if status == _BATCH_TOO_LARGE and chunk_size > 1:
            chunk_size = max(1, chunk_size // 2)  # the backend's limit is lower: send smaller batches
            continue
        res_json: dict = {}
        if _is_success(status):
            try:
                body = response.json()
            except ValueError:  # requests.JSONDecodeError is a ValueError
                logger.info("Backend sent an unreadable answer, buffering %d event(s) locally.", len(pending))
                return synced
            res_json = body if isinstance(body, dict) else {}
        elif _is_client_error(status) and status not in _RETRY_LATER and _has_error_envelope(response):
            logger.warning("Backend rejected a batch of %d event(s) (HTTP %d); dropping it.", len(pending), status)
        else:
            # 401/408/429, 5xx, a 4xx that is not the backend's, or no answer at all (1xx/3xx).
            logger.info("Backend answered HTTP %d, buffering %d event(s) locally.", status, len(pending))
            return synced

        # accepted, duplicate and rejected are all final outcomes for an event_id (and so is a
        # batch the backend refused with a final 4xx, see _RETRY_LATER).
        db.mark_synced([row["id"] for row in pending])
        synced += len(pending)
        logger.info("Synced %d event(s) to backend.", len(pending))

        latest_version = res_json.get("latest_config_version")
        if is_int(latest_version) and latest_version > applied_config_version(db):
            pull_latest_config(db, device_time)
    return synced


# --- heartbeat & config -----------------------------------------------------------

def send_heartbeat(
    db: Database,
    current_time_str: str,
    battery_percent: int,
    is_online: bool,
    clock_speed: float = 1.0,
    chambers: list[dict] | None = None,
) -> HeartbeatOutcome:
    """Sends one heartbeat in its own short request and reports how it went. chambers: from
    chamber_report() of the live compartments (door state is not in the database). A waiting
    config is NOT pulled here (that can take a long timeout): the caller pulls it when
    outcome.config_update is set, after the flush (contract §5.3)."""
    if not is_online:
        return HeartbeatOutcome(HeartbeatResult.OFFLINE)
    auth = _auth(db)
    if auth is None:
        return HeartbeatOutcome(HeartbeatResult.NOT_REGISTERED)
    code, headers = auth

    applied_version = applied_config_version(db)
    payload = {
        "sent_at": current_time_str,
        "battery_percent": battery_percent,
        "wifi_rssi_dbm": config.SIMULATED_WIFI_RSSI_DBM,
        "rtc_backup_active": config.SIMULATED_RTC_BACKUP_ACTIVE,
        "rtc_time": current_time_str,
        # The simulated RTC can run fast; the backend and the app extrapolate the device clock
        # with it between heartbeats (docs/DEVICE_CONTRACT.md, heartbeat).
        "rtc_speed": clock_speed,
        "config_version_applied": applied_version,
        "chambers": chambers or [],
    }

    try:
        response = _http().post(
            f"{config.BACKEND_BASE_URL}/devices/{code}/heartbeat",
            json=payload,
            headers=headers,
            timeout=config.HEARTBEAT_HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.info("Heartbeat not delivered: %s", exc)
        return HeartbeatOutcome(HeartbeatResult.NETWORK)
    received_at = time.monotonic()
    if response.status_code == HTTPStatus.UNAUTHORIZED:
        # The backend no longer knows this identity (e.g. its database was reset).
        logger.warning("Device key rejected by backend; register the device again.")
        return HeartbeatOutcome(HeartbeatResult.UNAUTHORIZED)
    if response.status_code != HTTPStatus.OK:
        logger.warning("Heartbeat answered HTTP %d.", response.status_code)
        return HeartbeatOutcome(HeartbeatResult.HTTP_ERROR)
    try:
        res_json = response.json()
    except ValueError:
        logger.warning("Heartbeat answer is not JSON.")
        return HeartbeatOutcome(HeartbeatResult.HTTP_ERROR)
    if not isinstance(res_json, dict):
        logger.warning("Heartbeat answer is not an object.")
        return HeartbeatOutcome(HeartbeatResult.HTTP_ERROR)

    state = {config.STATE_IS_PAIRED: config.STATE_TRUE if res_json.get("is_paired") else config.STATE_FALSE}
    interval = res_json.get("heartbeat_interval_seconds")
    if is_int(interval) and interval > 0:
        # The backend decides the heartbeat period (contract §2.1); the window applies it.
        state[config.STATE_HEARTBEAT_INTERVAL_SECONDS] = str(interval)
    db.update_device_states(state)
    latest_version = res_json.get("latest_config_version")
    update_available = res_json.get("config_update_available") is True
    server_time = res_json.get("server_time")
    return HeartbeatOutcome(
        HeartbeatResult.OK,
        server_time if isinstance(server_time, str) else None,
        received_at,
        config_update=update_available or (is_int(latest_version) and latest_version > applied_version),
    )


def _config_state(config_data: dict) -> dict[str, str]:
    """The device_state keys a pulled config sets, validated; raises ConfigError."""
    version = config_data.get("config_version")
    if not is_int(version) or version < 0:
        raise ConfigError("config_version is missing or not a non-negative integer")
    state = {config.STATE_CONFIG_VERSION: str(version)}
    # Refill mode and timezone travel in the config too: a refill_mode command sent while the
    # command channel was down must still reach the device (contract §3).
    if "is_refill_mode" in config_data:
        refill = config_data["is_refill_mode"]
        if not isinstance(refill, bool):
            raise ConfigError("is_refill_mode is not true or false")
        state[config.STATE_IS_REFILL_MODE] = config.STATE_TRUE if refill else config.STATE_FALSE
    timezone = config_data.get("timezone")
    if timezone:
        try:
            ZoneInfo(str(timezone))
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ConfigError(f"unknown timezone {timezone!r}") from exc
        state[config.STATE_TIMEZONE] = str(timezone)
    volume = config_data.get("chime_volume_level")
    if volume is not None:
        if volume not in config.CHIME_VOLUME_LEVELS:
            raise ConfigError(f"unknown chime_volume_level {volume!r}")
        state[config.STATE_CHIME_VOLUME_LEVEL] = volume
    return state


def pull_latest_config(db: Database, device_time: str | None = None) -> bool:
    """Pulls and applies a newer config, then acks it. device_time: the RTC reading sent as
    config-ack applied_at (wall clock if not given). Returns True when a new config was applied.
    A config that does not validate is logged and dropped as a whole: the old one keeps running
    and is still reported in config_version_applied, so the backend keeps offering the update."""
    auth = _auth(db)
    if auth is None:
        return False
    code, headers = auth
    current_version = applied_config_version(db)
    try:
        response = _http().get(
            f"{config.BACKEND_BASE_URL}/devices/{code}/config?since_version={current_version}",
            headers=headers,
            timeout=config.SYNC_HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.info("Config pull failed: %s", exc)
        return False
    if response.status_code == HTTPStatus.NOT_MODIFIED:
        logger.info("Config is already up to date (304 Not Modified).")
        return False
    if response.status_code != HTTPStatus.OK:
        logger.warning("Config pull answered HTTP %d.", response.status_code)
        return False
    try:
        config_data = response.json()
        if not isinstance(config_data, dict):
            raise ConfigError("config is not an object")
        state = _config_state(config_data)
        db.apply_config(config_data.get("schedules", []), state)  # schedules + state, one transaction
    except (ConfigError, KeyError, TypeError, ValueError) as exc:
        logger.warning("Ignoring an invalid config; keeping version %d: %s", current_version, exc)
        return False
    new_version = int(state[config.STATE_CONFIG_VERSION])
    logger.info("Config successfully synced to version %d.", new_version)

    # Send Config ACK to backend to close reconciliation loop
    try:
        _http().post(
            f"{config.BACKEND_BASE_URL}/devices/{code}/config-ack",
            json={"config_version": new_version, "applied_at": device_time or datetime.now().isoformat()},
            headers=headers,
            timeout=config.SYNC_HTTP_TIMEOUT_SECONDS,
        )
        logger.info("Config ACK sent to backend.")
    except requests.RequestException as exc:
        # The next heartbeat reports config_version_applied, which closes the loop as well.
        logger.info("Config ACK not delivered: %s", exc)
    return True
