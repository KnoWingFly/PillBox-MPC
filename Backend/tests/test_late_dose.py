"""A missed dose taken late: release, confirm, cutoff, forced open (services/late_dose.py)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
import httpx
import pytest

from app.services import connection_manager as cm
from tests.helpers import API, create_caregiver, create_schedule, event, paired_device, send_telemetry

JAKARTA = ZoneInfo("Asia/Jakarta")


async def _missed_dose(client: httpx.AsyncClient, db: asyncpg.Connection, *, next_dose_after: int | None = None):
    """Slot 1 was due 40 min ago (tolerance 15) and the pillbox timed out: MISSED.
    next_dose_after: also schedule slot 2 that many minutes after slot 1."""
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    due = datetime.now(JAKARTA).replace(second=0, microsecond=0) - timedelta(minutes=40)
    await create_schedule(client, owner, device, slot=1, start=f"{due:%H:%M}", end=f"{due:%H:%M}", tolerance=15)
    if next_dose_after is not None:
        later = due + timedelta(minutes=next_dose_after)
        await create_schedule(client, owner, device, slot=2, start=f"{later:%H:%M}", end=f"{later:%H:%M}", tolerance=15)
    res = await send_telemetry(client, device, [event("timeout-1", "ALARM_TIMEOUT", (due + timedelta(minutes=15)).isoformat())])
    assert res.status_code == 200 and res.json()["accepted"] == 1, res.text
    feed = (await client.get(f"{API}/notifications", headers=owner.headers)).json()["data"]
    missed = next(n for n in feed if n["type"] == "DOSE_MISSED")
    return owner, device, due, missed


async def _notifications(client: httpx.AsyncClient, owner: Any) -> list[dict[str, Any]]:
    return (await client.get(f"{API}/notifications", headers=owner.headers)).json()["data"]


async def test_missed_notification_offers_actions_and_confirm_settles_it(
    client: httpx.AsyncClient, db: asyncpg.Connection
) -> None:
    owner, _, _, missed = await _missed_dose(client, db)
    assert missed["actions"] == ["LATE_RELEASE", "CONFIRM_TAKEN"]

    res = await client.post(f"{API}/notifications/{missed['id']}/confirm-taken", json={}, headers=owner.headers)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "TAKEN_LATE"

    feed = await _notifications(client, owner)
    old = next(n for n in feed if n["id"] == missed["id"])
    assert old["is_resolved"] and old["actions"] == []
    follow_up = next(n for n in feed if n["type"] == "DOSE_LATE")
    assert "akhirnya diminum" in follow_up["message"]
    note = await db.fetchval("SELECT resolution_note FROM notifications WHERE id = $1", uuid.UUID(missed["id"]))
    assert note.startswith("Diminum terlambat pukul") and "dikonfirmasi oleh" in note


async def test_too_close_to_the_next_dose_is_refused(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    # Next dose 60 min after the missed one: the cutoff (halfway) was 10 min ago.
    owner, _, _, missed = await _missed_dose(client, db, next_dose_after=60)
    res = await client.post(f"{API}/notifications/{missed['id']}/confirm-taken", json={}, headers=owner.headers)
    assert res.status_code == 409 and res.json()["error"]["code"] == "LATE_DOSE_TOO_LATE"
    assert "Jangan diminum" in res.json()["error"]["message"]


async def test_release_reopens_the_slot_and_a_late_open_counts_as_taken(
    client: httpx.AsyncClient, db: asyncpg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, device, _, missed = await _missed_dose(client, db)
    sent: list[tuple[cm.DeviceCommand, dict[str, Any]]] = []

    async def fake_send(device_id: uuid.UUID, command: cm.DeviceCommand, payload: dict[str, Any], timeout: float) -> cm.CommandAck:
        sent.append((command, payload))
        return cm.CommandAck("cmd-1", True, {"released": True}, None, datetime.now(UTC))

    monkeypatch.setattr(cm.connection_manager, "send_command", fake_send)
    res = await client.post(
        f"{API}/notifications/{missed['id']}/late-release", json={"device_pin": device.pin}, headers=owner.headers
    )
    assert res.status_code == 200, res.text
    assert sent[0][0] is cm.DeviceCommand.RELEASE_SLOT and sent[0][1]["slot_number"] == 1

    # The elder opens the re-opened chamber a few minutes later (long after the dose's deadline).
    opened_at = datetime.now(JAKARTA) + timedelta(minutes=2)
    res = await send_telemetry(client, device, [event("open-late", "COMPARTMENT_OPENED", opened_at.isoformat())])
    assert res.status_code == 200 and res.json()["results"][0]["telemetry_log_id"], res.text
    status, delay = await db.fetchrow("SELECT status, delay_minutes FROM telemetry_logs WHERE status IS NOT NULL")
    assert status == "TAKEN" and delay >= 40
    feed = await _notifications(client, owner)
    assert next(n for n in feed if n["id"] == missed["id"])["is_resolved"]
    assert any(n["type"] == "DOSE_LATE" and "akhirnya diminum" in n["message"] for n in feed)


async def test_failed_release_leaves_no_open_window(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner, device, _, missed = await _missed_dose(client, db)
    res = await client.post(
        f"{API}/notifications/{missed['id']}/late-release", json={"device_pin": device.pin}, headers=owner.headers
    )
    # No command channel (the telemetry just now marked it online over REST).
    assert res.status_code == 409
    assert res.json()["error"]["code"] in ("DEVICE_OFFLINE", "DEVICE_COMMAND_CHANNEL_UNAVAILABLE")
    assert await db.fetchval("SELECT late_release_until FROM telemetry_logs WHERE status = 'MISSED'") is None


async def test_forced_open_after_a_miss_asks_to_confirm(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner, device, _, missed = await _missed_dose(client, db)
    res = await send_telemetry(client, device, [event("forced", "UNSCHEDULED_OPEN", datetime.now(JAKARTA).isoformat())])
    assert res.status_code == 200, res.text
    forced = next(n for n in await _notifications(client, owner) if n["type"] == "UNSCHEDULED_OPEN")
    assert forced["severity"] == "WARNING" and forced["actions"] == ["CONFIRM_TAKEN"]
    assert "Mungkin obatnya diminum terlambat" in forced["message"]

    res = await client.post(f"{API}/notifications/{forced['id']}/confirm-taken", json={}, headers=owner.headers)
    assert res.status_code == 200, res.text
    feed = await _notifications(client, owner)
    assert all(n["is_resolved"] for n in feed if n["id"] in (forced["id"], missed["id"]))


async def _summary(client: httpx.AsyncClient, owner: Any, elderly_id: str) -> dict[str, Any]:
    today = datetime.now(JAKARTA).date()
    res = await client.get(
        f"{API}/elderly/{elderly_id}/journal/summary",
        params={"start": (today - timedelta(days=1)).isoformat(), "end": (today + timedelta(days=1)).isoformat()},
        headers=owner.headers,
    )
    assert res.status_code == 200, res.text
    return res.json()


async def test_adherence_moves_from_missed_to_late_when_confirmed(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner, device, _, missed = await _missed_dose(client, db)
    before = await _summary(client, owner, device.elderly_id)
    assert (before["missed"], before["taken_late"]) == (1, 0)

    await client.post(f"{API}/notifications/{missed['id']}/confirm-taken", json={}, headers=owner.headers)
    after = await _summary(client, owner, device.elderly_id)
    assert (after["missed"], after["taken_late"]) == (0, 1)


async def test_adherence_moves_from_missed_to_late_when_the_released_lid_opens(
    client: httpx.AsyncClient, db: asyncpg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, device, _, missed = await _missed_dose(client, db)

    async def fake_send(device_id: uuid.UUID, command: cm.DeviceCommand, payload: dict[str, Any], timeout: float) -> cm.CommandAck:
        return cm.CommandAck("cmd-1", True, {}, None, datetime.now(UTC))

    monkeypatch.setattr(cm.connection_manager, "send_command", fake_send)
    await client.post(f"{API}/notifications/{missed['id']}/late-release", json={"device_pin": device.pin}, headers=owner.headers)
    await send_telemetry(client, device, [event("open", "COMPARTMENT_OPENED", datetime.now(JAKARTA).isoformat())])
    after = await _summary(client, owner, device.elderly_id)
    assert (after["missed"], after["taken_late"]) == (0, 1)
