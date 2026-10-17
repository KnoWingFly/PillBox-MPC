"""App push hints (services/app_hub.py): sent after commit, never after rollback."""

import asyncio
import uuid
from datetime import datetime
from collections.abc import Iterator
from typing import Any

import asyncpg
import httpx
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.db.session import get_sessionmaker
from app.main import app
from app.services.app_hub import AppConnection, app_hub, queue_device_change, queue_notifications
from tests.helpers import API, create_caregiver, create_schedule, event, paired_device, send_telemetry

DAY = "2026-09-30"


class _FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, message: dict[str, Any]) -> None:
        self.sent.append(message)


@pytest.fixture(autouse=True)
def _clean_hub() -> Iterator[None]:
    app_hub._connections.clear()
    yield
    app_hub._connections.clear()


async def _drain() -> None:
    # Hints are sent from a task scheduled by the commit hook.
    for _ in range(5):
        await asyncio.sleep(0)


async def test_late_dose_pushes_notification_and_device_hints(
    client: httpx.AsyncClient, db: asyncpg.Connection
) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    await create_schedule(client, owner, device)
    socket = _FakeSocket()
    app_hub.register(AppConnection(owner.id, {uuid.UUID(device.elderly_id)}, socket))  # type: ignore[arg-type]

    res = await send_telemetry(client, device, [event("ev-1", "COMPARTMENT_OPENED", f"{DAY}T07:45:00+07:00")])
    assert res.status_code == 200, res.text
    await _drain()

    # The pushed rows are what GET /notifications returns (the app shows them without refetching).
    pushed = [m for m in socket.sent if m["type"] == "notifications"]
    assert len(pushed) == 1 and len(pushed[0]["items"]) == 1
    item = pushed[0]["items"][0]
    feed = (await client.get(f"{API}/notifications", headers=owner.headers)).json()["data"][0]
    assert item["type"] == "DOSE_LATE" and item["slot_number"] == 1 and item["delay_minutes"] == 15
    for key in ("id", "type", "severity", "elderly_id", "device_id", "slot_number", "delay_minutes",
                "message", "is_read", "is_resolved"):
        assert item[key] == feed[key], key
    assert datetime.fromisoformat(item["created_at"]) == datetime.fromisoformat(feed["created_at"])

    # The device message carries the status body, same as GET /devices/{id}/status.
    devices = [m for m in socket.sent if m["type"] == "device"]
    assert devices and devices[-1]["device_id"] == device.id
    status = (await client.get(f"{API}/devices/{device.id}/status", headers=owner.headers)).json()
    assert devices[-1]["status"] == status


async def test_heartbeat_pushes_status(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    socket = _FakeSocket()
    app_hub.register(AppConnection(owner.id, {uuid.UUID(device.elderly_id)}, socket))  # type: ignore[arg-type]

    await _heartbeat(client, device, battery=42, stock=5)
    await _drain()
    status = socket.sent[-1]["status"]
    assert socket.sent[-1]["type"] == "device"
    assert status["battery_percent"] == 42 and status["connectivity"] == "ONLINE"


async def test_unchanged_stock_skips_write_until_another_writer_touches_it(
    client: httpx.AsyncClient, db: asyncpg.Connection
) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)

    async def stock_slot1() -> int:
        return await db.fetchval(
            "SELECT remaining_units FROM device_stocks WHERE device_id = $1 AND slot_number = 1",
            uuid.UUID(device.id),
        )

    await _heartbeat(client, device, battery=90, stock=5)
    assert await stock_slot1() == 5
    # Changed behind the backend's back: an identical heartbeat does not rewrite it...
    await db.execute("UPDATE device_stocks SET remaining_units = 9 WHERE device_id = $1", uuid.UUID(device.id))
    await _heartbeat(client, device, battery=90, stock=5)
    assert await stock_slot1() == 9
    # ...but a changed count is written,
    await _heartbeat(client, device, battery=90, stock=4)
    assert await stock_slot1() == 4
    # and after a refill through the API the device's count is asserted again.
    res = await client.post(
        f"{API}/devices/{device.id}/refills",
        json={"is_reset": True, "items": [{"slot_number": 1, "unit_dose_count": 20}]},
        headers=owner.headers,
    )
    assert res.status_code == 201, res.text
    await _heartbeat(client, device, battery=90, stock=4)
    assert await stock_slot1() == 4


async def _heartbeat(client: httpx.AsyncClient, device: Any, battery: int, stock: int) -> None:
    res = await client.post(
        f"{API}/devices/{device.code}/heartbeat",
        json={"battery_percent": battery, "chambers": [{"slot_number": 1, "door": "CLOSED", "stock_count": stock}]},
        headers=device.device_headers,
    )
    assert res.status_code == 200, res.text


async def test_other_users_get_no_hints(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    stranger = await create_caregiver(db, "Stranger")
    device = await paired_device(client, owner)
    await create_schedule(client, owner, device)
    socket = _FakeSocket()
    app_hub.register(AppConnection(stranger.id, set(), socket))  # type: ignore[arg-type]

    await send_telemetry(client, device, [event("ev-1", "COMPARTMENT_OPENED", f"{DAY}T07:45:00+07:00")])
    await _drain()
    assert socket.sent == []


async def test_rollback_sends_nothing() -> None:
    user_id, elderly_id = uuid.uuid4(), uuid.uuid4()
    socket = _FakeSocket()
    app_hub.register(AppConnection(user_id, {elderly_id}, socket))  # type: ignore[arg-type]

    async with get_sessionmaker()() as session:
        await session.connection()  # start a real transaction
        queue_notifications(session, {user_id: [{"id": "x"}]})
        queue_device_change(session, elderly_id, uuid.uuid4())
        await session.rollback()
        await session.commit()  # a later, empty commit must not resend the dropped queue
    await _drain()
    assert socket.sent == []


async def test_app_socket_auth(db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    token = owner.headers["Authorization"].removeprefix("Bearer ")

    def _connect() -> tuple[dict[str, Any], int | None]:
        test_client = TestClient(app)
        with test_client.websocket_connect("/ws/app") as ws:
            ws.send_json({"type": "auth", "token": token})
            ready = ws.receive_json()
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
        with test_client.websocket_connect("/ws/app") as ws:
            ws.send_json({"type": "auth", "token": "not-a-token"})
            try:
                ws.receive_json()
            except WebSocketDisconnect as exc:
                return ready, exc.code
        return ready, None

    ready, bad_code = await asyncio.to_thread(_connect)
    assert ready == {"type": "ready"}
    assert bad_code == 4401
