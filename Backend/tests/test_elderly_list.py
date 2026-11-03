"""GET /elderly (home screen list) against a real database."""

import uuid
from typing import Any

import asyncpg
import httpx
from sqlalchemy import event as sa_event

from app.db.session import get_engine
from tests.helpers import API, Caregiver, create_caregiver, create_schedule, paired_device


async def _list(client: httpx.AsyncClient, owner: Caregiver) -> tuple[list[dict[str, Any]], int]:
    executed: list[str] = []

    def count(*_: Any) -> None:
        executed.append("x")

    sa_event.listen(get_engine().sync_engine, "before_cursor_execute", count)
    try:
        res = await client.get(f"{API}/elderly", params={"limit": 50}, headers=owner.headers)
    finally:
        sa_event.remove(get_engine().sync_engine, "before_cursor_execute", count)
    assert res.status_code == 200, res.text
    return res.json()["data"], len(executed)


async def test_list_summarizes_each_elderly_with_a_fixed_number_of_queries(
    client: httpx.AsyncClient, db: asyncpg.Connection
) -> None:
    owner = await create_caregiver(db, "Owner")
    first = await paired_device(client, owner)
    await create_schedule(client, owner, first, slot=8, start="23:30", end="23:30")
    _, one_elderly = await _list(client, owner)

    second = await paired_device(client, owner)
    await paired_device(client, owner)
    await db.execute(
        "INSERT INTO notifications (user_id, elderly_id, type, severity, message) VALUES ($1, $2, 'DOSE_MISSED', 'CRITICAL', 'x')",
        owner.id,
        uuid.UUID(second.elderly_id),
    )
    items, three_elderly = await _list(client, owner)

    assert three_elderly == one_elderly  # not one query (or four) per elderly
    by_id = {item["id"]: item for item in items}
    assert len(by_id) == 3
    a, b = by_id[first.elderly_id], by_id[second.elderly_id]
    assert a["device_count"] == 1 and a["today_summary"]["scheduled"] == 1 and a["today_summary"]["pending"] == 1
    assert a["open_alert_count"] == 0 and a["overall_indicator"] == "GREEN"
    assert b["open_alert_count"] == 1 and b["today_summary"]["scheduled"] == 0 and b["overall_indicator"] == "GRAY"
