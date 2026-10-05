"""Test helpers. Users are inserted directly because the Mobile server
(Prisma) owns account creation; everything else goes through the real API."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import httpx
import jwt

from tests.constants import TEST_JWT_SECRET, TEST_PROVISIONING_TOKEN

API = "/api/v1"


@dataclass
class Caregiver:
    id: uuid.UUID
    email: str
    headers: dict[str, str]


@dataclass
class PairedDevice:
    id: str
    code: str
    secret: str
    elderly_id: str
    pin: str

    @property
    def device_headers(self) -> dict[str, str]:
        return {"X-Device-Key": self.secret}


def access_token(user_id: uuid.UUID) -> str:
    """Same shape as Mobile/src/server/tokens.ts signAccessToken()."""
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": str(user_id), "fid": str(uuid.uuid4()), "iat": now, "exp": now + timedelta(minutes=15)},
        TEST_JWT_SECRET,
        algorithm="HS256",
    )


async def create_caregiver(db: asyncpg.Connection, name: str, timezone: str = "Asia/Jakarta") -> Caregiver:
    email = f"{name.lower()}-{uuid.uuid4().hex[:8]}@example.test"
    user_id = await db.fetchval(
        "INSERT INTO users (full_name, email, timezone) VALUES ($1, $2, $3) RETURNING id", name, email, timezone
    )
    return Caregiver(id=user_id, email=email, headers={"Authorization": f"Bearer {access_token(user_id)}"})


async def provision(client: httpx.AsyncClient) -> dict[str, Any]:
    res = await client.post(
        f"{API}/admin/devices", json={}, headers={"X-Provisioning-Token": TEST_PROVISIONING_TOKEN}
    )
    assert res.status_code == 201, res.text
    return res.json()


async def paired_device(client: httpx.AsyncClient, owner: Caregiver, pin: str = "1234") -> PairedDevice:
    res = await client.post(f"{API}/elderly", json={"full_name": "Oma Sari", "nickname": "Oma"}, headers=owner.headers)
    assert res.status_code == 201, res.text
    elderly_id = res.json()["id"]
    dev = await provision(client)
    res = await client.post(
        f"{API}/devices",
        json={
            "device_qr_payload": dev["qr_payload"],
            "elderly_id": elderly_id,
            "device_nickname": "Pillbox Kamar",
            "timezone": "Asia/Jakarta",
            "device_pin": pin,
        },
        headers=owner.headers,
    )
    assert res.status_code == 201, res.text
    return PairedDevice(id=res.json()["id"], code=dev["device_code"], secret=dev["device_secret"], elderly_id=elderly_id, pin=pin)


async def create_schedule(
    client: httpx.AsyncClient,
    owner: Caregiver,
    device: PairedDevice,
    slot: int = 1,
    start: str = "07:00",
    end: str = "07:30",
    tolerance: int = 30,
) -> dict[str, Any]:
    res = await client.post(
        f"{API}/devices/{device.id}/schedules",
        json={
            "slot_number": slot,
            "medication_name": "Amlodipine",
            "dosage_info": "5 mg",
            "window_start": start,
            "window_end": end,
            "tolerance_minutes": tolerance,
            "days_of_week": [1, 2, 3, 4, 5, 6, 7],
            "active": True,
        },
        headers=owner.headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


def event(event_id: str, event_type: str, occurred_at: str, slot: int | None = 1, **extra: Any) -> dict[str, Any]:
    return {"event_id": event_id, "event_type": event_type, "slot_number": slot, "occurred_at": occurred_at, **extra}


async def send_telemetry(
    client: httpx.AsyncClient, device: PairedDevice, events: list[dict[str, Any]], **body: Any
) -> httpx.Response:
    return await client.post(
        f"{API}/devices/{device.code}/telemetry",
        json={"batch_id": str(uuid.uuid4()), "events": events, **body},
        headers=device.device_headers,
    )
