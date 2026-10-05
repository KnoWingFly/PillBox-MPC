"""Backend sync: device identity, registration, heartbeat, telemetry flush and
config pull/ack. Network errors are swallowed and events stay queued in
SQLite: that IS the offline-first behaviour, not a bug.

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
import secrets
import uuid
from datetime import datetime

import requests

from smart_pillbox import config
from smart_pillbox.db.database import Database

logger = logging.getLogger(__name__)

# Backend accepts at most 500 events per telemetry batch.
FLUSH_CHUNK_SIZE = 200


class RegistrationError(Exception):
    """Registration failed; the message is shown to the user as-is."""


# --- identity -------------------------------------------------------------------

def get_identity(db: Database) -> tuple[str | None, str | None]:
    code = os.environ.get("PILLCARE_DEVICE_CODE") or db.get_device_state("device_code")
    key = os.environ.get("PILLCARE_DEVICE_KEY") or db.get_device_state("device_secret")
    return code, key


def is_registered(db: Database) -> bool:
    code, key = get_identity(db)
    return bool(code and key)


def is_paired(db: Database) -> bool:
    return db.get_device_state("is_paired") == "1"


def forget_identity(db: Database) -> None:
    for key in ("device_code", "device_secret", "is_paired"):
        db.update_device_state(key, "")


def _pending_identity(db: Database) -> tuple[str, str]:
    """The code + secret this emulator asks the backend to register. Created once and
    kept until registration is confirmed, so retrying after a timeout re-sends the SAME
    identity instead of creating a second device on the server."""
    code = db.get_device_state("pending_device_code")
    secret = db.get_device_state("pending_device_secret")
    if not (code and secret):
        code = f"PB-{secrets.token_hex(4).upper()}"
        secret = secrets.token_urlsafe(32)
        db.update_device_state("pending_device_code", code)
        db.update_device_state("pending_device_secret", secret)
    return code, secret


def _server_accepts(code: str, secret: str) -> bool:
    try:
        response = requests.get(
            f"{config.BACKEND_BASE_URL}/devices/{code}/config",
            headers={"X-Device-Key": secret},
            timeout=config.REGISTER_HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        return False
    return response.status_code in (200, 304)


def register_device(db: Database, provisioning_token: str) -> str:
    """Registers this emulator with the backend (factory provisioning) and stores
    its device_code + secret locally. Returns the device_code."""
    code, secret = _pending_identity(db)
    try:
        response = requests.post(
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
    if response.status_code == 401:
        raise RegistrationError("Provisioning token salah (cek PROVISIONING_TOKEN di Backend/.env).")
    if response.status_code == 404:
        raise RegistrationError("Registrasi dinonaktifkan: PROVISIONING_TOKEN belum diisi di Backend/.env.")
    if response.status_code == 409:
        # Code already exists: our earlier attempt succeeded on the server but the
        # response was lost. Confirm the server knows OUR secret before adopting it.
        if not _server_accepts(code, secret):
            for key in ("pending_device_code", "pending_device_secret"):
                db.update_device_state(key, "")
            raise RegistrationError("Kode bentrok dengan perangkat lain. Tekan 'Daftarkan Perangkat' lagi.")
    elif response.status_code != 201:
        raise RegistrationError(f"Registrasi gagal (HTTP {response.status_code}).")

    db.update_device_state("device_code", code)
    db.update_device_state("device_secret", secret)
    db.update_device_state("pending_device_code", "")
    db.update_device_state("pending_device_secret", "")
    db.update_device_state("is_paired", "0")
    # A brand-new server identity starts its config history from scratch, so pull
    # the first config even if this local DB was synced before.
    db.update_device_state("config_version", "0")
    logger.info("Registered as %s.", code)
    return code


def _auth(db: Database) -> tuple[str, dict[str, str]] | None:
    code, key = get_identity(db)
    if not (code and key):
        return None
    return code, {"X-Device-Key": key}


# --- telemetry ------------------------------------------------------------------

def flush_pending_events(db: Database) -> int:
    """Sends unsynced events (oldest first, in chunks). Returns how many were
    synced (0 if not registered or the backend is unreachable)."""
    auth = _auth(db)
    if auth is None:
        return 0
    code, headers = auth
    synced = 0
    while True:
        pending = db.get_unsynced_events()[:FLUSH_CHUNK_SIZE]
        if not pending:
            return synced
        payload = {
            "batch_id": str(uuid.uuid4()),
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
            response = requests.post(
                f"{config.BACKEND_BASE_URL}/devices/{code}/telemetry",
                json=payload,
                headers=headers,
                timeout=config.SYNC_HTTP_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            res_json = response.json()
        except requests.RequestException as exc:
            logger.info("Backend unreachable, buffering %d event(s) locally: %s", len(pending), exc)
            return synced

        # accepted, duplicate and rejected are all final outcomes for an event_id.
        db.mark_synced([row["id"] for row in pending])
        synced += len(pending)
        logger.info("Synced %d event(s) to backend.", len(pending))

        latest_version = res_json.get("latest_config_version")
        current_version = int(db.get_device_state("config_version") or "1")
        if latest_version and latest_version > current_version:
            pull_latest_config(db)


# --- heartbeat & config -----------------------------------------------------------

def send_heartbeat(db: Database, current_time_str: str, battery_percent: int, is_online: bool) -> None:
    if not is_online:
        return
    auth = _auth(db)
    if auth is None:
        return
    code, headers = auth

    config_version = db.get_device_state("config_version") or "1"
    payload = {
        "sent_at": current_time_str,
        "battery_percent": battery_percent,
        "wifi_rssi_dbm": -50,
        "rtc_time": current_time_str,
        "config_version_applied": int(config_version),
        "chambers": [
            {
                "slot_number": c.slot_number,
                "door": "OPEN" if c.door_open else "CLOSED",
                "stock_count": c.stock_count,
            }
            for c in db.get_compartments()
        ],
    }

    try:
        response = requests.post(
            f"{config.BACKEND_BASE_URL}/devices/{code}/heartbeat",
            json=payload,
            headers=headers,
            timeout=config.SYNC_HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code == 401:
            # The backend no longer knows this identity (e.g. its database was reset).
            db.update_device_state("is_paired", "0")
            logger.warning("Device key rejected by backend; register the device again.")
            return
        if response.status_code == 200:
            res_json = response.json()
            db.update_device_state("is_paired", "1" if res_json.get("is_paired") else "0")
            latest_version = res_json.get("latest_config_version")
            update_available = res_json.get("config_update_available", False)
            current_version = int(config_version)
            if update_available or (latest_version and latest_version > current_version):
                pull_latest_config(db)
    except requests.RequestException:
        pass  # offline: the next heartbeat retries


def pull_latest_config(db: Database) -> None:
    auth = _auth(db)
    if auth is None:
        return
    code, headers = auth
    try:
        current_version = int(db.get_device_state("config_version") or "1")
        response = requests.get(
            f"{config.BACKEND_BASE_URL}/devices/{code}/config?since_version={current_version}",
            headers=headers,
            timeout=config.SYNC_HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code == 200:
            config_data = response.json()
            schedules = config_data.get("schedules", [])
            new_version = config_data.get("config_version") or config_data.get("version", current_version + 1)

            db.update_schedules(schedules)
            db.update_device_state("config_version", str(new_version))
            logger.info("Config successfully synced to version %s.", new_version)

            # Send Config ACK to backend to close reconciliation loop
            try:
                ack_payload = {
                    "config_version": int(new_version),
                    "applied_at": datetime.now().isoformat(),
                }
                requests.post(
                    f"{config.BACKEND_BASE_URL}/devices/{code}/config-ack",
                    json=ack_payload,
                    headers=headers,
                    timeout=config.SYNC_HTTP_TIMEOUT_SECONDS,
                )
                logger.info("Config ACK sent to backend.")
            except requests.RequestException:
                pass
        elif response.status_code == 304:
            logger.info("Config is already up to date (304 Not Modified).")
    except requests.RequestException:
        pass
