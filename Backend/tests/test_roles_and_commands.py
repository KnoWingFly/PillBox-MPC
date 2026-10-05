"""Role enforcement and backend -> device commands."""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg
import httpx
import pytest

from app.services.connection_manager import (
    CommandTimeoutError,
    ConnectionManager,
    DeviceCommand,
    DeviceConnection,
    DeviceNotConnectedError,
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
