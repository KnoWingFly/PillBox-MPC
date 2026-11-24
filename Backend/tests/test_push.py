"""Phone push through the Expo Push API (services/push.py), with a fake Expo server."""

import json
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
import httpx
import pytest

from app.core.config import get_settings
from app.services.push import push_sender
from tests.helpers import create_caregiver, event, paired_device, send_telemetry

JAKARTA = ZoneInfo("Asia/Jakarta")


@pytest.fixture
def expo(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    """Records what would be sent to Expo; every token except 'gone' is accepted."""
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        messages = json.loads(request.content)
        sent.extend(messages)
        tickets = [
            {"status": "error", "message": "gone", "details": {"error": "DeviceNotRegistered"}}
            if m["to"].endswith("[gone]")
            else {"status": "ok", "id": f"r-{i}"}
            for i, m in enumerate(messages)
        ]
        return httpx.Response(200, json={"data": tickets})

    monkeypatch.setattr(push_sender, "transport", httpx.MockTransport(handler))
    monkeypatch.setattr(get_settings(), "push_enabled", True)
    monkeypatch.setattr(get_settings(), "expo_push_receipt_delay_seconds", 0)
    yield sent


async def _register_phone(db: asyncpg.Connection, user_id: Any, token: str) -> None:
    await db.execute("INSERT INTO push_tokens (user_id, token, platform) VALUES ($1, $2, 'ANDROID')", user_id, token)


async def test_a_new_notification_is_pushed_to_every_phone(
    client: httpx.AsyncClient, db: asyncpg.Connection, expo: list[dict[str, Any]]
) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    await _register_phone(db, owner.id, "ExponentPushToken[phone-1]")
    await _register_phone(db, owner.id, "ExponentPushToken[gone]")

    res = await send_telemetry(client, device, [event("forced", "UNSCHEDULED_OPEN", datetime.now(JAKARTA).isoformat())])
    assert res.status_code == 200, res.text
    await push_sender.settle()

    assert {m["to"] for m in expo} == {"ExponentPushToken[phone-1]", "ExponentPushToken[gone]"}
    message = expo[0]
    assert message["title"] == "Bilik dibuka di luar jadwal"  # caregiver language ID (default)
    assert "dibuka di luar jadwal" in message["body"]
    assert message["data"]["type"] == "UNSCHEDULED_OPEN" and message["data"]["device_id"] == str(device.id)
    assert message["priority"] == "high"
    row_id = await db.fetchval("SELECT id FROM notifications WHERE user_id = $1", owner.id)
    assert message["data"]["notification_id"] == str(row_id)


async def test_no_push_when_push_is_off_or_no_phone(
    client: httpx.AsyncClient, db: asyncpg.Connection, expo: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    # No phone registered: nothing is sent.
    await send_telemetry(client, device, [event("open-1", "UNSCHEDULED_OPEN", datetime.now(JAKARTA).isoformat())])
    await push_sender.settle()
    assert expo == []

    # A phone, but the caregiver turned push off for this elderly.
    await _register_phone(db, owner.id, "ExponentPushToken[phone-1]")
    res = await client.put(
        f"/api/v1/elderly/{device.elderly_id}/notification-preferences",
        json={"channels": {"push": False, "whatsapp": False}},
        headers=owner.headers,
    )
    assert res.status_code == 200, res.text
    await send_telemetry(client, device, [event("open-2", "UNSCHEDULED_OPEN", datetime.now(JAKARTA).isoformat(), slot=2)])
    await push_sender.settle()
    assert expo == []

    # Push switched off server-wide.
    await client.put(
        f"/api/v1/elderly/{device.elderly_id}/notification-preferences",
        json={"channels": {"push": True, "whatsapp": False}},
        headers=owner.headers,
    )
    monkeypatch.setattr(get_settings(), "push_enabled", False)
    await send_telemetry(client, device, [event("open-3", "UNSCHEDULED_OPEN", datetime.now(JAKARTA).isoformat(), slot=3)])
    await push_sender.settle()
    assert expo == []
