"""Missed-dose rules engine against a real database."""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import asyncpg
import httpx

from app.core.config import Settings, get_settings
from app.db.session import get_sessionmaker
from app.services.rules_engine import run_once
from tests.helpers import create_caregiver, create_schedule, event, paired_device, send_telemetry


def _settings(**overrides: object) -> Settings:
    base = {"rules_engine_lookback_days": 2, "missed_decision_grace_seconds": 0}
    return get_settings().model_copy(update={**base, **overrides})


async def _backdate(db: asyncpg.Connection, device_id: str, days: int = 3) -> None:
    """Pretend the device was paired and the schedule created `days` ago."""
    did = uuid.UUID(device_id)
    await db.execute("UPDATE schedules SET created_at = now() - make_interval(days => $2) WHERE device_id = $1", did, days)
    await db.execute("UPDATE devices SET paired_at = now() - make_interval(days => $2) WHERE id = $1", did, days)


async def _set_online(db: asyncpg.Connection, device_id: str, since: datetime) -> None:
    await db.execute(
        "UPDATE devices SET status = 'ONLINE', online_since = $2, last_heartbeat = now() WHERE id = $1",
        uuid.UUID(device_id),
        since,
    )


async def _count(db: asyncpg.Connection, sql: str, *args: object) -> int:
    return int(await db.fetchval(sql, *args))


async def test_missed_dose_rule_is_idempotent(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    # 08:00-08:30 + 15 min: yesterday's and the day before's doses are long past.
    await create_schedule(client, owner, device, start="08:00", end="08:30", tolerance=15)
    await _backdate(db, device.id)
    await _set_online(db, device.id, datetime.now(UTC) - timedelta(days=1))
    settings = _settings(offline_flush_wait_seconds=0)
    now = datetime.now(UTC)

    await run_once(get_sessionmaker(), now, settings)
    missed = await _count(db, "SELECT count(*) FROM telemetry_logs WHERE status = 'MISSED'")
    notified = await _count(db, "SELECT count(*) FROM notifications WHERE type = 'DOSE_MISSED'")
    assert missed >= 2
    assert notified == missed  # one caregiver (the owner)

    # Second pass and a "restart" (fresh settings object, same DB): nothing new.
    await run_once(get_sessionmaker(), now, settings)
    await run_once(get_sessionmaker(), datetime.now(UTC), _settings(offline_flush_wait_seconds=0))
    assert await _count(db, "SELECT count(*) FROM telemetry_logs WHERE status = 'MISSED'") == missed
    assert await _count(db, "SELECT count(*) FROM notifications WHERE type = 'DOSE_MISSED'") == notified
    assert await _count(
        db, "SELECT count(*) FROM (SELECT schedule_id, scheduled_for FROM telemetry_logs GROUP BY 1, 2 HAVING count(*) > 1) d"
    ) == 0


async def test_offline_device_is_not_marked_missed_until_flush(
    client: httpx.AsyncClient, db: asyncpg.Connection
) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    await create_schedule(client, owner, device, start="08:00", end="08:30", tolerance=15)
    await _backdate(db, device.id)
    # Device is OFFLINE (never sent anything). Max wait is long, so no decision.
    patient = _settings(offline_max_wait_minutes=60 * 24 * 10, offline_flush_wait_seconds=60)
    await run_once(get_sessionmaker(), datetime.now(UTC), patient)
    # Today's dose may still be inside its window, so only count past deadlines.
    overdue = await _count(
        db, "SELECT count(*) FROM telemetry_logs WHERE status = 'PENDING' AND deadline_at <= now()"
    )
    assert overdue >= 2
    assert await _count(db, "SELECT count(*) FROM telemetry_logs WHERE status = 'MISSED'") == 0

    # Wi-Fi returns: the device flushes yesterday's dose (taken late at 08:40).
    yesterday = (datetime.now(ZoneInfo("Asia/Jakarta")).date() - timedelta(days=1)).isoformat()
    res = await send_telemetry(
        client, device, [event("ev-y", "COMPARTMENT_OPENED", f"{yesterday}T08:40:00+07:00")], is_offline_flush=True
    )
    assert res.status_code == 200 and res.json()["accepted"] == 1

    # Just reconnected: still inside the flush wait -> no decision yet.
    await run_once(get_sessionmaker(), datetime.now(UTC), patient)
    assert await _count(db, "SELECT count(*) FROM telemetry_logs WHERE status = 'MISSED'") == 0

    # After the flush wait the remaining doses are decided; the flushed one stays TAKEN.
    await run_once(get_sessionmaker(), datetime.now(UTC), _settings(offline_flush_wait_seconds=0))
    taken = await db.fetch("SELECT delay_minutes FROM telemetry_logs WHERE status = 'TAKEN'")
    assert len(taken) == 1 and taken[0]["delay_minutes"] == 10
    assert await _count(db, "SELECT count(*) FROM telemetry_logs WHERE status = 'MISSED'") == overdue - 1


async def test_late_evidence_upgrades_missed_and_resolves_alert(
    client: httpx.AsyncClient, db: asyncpg.Connection
) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    await create_schedule(client, owner, device, start="08:00", end="08:30", tolerance=15)
    await _backdate(db, device.id)
    # Gave up waiting for an offline device (max wait 0) -> MISSED.
    await run_once(get_sessionmaker(), datetime.now(UTC), _settings(offline_max_wait_minutes=0))
    row = await db.fetchrow(
        "SELECT id, scheduled_date FROM telemetry_logs WHERE status = 'MISSED' ORDER BY scheduled_for LIMIT 1"
    )
    assert row is not None
    day = row["scheduled_date"].isoformat()
    await send_telemetry(client, device, [event("ev-late", "COMPARTMENT_OPENED", f"{day}T08:20:00+07:00")])
    upgraded = await db.fetchrow("SELECT status, delay_minutes FROM telemetry_logs WHERE id = $1", row["id"])
    assert upgraded["status"] == "TAKEN" and upgraded["delay_minutes"] == 0
    assert await _count(
        db, "SELECT count(*) FROM notifications WHERE telemetry_log_id = $1 AND type = 'DOSE_MISSED' AND NOT is_resolved",
        row["id"],
    ) == 0
