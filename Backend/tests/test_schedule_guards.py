"""Schedule edits that must be refused: slots too close together, and a slot under way."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import asyncpg
import httpx

from tests.helpers import API, create_caregiver, create_schedule, event, paired_device, send_telemetry

JAKARTA = ZoneInfo("Asia/Jakarta")


async def _save(client: httpx.AsyncClient, owner, device, slots: list[dict]) -> httpx.Response:
    return await client.put(f"{API}/devices/{device.id}/schedules", json={"slots": slots}, headers=owner.headers)


async def test_slots_closer_than_the_tolerance_are_refused(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    await create_schedule(client, owner, device, slot=1, start="08:00", end="08:00", tolerance=30)

    res = await _save(client, owner, device, [{"slot_number": 5, "window_start": "08:20", "window_end": "08:20"}])
    assert res.status_code == 409, res.text
    err = res.json()["error"]
    assert err["code"] == "SCHEDULE_TOO_CLOSE"
    assert "B1 terlalu dekat dengan slot A1" in err["message"] and "30 menit" in err["message"]

    # Exactly one tolerance later is fine.
    res = await _save(client, owner, device, [{"slot_number": 5, "window_start": "08:30", "window_end": "08:30"}])
    assert res.status_code == 200, res.text


async def test_too_close_across_midnight(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    await create_schedule(client, owner, device, slot=4, start="23:50", end="23:50", tolerance=30)
    # 23:50 + 30 min runs until 00:20 the next day.
    res = await _save(client, owner, device, [{"slot_number": 1, "window_start": "00:10", "window_end": "00:10"}])
    assert res.status_code == 409 and res.json()["error"]["code"] == "SCHEDULE_TOO_CLOSE"


async def test_slot_under_way_cannot_be_changed_until_decided(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    due = datetime.now(JAKARTA).replace(second=0, microsecond=0) - timedelta(minutes=5)
    await create_schedule(client, owner, device, slot=1, start=f"{due:%H:%M}", end=f"{due:%H:%M}", tolerance=30)
    later = (due + timedelta(hours=2)).strftime("%H:%M")

    res = await _save(client, owner, device, [{"slot_number": 1, "window_start": later, "window_end": later}])
    assert res.status_code == 409 and res.json()["error"]["code"] == "SLOT_IN_PROGRESS", res.text
    assert "sedang berbunyi" in res.json()["error"]["message"]
    res = await _save(client, owner, device, [{"slot_number": 1, "clear": True}])
    assert res.status_code == 409 and res.json()["error"]["code"] == "SLOT_IN_PROGRESS"
    # Renaming the medication never touches the dose.
    res = await _save(client, owner, device, [{"slot_number": 1, "medication_name": "Metformin"}])
    assert res.status_code == 200, res.text

    # The lid is open: still refused, with the door message.
    hb = {"battery_percent": 90, "chambers": [{"slot_number": 1, "door": "OPEN"}]}
    assert (await client.post(f"{API}/devices/{device.code}/heartbeat", json=hb, headers=device.device_headers)).status_code == 200
    res = await _save(client, owner, device, [{"slot_number": 1, "window_start": later, "window_end": later}])
    assert res.status_code == 409 and "Pintu bilik A1 sedang terbuka" in res.json()["error"]["message"]

    # Taken and the lid closed again: the change goes through.
    await send_telemetry(client, device, [event("open", "COMPARTMENT_OPENED", (due + timedelta(minutes=2)).isoformat())])
    hb["chambers"][0]["door"] = "CLOSED"
    await client.post(f"{API}/devices/{device.code}/heartbeat", json=hb, headers=device.device_headers)
    res = await _save(client, owner, device, [{"slot_number": 1, "window_start": later, "window_end": later}])
    assert res.status_code == 200, res.text
