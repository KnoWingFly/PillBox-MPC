"""Telemetry ingestion against a real database: idempotency, adherence
classification, and offline-flush ordering."""

import uuid

import asyncpg
import httpx

from tests.helpers import API, create_caregiver, create_schedule, event, paired_device, send_telemetry

# 2026-09-28 (Monday), Asia/Jakarta (+07:00). Schedule: 07:00-07:30, tolerance 30
# -> on time until 07:30, late until 08:00, missed after.
DAY = "2026-09-28"


async def _dose_rows(db: asyncpg.Connection, device_id: str) -> list[asyncpg.Record]:
    return await db.fetch(
        "SELECT * FROM telemetry_logs WHERE device_id = $1 AND status IS NOT NULL ORDER BY scheduled_for",
        uuid.UUID(device_id),
    )


async def test_duplicate_event_id_is_a_noop(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    await create_schedule(client, owner, device)
    events = [
        event("ev-popup-1", "POPUP_ACTIVATED", f"{DAY}T07:00:00+07:00"),
        event("ev-open-1", "COMPARTMENT_OPENED", f"{DAY}T07:10:00+07:00", chime_count=4),
    ]

    first = await send_telemetry(client, device, events)
    assert first.status_code == 200, first.text
    body1 = first.json()
    assert (body1["accepted"], body1["duplicates"], body1["rejected"]) == (2, 0, [])
    notifications_before = await db.fetchval("SELECT count(*) FROM notifications")

    second = await send_telemetry(client, device, events)
    body2 = second.json()
    assert (body2["accepted"], body2["duplicates"]) == (0, 2)
    # The original outcome (same dose row) is returned for the re-sent event.
    assert [r["telemetry_log_id"] for r in body2["results"]] == [r["telemetry_log_id"] for r in body1["results"]]
    assert all(r["status"] == "duplicate" for r in body2["results"])

    rows = await _dose_rows(db, device.id)
    assert len(rows) == 1 and rows[0]["status"] == "TAKEN"
    assert await db.fetchval("SELECT count(*) FROM device_events") == 2
    assert await db.fetchval("SELECT count(*) FROM notifications") == notifications_before


async def test_duplicate_within_one_batch(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    await create_schedule(client, owner, device)
    e = event("ev-x", "COMPARTMENT_OPENED", f"{DAY}T07:05:00+07:00")
    body = (await send_telemetry(client, device, [e, e])).json()
    assert (body["accepted"], body["duplicates"]) == (1, 1)


async def test_on_time_classification(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    await create_schedule(client, owner, device)
    await send_telemetry(client, device, [event("ev-1", "COMPARTMENT_OPENED", f"{DAY}T07:25:00+07:00")])

    rows = await _dose_rows(db, device.id)
    assert rows[0]["status"] == "TAKEN" and rows[0]["delay_minutes"] == 0

    day = (await client.get(f"{API}/elderly/{device.elderly_id}/journal/{DAY}", headers=owner.headers)).json()
    assert day["doses"][0]["status"] == "TAKEN_ON_TIME"
    assert day["adherence_rate"] == 100.0 and day["avg_delay_minutes"] == 0.0


async def test_late_classification_stores_minutes_late(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    await create_schedule(client, owner, device)
    await send_telemetry(client, device, [event("ev-1", "COMPARTMENT_OPENED", f"{DAY}T07:45:00+07:00")])

    rows = await _dose_rows(db, device.id)
    assert rows[0]["status"] == "TAKEN" and rows[0]["delay_minutes"] == 15
    late = await db.fetchval("SELECT count(*) FROM notifications WHERE type = 'DOSE_LATE'")
    assert late == 1  # the owner, per default preferences

    day = (await client.get(f"{API}/elderly/{device.elderly_id}/journal/{DAY}", headers=owner.headers)).json()
    assert day["doses"][0]["status"] == "TAKEN_LATE" and day["doses"][0]["delay_minutes"] == 15


async def test_alarm_timeout_marks_missed(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    await create_schedule(client, owner, device)
    await send_telemetry(
        client,
        device,
        [
            event("ev-1", "POPUP_ACTIVATED", f"{DAY}T07:00:00+07:00"),
            event("ev-2", "ALARM_TIMEOUT", f"{DAY}T07:30:00+07:00", chime_count=30),
        ],
    )
    rows = await _dose_rows(db, device.id)
    assert rows[0]["status"] == "MISSED" and rows[0]["log_source"] == "AUTO_SENSOR"
    assert await db.fetchval("SELECT count(*) FROM notifications WHERE type = 'DOSE_MISSED'") == 1


async def test_offline_flush_is_processed_in_timestamp_order(
    client: httpx.AsyncClient, db: asyncpg.Connection
) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    await create_schedule(client, owner, device)
    # Buffered while offline, flushed out of order. Naive timestamps like the
    # emulator sends: interpreted in the device timezone (Asia/Jakarta).
    flush = [
        event("ev-close", "COMPARTMENT_CLOSED", f"{DAY}T07:12:00"),
        event("ev-unsched", "UNSCHEDULED_OPEN", f"{DAY}T10:00:00", slot=2),
        event("ev-open", "COMPARTMENT_OPENED", f"{DAY}T07:05:00"),
        event("ev-popup", "POPUP_ACTIVATED", f"{DAY}T07:00:00"),
    ]
    res = await send_telemetry(client, device, flush, is_offline_flush=True)
    assert res.json()["accepted"] == 4

    row = (await _dose_rows(db, device.id))[0]
    assert row["status"] == "TAKEN" and row["delay_minutes"] == 0
    # 07:05 local = 00:05 UTC; close recorded after open.
    assert row["actual_open_time"].isoformat().startswith(f"{DAY}T00:05:00")
    assert row["actual_close_time"].isoformat().startswith(f"{DAY}T00:12:00")
    assert await db.fetchval("SELECT count(*) FROM telemetry_logs WHERE event_type = 'UNSCHEDULED_OPEN'") == 1
    # Events are stored with their true device time, not arrival time.
    times = await db.fetch("SELECT event_id FROM device_events ORDER BY occurred_at")
    assert [r["event_id"] for r in times] == ["ev-popup", "ev-open", "ev-close", "ev-unsched"]


async def test_unknown_event_type_is_rejected_per_event(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    await create_schedule(client, owner, device)
    body = (
        await send_telemetry(
            client,
            device,
            [
                event("ev-bad", "SOMETHING_ELSE", f"{DAY}T07:00:00+07:00"),
                event("ev-good", "COMPARTMENT_OPENED", f"{DAY}T07:05:00+07:00"),
            ],
        )
    ).json()
    assert body["accepted"] == 1
    assert body["rejected"][0]["event_id"] == "ev-bad"


async def test_device_key_is_required(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    res = await client.post(
        f"{API}/devices/{device.code}/telemetry", json={"events": []}, headers={"X-Device-Key": "wrong"}
    )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "DEVICE_KEY_INVALID"
