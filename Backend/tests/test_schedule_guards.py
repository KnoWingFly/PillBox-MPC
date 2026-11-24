"""Schedule edits that must be refused: slots too close together, and a slot under way."""

from datetime import datetime, timedelta
from uuid import UUID
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


# --- PUT /devices/{id}/schedules/{schedule_id} (B1) ----------------------------------------------
# model_dump() turned the HHMM times into "07:00" strings, which then reached the TIME column and
# failed with a server error. Only the fields present in the body may change.


async def test_single_schedule_update_changes_the_times(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    created = await create_schedule(client, owner, device, slot=1, start="07:00", end="07:30", tolerance=30)

    res = await client.put(
        f"{API}/devices/{device.id}/schedules/{created['id']}",
        json={"window_start": "08:00", "window_end": "08:15"},
        headers=owner.headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["window_start"] == "08:00" and body["window_end"] == "08:15"
    # Fields left out of the body keep their values.
    assert body["medication_name"] == "Amlodipine" and body["tolerance_minutes"] == 30
    assert body["config_version"] > created["config_version"]
    row = await db.fetchrow("SELECT window_start, window_end FROM schedules WHERE id = $1", UUID(created["id"]))
    assert f"{row['window_start']:%H:%M}" == "08:00" and f"{row['window_end']:%H:%M}" == "08:15"


async def test_single_schedule_update_of_other_fields(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    created = await create_schedule(client, owner, device, slot=2, start="12:00", end="12:30")
    url = f"{API}/devices/{device.id}/schedules/{created['id']}"

    res = await client.put(url, json={"medication_name": "Metformin", "tolerance_minutes": 45}, headers=owner.headers)
    assert res.status_code == 200, res.text
    assert res.json()["medication_name"] == "Metformin" and res.json()["tolerance_minutes"] == 45
    assert res.json()["window_start"] == "12:00"

    # A required field sent as null is refused, not stored.
    res = await client.put(url, json={"window_start": None}, headers=owner.headers)
    assert res.status_code == 422 and res.json()["error"]["code"] == "VALIDATION_ERROR"
    # An end before the start is refused.
    res = await client.put(url, json={"window_end": "11:00"}, headers=owner.headers)
    assert res.status_code == 422, res.text
