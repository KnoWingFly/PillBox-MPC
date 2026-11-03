"""Role enforcement and backend -> device commands."""

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
import httpx
import pytest
from sqlalchemy import event as sa_event

from app.db.session import get_engine
from app.main import app
from app.services.connection_manager import (
    CommandTimeoutError,
    ConnectionManager,
    DeviceCommand,
    DeviceConnection,
    DeviceDisconnectedError,
    DeviceNotConnectedError,
    connection_manager,
)
from tests.helpers import API, Caregiver, create_caregiver, create_schedule, paired_device


async def _join_as_pemantau(client: httpx.AsyncClient, db: asyncpg.Connection, device_id: str, pin: str) -> Caregiver:
    watcher = await create_caregiver(db, "Watcher")
    res = await client.post(f"{API}/devices/{device_id}/join", json={"device_pin": pin}, headers=watcher.headers)
    assert res.status_code == 200, res.text
    assert res.json()["my_role"] == "PEMANTAU"
    return watcher


async def test_pemantau_cannot_trigger_alarm_or_edit(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    watcher = await _join_as_pemantau(client, db, device.id, device.pin)

    res = await client.post(f"{API}/devices/{device.id}/alarm", json={}, headers=watcher.headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN"

    res = await client.post(
        f"{API}/devices/{device.id}/schedules",
        json={"slot_number": 2, "window_start": "12:00", "window_end": "12:30", "tolerance_minutes": 30},
        headers=watcher.headers,
    )
    assert res.status_code == 403

    # Read access still works.
    res = await client.get(f"{API}/devices/{device.id}/schedules", headers=watcher.headers)
    assert res.status_code == 200 and len(res.json()) == 8


async def test_wrong_pin_is_rejected_and_rate_limited(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    stranger = await create_caregiver(db, "Stranger")
    codes = []
    for _ in range(6):
        res = await client.post(f"{API}/devices/{device.id}/join", json={"device_pin": "0000"}, headers=stranger.headers)
        codes.append(res.json()["error"]["code"])
    assert codes[:5] == ["DEVICE_PIN_INCORRECT"] * 5
    assert codes[5] == "TOO_MANY_ATTEMPTS"


async def test_trigger_alarm_when_device_offline_fails_clearly(
    client: httpx.AsyncClient, db: asyncpg.Connection
) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    res = await client.post(f"{API}/devices/{device.id}/alarm", json={"slot_number": 1}, headers=owner.headers)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "DEVICE_OFFLINE"


async def test_trigger_alarm_rest_only_device_reports_missing_channel(
    client: httpx.AsyncClient, db: asyncpg.Connection
) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    hb = await client.post(
        f"{API}/devices/{device.code}/heartbeat",
        json={"battery_percent": 80, "wifi_rssi_dbm": -55, "chambers": []},
        headers=device.device_headers,
    )
    assert hb.status_code == 200
    status = (await client.get(f"{API}/devices/{device.id}/status", headers=owner.headers)).json()
    assert status["connectivity"] == "ONLINE" and status["command_channel_connected"] is False

    res = await client.post(f"{API}/devices/{device.id}/alarm", json={}, headers=owner.headers)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "DEVICE_COMMAND_CHANNEL_UNAVAILABLE"


async def test_schedule_change_bumps_config_version(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    cfg = await client.get(f"{API}/devices/{device.code}/config", headers=device.device_headers)
    version = cfg.json()["config_version"]
    created = await create_schedule(client, owner, device)
    assert created["config_version"] == version + 1
    not_modified = await client.get(
        f"{API}/devices/{device.code}/config", params={"since_version": version + 1}, headers=device.device_headers
    )
    assert not_modified.status_code == 304
    cfg = (await client.get(f"{API}/devices/{device.code}/config", headers=device.device_headers)).json()
    assert cfg["schedules"][0]["window_start"] == "07:00"


async def test_device_reporting_an_unknown_newer_version_resyncs(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    """A device whose local config_version is above anything issued (its DB came from another
    server, or the backend was restored) must still get the current config."""
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    await create_schedule(client, owner, device)
    latest = await db.fetchval("SELECT config_version FROM devices WHERE id = $1", uuid.UUID(device.id))

    hb = await client.post(
        f"{API}/devices/{device.code}/heartbeat",
        json={"battery_percent": 80, "config_version_applied": latest + 100},
        headers=device.device_headers,
    )
    assert hb.status_code == 200 and hb.json()["config_update_available"] is True
    assert await db.fetchval("SELECT config_version_applied FROM devices WHERE id = $1", uuid.UUID(device.id)) != latest + 100

    cfg = await client.get(
        f"{API}/devices/{device.code}/config", params={"since_version": latest + 100}, headers=device.device_headers
    )
    assert cfg.status_code == 200 and cfg.json()["config_version"] == latest
    ack = await client.post(
        f"{API}/devices/{device.code}/config-ack", json={"config_version": latest}, headers=device.device_headers
    )
    assert ack.status_code == 200
    hb = await client.post(
        f"{API}/devices/{device.code}/heartbeat",
        json={"battery_percent": 80, "config_version_applied": latest},
        headers=device.device_headers,
    )
    assert hb.json()["config_update_available"] is False


# --- connection manager (in-process, stub socket) -----------------------------


class _AckingSocket:
    """Minimal stand-in for a WebSocket: records sent JSON and, if `auto_ack`,
    answers each command through the manager like a real device would."""

    def __init__(self, manager: ConnectionManager, device_id: uuid.UUID, auto_ack: bool) -> None:
        self.manager, self.device_id, self.auto_ack = manager, device_id, auto_ack
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)
        if self.auto_ack:
            asyncio.get_running_loop().call_soon(
                self.manager.handle_ack,
                self.device_id,
                {"type": "ack", "command_id": data["command_id"], "ok": True, "result": {"ringing": True}},
            )


async def test_a_replaced_socket_fails_its_pending_commands_at_once() -> None:
    """A reconnect replaces the socket; acks can no longer arrive on the old one, so the waiting
    caller gets 502 DEVICE_DISCONNECTED now instead of 504 after the ack timeout."""
    manager = ConnectionManager()
    device_id = uuid.uuid4()
    old = _AckingSocket(manager, device_id, auto_ack=False)
    manager.register(DeviceConnection(device_id, "PB-TEST", old, datetime.now(UTC)))  # type: ignore[arg-type]
    waiting = asyncio.create_task(manager.send_command(device_id, DeviceCommand.TRIGGER_ALARM, {}, timeout=30))
    await asyncio.sleep(0)

    new = _AckingSocket(manager, device_id, auto_ack=True)
    manager.register(DeviceConnection(device_id, "PB-TEST", new, datetime.now(UTC)))  # type: ignore[arg-type]

    with pytest.raises(DeviceDisconnectedError):
        await asyncio.wait_for(waiting, timeout=1)


async def test_connection_manager_ack_timeout_and_not_connected() -> None:
    manager = ConnectionManager()
    device_id = uuid.uuid4()
    with pytest.raises(DeviceNotConnectedError):
        await manager.send_command(device_id, DeviceCommand.TRIGGER_ALARM, {}, timeout=0.1)

    socket = _AckingSocket(manager, device_id, auto_ack=True)
    manager.register(DeviceConnection(device_id, "PB-TEST", socket, datetime.now(UTC)))  # type: ignore[arg-type]
    ack = await manager.send_command(device_id, DeviceCommand.TRIGGER_ALARM, {"slot_number": 1}, timeout=1)
    assert ack.ok and ack.result == {"ringing": True}
    assert socket.sent[0]["command"] == "trigger_alarm"

    socket.auto_ack = False
    with pytest.raises(CommandTimeoutError):
        await manager.send_command(device_id, DeviceCommand.TRIGGER_ALARM, {}, timeout=0.1)


async def test_bulk_save_applies_all_slots_with_one_config_version(
    client: httpx.AsyncClient, db: asyncpg.Connection
) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    await create_schedule(client, owner, device, slot=1, start="08:00", end="08:00")
    await create_schedule(client, owner, device, slot=2, start="12:00", end="12:00")
    # Pin the device clock to 03:00 today: at 12:00-12:30 local time slot 2 would be "in
    # progress" (409 SLOT_IN_PROGRESS) and the test would fail by wall-clock time alone.
    three_am = datetime.now(ZoneInfo("Asia/Jakarta")).replace(hour=3, minute=0, second=0, microsecond=0)
    pinned = await client.post(
        f"{API}/devices/{device.code}/heartbeat",
        json={"battery_percent": 80, "rtc_time": three_am.isoformat(), "rtc_speed": 1.0},
        headers=device.device_headers,
    )
    assert pinned.status_code == 200
    before = await db.fetchval("SELECT config_version FROM devices WHERE id = $1", uuid.UUID(device.id))

    # Move slot 1's time onto slot 2's old time while clearing slot 2 and adding slot 3:
    # one at a time this order would trip WINDOW_OVERLAP; checked on the final state it is fine.
    body = {
        "slots": [
            {"slot_number": 1, "window_start": "12:00", "window_end": "12:00"},
            {"slot_number": 2, "clear": True},
            {"slot_number": 3, "window_start": "17:00", "window_end": "17:00", "tolerance_minutes": 45, "active": False},
        ]
    }
    res = await client.put(f"{API}/devices/{device.id}/schedules", json=body, headers=owner.headers)
    assert res.status_code == 200, res.text
    slots = {s["slot_number"]: s for s in res.json()}
    assert slots[1]["window_start"] == "12:00" and slots[2]["is_empty"]
    assert slots[3]["tolerance_minutes"] == 45 and slots[3]["active"] is False
    after = await db.fetchval("SELECT config_version FROM devices WHERE id = $1", uuid.UUID(device.id))
    assert after == before + 1

    # Nothing changed: no new version.
    res = await client.put(f"{API}/devices/{device.id}/schedules", json=body, headers=owner.headers)
    assert res.status_code == 200
    assert await db.fetchval("SELECT config_version FROM devices WHERE id = $1", uuid.UUID(device.id)) == after

    # A real overlap in the final state is rejected and nothing is saved.
    clash = {"slots": [{"slot_number": 4, "window_start": "12:00", "window_end": "12:00"}]}
    res = await client.put(f"{API}/devices/{device.id}/schedules", json=clash, headers=owner.headers)
    assert res.status_code == 409 and res.json()["error"]["code"] == "WINDOW_OVERLAP"
    assert await db.fetchval("SELECT count(*) FROM schedules WHERE slot_number = 4") == 0


async def _hold_device_lock(db: asyncpg.Connection, device_id: str) -> asyncpg.transaction.Transaction:
    tx = db.transaction()
    await tx.start()
    await db.execute("SELECT 1 FROM devices WHERE id = $1 FOR UPDATE", uuid.UUID(device_id))
    return tx


async def test_wrong_device_key_does_not_wait_for_the_row_lock(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    """The key is checked before the row is locked, so guessing requests cannot queue on it."""
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    tx = await _hold_device_lock(db, device.id)
    try:
        started = time.perf_counter()
        res = await client.post(
            f"{API}/devices/{device.code}/heartbeat", json={"battery_percent": 50}, headers={"X-Device-Key": "wrong"}
        )
        assert res.status_code == 401
        assert time.perf_counter() - started < 0.5
    finally:
        await tx.rollback()


async def test_request_stuck_on_a_row_lock_fails_fast_with_503(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    """DB_LOCK_TIMEOUT_MS (1 s in tests) instead of holding the connection for the whole command timeout."""
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    tx = await _hold_device_lock(db, device.id)
    try:
        started = time.perf_counter()
        # Starlette re-raises after the catch-all handler answered; uvicorn sends the 503.
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as server:
            res = await server.post(
                f"{API}/devices/{device.code}/heartbeat", json={"battery_percent": 50}, headers=device.device_headers
            )
        assert res.status_code == 503 and res.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert time.perf_counter() - started < 5
    finally:
        await tx.rollback()


async def test_owner_changes_the_device_pin(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner, pin="1234")
    url = f"{API}/devices/{device.id}/pin"

    wrong = await client.put(url, json={"current_device_pin": "9999", "new_device_pin": "4321"}, headers=owner.headers)
    assert wrong.status_code == 401 and wrong.json()["error"]["code"] == "CURRENT_PIN_INCORRECT"

    ok = await client.put(url, json={"current_device_pin": "1234", "new_device_pin": "4321"}, headers=owner.headers)
    assert ok.status_code == 200, ok.text

    viewer = await create_caregiver(db, "Viewer")
    old = await client.post(f"{API}/devices/{device.id}/join", json={"device_pin": "1234"}, headers=viewer.headers)
    assert old.status_code == 401
    new = await client.post(f"{API}/devices/{device.id}/join", json={"device_pin": "4321"}, headers=viewer.headers)
    assert new.status_code == 200, new.text


async def test_token_user_is_reused_between_requests(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    """Every request needs the token's user; within AUTH_USER_CACHE_SECONDS it is not re-read."""
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    seen: list[str] = []

    def record(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        seen.append(statement)

    sa_event.listen(get_engine().sync_engine, "before_cursor_execute", record)
    try:
        first = await client.get(f"{API}/devices/{device.id}", headers=owner.headers)
        reads_after_first = sum("FROM users" in s for s in seen)
        second = await client.get(f"{API}/devices/{device.id}", headers=owner.headers)
    finally:
        sa_event.remove(get_engine().sync_engine, "before_cursor_execute", record)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert sum("FROM users" in s for s in seen) == reads_after_first  # no new user lookup


async def test_device_settings_response_carries_the_new_updated_at(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    """Server-set columns come back with RETURNING (eager_defaults), without a refresh query."""
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    before = await db.fetchval("SELECT updated_at FROM devices WHERE id = $1", uuid.UUID(device.id))

    res = await client.put(f"{API}/devices/{device.id}", json={"device_nickname": "Kamar Baru"}, headers=owner.headers)

    assert res.status_code == 200, res.text
    stored = await db.fetchval("SELECT updated_at FROM devices WHERE id = $1", uuid.UUID(device.id))
    assert stored > before
    assert datetime.fromisoformat(res.json()["updated_at"]) == stored
    assert res.json()["device_nickname"] == "Kamar Baru"


async def test_owner_stops_a_running_alarm(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    """DELETE /devices/{id}/alarm sends stop_alarm and answers after the device's ack."""
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    device_uuid = uuid.UUID(device.id)
    socket = _AckingSocket(connection_manager, device_uuid, auto_ack=True)
    connection_manager.register(DeviceConnection(device_uuid, device.code, socket, datetime.now(UTC)))  # type: ignore[arg-type]

    res = await client.delete(f"{API}/devices/{device.id}/alarm", headers=owner.headers)

    assert res.status_code == 200, res.text
    assert res.json()["command"] == "stop_alarm" and res.json()["acknowledged"] is True
    assert [m["command"] for m in socket.sent] == ["stop_alarm"]
    assert socket.sent[0]["command_id"] == res.json()["command_id"]


async def test_stop_alarm_needs_an_editor_and_a_reachable_device(
    client: httpx.AsyncClient, db: asyncpg.Connection
) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    watcher = await _join_as_pemantau(client, db, device.id, device.pin)

    forbidden = await client.delete(f"{API}/devices/{device.id}/alarm", headers=watcher.headers)
    assert forbidden.status_code == 403 and forbidden.json()["error"]["code"] == "FORBIDDEN"
    offline = await client.delete(f"{API}/devices/{device.id}/alarm", headers=owner.headers)
    assert offline.status_code == 409 and offline.json()["error"]["code"] == "DEVICE_OFFLINE"
