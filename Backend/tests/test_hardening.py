"""Sad paths found in the 2026-11-03 robustness review: values the database cannot store, PIN
brute force, stalled sockets, database failures on WebSockets, background re-work, roles."""

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import httpx
import pytest
from sqlalchemy import exc as sa_exc
from starlette.testclient import TestClient, WebSocketTestSession

from app.api.routes import ws as ws_routes
from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.main import app
from app.schemas.common import PG_INT_MAX
from app.services import presence, telemetry
from app.services.connection_manager import DeviceCommand, DeviceConnection, connection_manager
from tests.constants import TEST_PROVISIONING_TOKEN
from tests.helpers import API, create_caregiver, event, paired_device, send_telemetry

ADMIN = {"X-Provisioning-Token": TEST_PROVISIONING_TOKEN}
WRONG_PIN = "0000"


# --- telemetry / heartbeat values the database cannot store ------------------------------

async def test_int_above_the_column_range_is_rejected_per_event(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    now = datetime.now(UTC).isoformat()
    res = await send_telemetry(client, device, [
        event("too-big", "BATTERY_STATUS", now, slot=None, chime_count=PG_INT_MAX + 1),
        event("fine", "BATTERY_STATUS", now, slot=None, battery_percent=80),
    ])
    assert res.status_code == 200, res.text
    by_id = {r["event_id"]: r["status"] for r in res.json()["results"]}
    assert by_id == {"too-big": "rejected", "fine": "accepted"}


async def test_heartbeat_int_above_the_column_range_is_422_not_500(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    res = await client.post(
        f"{API}/devices/{device.code}/heartbeat",
        json={"battery_percent": 50, "wifi_rssi_dbm": PG_INT_MAX + 1},
        headers=device.device_headers,
    )
    assert res.status_code == 422


async def test_an_event_the_database_refuses_does_not_block_the_batch(
    client: httpx.AsyncClient, db: asyncpg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    original = telemetry._apply

    async def refusing_apply(session: Any, dev: Any, ev: Any, *args: Any, **kwargs: Any) -> Any:
        if ev.event_id == "refused":
            raise sa_exc.DataError("INSERT …", {}, Exception("value out of range"))
        return await original(session, dev, ev, *args, **kwargs)

    monkeypatch.setattr(telemetry, "_apply", refusing_apply)
    now = datetime.now(UTC).isoformat()
    res = await send_telemetry(client, device, [
        event("refused", "BATTERY_STATUS", now, slot=None, battery_percent=70),
        event("stored", "BATTERY_STATUS", now, slot=None, battery_percent=71),
    ])
    assert res.status_code == 200, res.text
    by_id = {r["event_id"]: r for r in res.json()["results"]}
    assert by_id["refused"]["status"] == "rejected" and "could not be stored" in by_id["refused"]["reason"]
    assert by_id["stored"]["status"] == "accepted"
    outcomes = dict(await db.fetch("SELECT event_id, outcome FROM device_events"))
    assert outcomes == {"refused": "REJECTED", "stored": "ACCEPTED"}

    # The device resends after a lost answer: the refused event is a final duplicate now.
    again = await send_telemetry(client, device, [event("refused", "BATTERY_STATUS", now, slot=None, battery_percent=70)])
    assert again.json()["results"][0]["status"] == "duplicate"


async def test_oversized_body_is_413(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    body = b'{"events": [], "batch_id": "' + b"x" * (get_settings().max_request_body_bytes + 1) + b'"}'
    res = await client.post(
        f"{API}/devices/{device.code}/telemetry",
        content=body,
        headers={**device.device_headers, "Content-Type": "application/json"},
    )
    assert res.status_code == 413 and res.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


# --- PIN brute force -----------------------------------------------------------------------

async def test_parallel_wrong_pins_cannot_exceed_the_limit(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    limit = get_settings().pin_max_attempts
    attackers = [await create_caregiver(db, f"Attacker{i}") for i in range(limit * 2)]
    responses = await asyncio.gather(*(
        client.post(f"{API}/devices/{device.id}/join", json={"device_pin": WRONG_PIN}, headers=a.headers)
        for a in attackers
    ))
    codes = [r.json()["error"]["code"] for r in responses]
    # Per device across all users: more accounts and parallel requests buy no extra guesses.
    assert codes.count("DEVICE_PIN_INCORRECT") == limit
    assert codes.count("TOO_MANY_ATTEMPTS") == limit
    locked = await client.post(f"{API}/devices/{device.id}/join", json={"device_pin": device.pin}, headers=attackers[0].headers)
    assert locked.status_code == 429 and "Retry-After" in locked.headers


async def test_pairing_scan_hides_the_elderly_name_from_strangers(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    stranger = await create_caregiver(db, "Stranger")
    body = {"device_qr_payload": device.code}
    mine = (await client.post(f"{API}/devices/pairing/scan", json=body, headers=owner.headers)).json()
    theirs = (await client.post(f"{API}/devices/pairing/scan", json=body, headers=stranger.headers)).json()
    assert mine["elderly_name_if_owned"] == "Oma"
    assert theirs["is_registered"] is True and theirs["elderly_name_if_owned"] is None


async def test_pairing_scan_is_rate_limited_per_user(
    client: httpx.AsyncClient, db: asyncpg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "pairing_scan_max_attempts", 2)
    user = await create_caregiver(db, "Scanner")
    codes = []
    for _ in range(3):
        res = await client.post(f"{API}/devices/pairing/scan", json={"device_qr_payload": "PB-DEADBEEF"}, headers=user.headers)
        codes.append(res.json()["error"]["code"])
    assert codes == ["QR_CODE_NOT_RECOGNIZED", "QR_CODE_NOT_RECOGNIZED", "TOO_MANY_ATTEMPTS"]


# --- device sockets ------------------------------------------------------------------------

class _StalledSocket:
    """A pillbox whose TCP connection stopped draining: every send waits forever."""

    async def send_json(self, _: dict[str, Any]) -> None:
        await asyncio.Event().wait()

    async def close(self, code: int = 1000, reason: str = "") -> None:
        await asyncio.Event().wait()


async def test_a_stalled_device_socket_cannot_hang_a_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "device_ws_send_timeout_seconds", 0.05)
    device_id = uuid.uuid4()
    conn = DeviceConnection(device_id, "PB-STALLED", _StalledSocket(), datetime.now(UTC))  # type: ignore[arg-type]
    connection_manager.register(conn)
    delivered = await asyncio.wait_for(
        connection_manager.notify(device_id, DeviceCommand.SCHEDULE_UPDATED, {"config_version": 2}), timeout=2
    )
    assert delivered is False
    assert not connection_manager.is_connected(device_id)


@pytest.fixture
def tc() -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


def _next_reply(ws: WebSocketTestSession) -> dict[str, Any]:
    while True:
        message: dict[str, Any] = ws.receive_json()
        if message.get("type") != "command":
            return message


def test_a_database_error_on_a_ws_heartbeat_keeps_the_socket(
    tc: TestClient, db: asyncpg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev = tc.post(f"{API}/admin/devices", json={}, headers=ADMIN).json()
    original = ws_routes.process_heartbeat
    calls = {"n": 0}

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise sa_exc.OperationalError("SELECT …", {}, Exception("connection reset"))
        return await original(*args, **kwargs)

    monkeypatch.setattr(ws_routes, "process_heartbeat", flaky)
    with tc.websocket_connect(f"/ws/device/{dev['device_code']}", headers={"X-Device-Key": dev["device_secret"]}) as ws:
        assert _next_reply(ws)["type"] == "welcome"
        ws.send_json({"type": "heartbeat", "battery_percent": 40})
        assert _next_reply(ws)["type"] == "error"
        ws.send_json({"type": "heartbeat", "battery_percent": 40})
        assert _next_reply(ws)["type"] == "heartbeat_ack"


# --- background work and roles -------------------------------------------------------------

async def test_presence_sweep_does_not_resend_offline_notifications(
    client: httpx.AsyncClient, db: asyncpg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    await db.execute(
        "UPDATE devices SET status = 'OFFLINE', offline_since = now() - interval '30 minutes' WHERE id = $1",
        uuid.UUID(device.id),
    )
    calls = {"n": 0}
    original = presence.notify

    async def counting_notify(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(presence, "notify", counting_notify)
    for _ in range(2):
        async with get_sessionmaker()() as session:
            await presence.sweep(session, datetime.now(UTC), get_settings())
    assert calls["n"] == 1
    assert await db.fetchval("SELECT count(*) FROM notifications WHERE type = 'DEVICE_OFFLINE'") == 1


async def _notification(db: asyncpg.Connection, user_id: uuid.UUID, elderly_id: str, device_id: str | None) -> uuid.UUID:
    return await db.fetchval(
        """INSERT INTO notifications (user_id, elderly_id, device_id, type, severity, message, event_key)
           VALUES ($1, $2, $3, 'DOSE_MISSED', 'WARNING', 'test', $4) RETURNING id""",
        user_id, uuid.UUID(elderly_id), uuid.UUID(device_id) if device_id else None, f"TEST:{uuid.uuid4()}",
    )


async def test_pemantau_cannot_resolve_a_shared_incident(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    viewer = await create_caregiver(db, "Viewer")
    joined = await client.post(f"{API}/devices/{device.id}/join", json={"device_pin": device.pin}, headers=viewer.headers)
    assert joined.status_code == 200, joined.text
    notification_id = await _notification(db, viewer.id, device.elderly_id, device.id)
    res = await client.put(f"{API}/notifications/{notification_id}/resolve", json={}, headers=viewer.headers)
    assert res.status_code == 403


# --- contract additions: pagination and the per-pillbox feed -------------------------------

async def test_device_and_caregiver_lists_are_paginated(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    first = await paired_device(client, owner)
    await paired_device(client, owner)
    page = (await client.get(f"{API}/devices", params={"limit": 1}, headers=owner.headers)).json()
    assert page["page"] == 1 and page["limit"] == 1 and page["total"] == 2 and len(page["data"]) == 1
    past_end = (await client.get(f"{API}/devices", params={"limit": 1, "page": 3}, headers=owner.headers)).json()
    assert past_end["total"] == 2 and past_end["data"] == []
    caregivers = (await client.get(f"{API}/elderly/{first.elderly_id}/caregivers", headers=owner.headers)).json()
    assert caregivers["total"] == 1 and caregivers["data"][0]["role"] == "OWNER"


async def test_feed_filtered_by_device_includes_its_elderly_level_rows(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    mine = await paired_device(client, owner)
    other = await paired_device(client, owner)
    own_row = await _notification(db, owner.id, mine.elderly_id, mine.id)
    elderly_row = await _notification(db, owner.id, mine.elderly_id, None)
    await _notification(db, owner.id, other.elderly_id, other.id)
    res = await client.get(f"{API}/notifications", params={"device_id": mine.id}, headers=owner.headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert {item["id"] for item in body["data"]} == {str(own_row), str(elderly_row)}
    assert body["total"] == 2 and body["unread_count"] == 2
    unfiltered = (await client.get(f"{API}/notifications", headers=owner.headers)).json()
    assert unfiltered["unread_count"] == 3


async def test_past_confirmation_time_is_validated(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    """confirmed_at is stored as recorded_at: a typo'd year must not land in the journal."""
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    log_id = await db.fetchval(
        """INSERT INTO telemetry_logs
               (device_id, elderly_id, slot_number, event_type, status, scheduled_for, scheduled_date, log_source)
           VALUES ($1, $2, 1, 'RULES_ENGINE_MISSED', 'MISSED', now() - interval '2 hours', current_date,
                   'SYSTEM_RULES_ENGINE') RETURNING id""",
        uuid.UUID(device.id), uuid.UUID(device.elderly_id),
    )
    far_future = (datetime.now(UTC) + timedelta(days=400)).isoformat()
    res = await client.put(
        f"{API}/journal/dose-logs/{log_id}/manual-confirmation",
        json={"override_status": "TAKEN_LATE", "confirmed_at": far_future},
        headers=owner.headers,
    )
    assert res.status_code == 422, res.text


async def test_chunked_oversized_body_is_413(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    chunk = b"x" * 65536
    chunks = get_settings().max_request_body_bytes // len(chunk) + 2

    async def body() -> Any:
        yield b'{"events": [], "batch_id": "'
        for _ in range(chunks):
            yield chunk
        yield b'"}'

    res = await client.post(
        f"{API}/devices/{device.code}/telemetry",
        content=body(),
        headers={**device.device_headers, "Content-Type": "application/json"},
    )
    assert res.status_code == 413 and res.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


async def test_nul_character_in_an_event_is_rejected_per_event(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    """Postgres text/jsonb cannot store U+0000: it must not fail the claim INSERT for the batch."""
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    now = datetime.now(UTC).isoformat()
    res = await send_telemetry(client, device, [
        event("nul", "ALARM_STOPPED", now, slot=None, reason="bad\x00reason"),
        event("ok", "BATTERY_STATUS", now, slot=None, battery_percent=60),
    ])
    assert res.status_code == 200, res.text
    assert {r["event_id"]: r["status"] for r in res.json()["results"]} == {"nul": "rejected", "ok": "accepted"}


async def test_page_beyond_the_offset_range_is_422(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    res = await client.get(f"{API}/devices", params={"page": 10**19}, headers=owner.headers)
    assert res.status_code == 422


async def test_strangers_guessing_the_pin_do_not_lock_out_the_owner(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    stranger = await create_caregiver(db, "Stranger")
    for _ in range(get_settings().pin_max_attempts + 1):
        await client.post(f"{API}/devices/{device.id}/join", json={"device_pin": WRONG_PIN}, headers=stranger.headers)
    res = await client.put(
        f"{API}/devices/{device.id}/pin",
        json={"current_device_pin": device.pin, "new_device_pin": "4321"},
        headers=owner.headers,
    )
    assert res.status_code == 200, res.text
