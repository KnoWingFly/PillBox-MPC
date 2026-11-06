"""DELETE /notifications/{id} and "Hapus semua" (DELETE /notifications?up_to_...)."""

import uuid
from datetime import UTC, datetime

import asyncpg
import httpx

from tests.helpers import API, create_caregiver, paired_device


async def _add(db: asyncpg.Connection, user_id: uuid.UUID, elderly_id: str, created_at: datetime, key: str) -> str:
    return str(
        await db.fetchval(
            "INSERT INTO notifications (user_id, elderly_id, type, severity, message, event_key, created_at) "
            "VALUES ($1, $2, 'DOSE_TAKEN', 'INFO', 'x', $3, $4) RETURNING id",
            user_id, uuid.UUID(elderly_id), key, created_at,
        )
    )


async def test_delete_one_and_delete_up_to(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    other = await create_caregiver(db, "Other")
    device = await paired_device(client, owner)
    t = [datetime(2026, 10, 17, 10, 0, s, 123456, tzinfo=UTC) for s in range(4)]
    ids = [await _add(db, owner.id, device.elderly_id, t[i], f"k{i}") for i in range(4)]
    others = await _add(db, other.id, device.elderly_id, t[0], "k0")  # another caregiver's copy

    assert (await client.delete(f"{API}/notifications/{ids[3]}", headers=owner.headers)).status_code == 204
    assert (await client.delete(f"{API}/notifications/{ids[3]}", headers=owner.headers)).status_code == 404
    assert (await client.delete(f"{API}/notifications/{others}", headers=owner.headers)).status_code == 404

    # Up to the 3rd one as the app knows it (milliseconds): it and the older ones go, nothing newer.
    boundary = t[2].replace(microsecond=123000).isoformat().replace("+00:00", "Z")
    res = await client.delete(
        f"{API}/notifications", params={"up_to_created_at": boundary, "up_to_id": ids[2]}, headers=owner.headers
    )
    assert res.status_code == 200 and res.json() == {"deleted": 3}
    assert await db.fetchval("SELECT count(*) FROM notifications WHERE user_id = $1", owner.id) == 0
    assert await db.fetchval("SELECT count(*) FROM notifications WHERE user_id = $1", other.id) == 1


async def test_feed_counts_follow_the_tab(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    rows = [  # (type, is_read, is_resolved)
        ("DOSE_MISSED", False, False), ("DOSE_LATE", True, False), ("DOSE_TAKEN", False, False), ("DOSE_MISSED", True, True),
    ]
    for ntype, read, resolved in rows:
        await db.execute(
            "INSERT INTO notifications (user_id, elderly_id, type, severity, message, is_read, is_resolved) "
            "VALUES ($1, $2, $3, 'WARNING', 'x', $4, $5)",
            owner.id, uuid.UUID(device.elderly_id), ntype, read, resolved,
        )

    async def counts(tab: str) -> tuple[int, int]:
        page = (await client.get(f"{API}/notifications", params={"tab": tab}, headers=owner.headers)).json()
        return page["total"], page["unread_count"]

    assert await counts("ALL") == (4, 2)
    assert await counts("LATE_MISSED") == (2, 2)  # unread is per user, not per tab
    assert await counts("RESOLVED") == (1, 2)


async def test_delete_one_pillboxs_notifications_in_one_call(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    """Mobile/BACKEND_HANDOFF.md item 3: the app used to page through the feed and DELETE each row."""
    owner = await create_caregiver(db, "Owner")
    first = await paired_device(client, owner)
    second = await paired_device(client, owner)
    viewer = await create_caregiver(db, "Viewer")
    for user, device in ((owner, first), (owner, first), (owner, second), (viewer, first)):
        await db.execute(
            "INSERT INTO notifications (user_id, elderly_id, device_id, type, severity, message) "
            "VALUES ($1, $2, $3, 'DOSE_TAKEN', 'INFO', 'x')",
            user.id, uuid.UUID(device.elderly_id), uuid.UUID(device.id),
        )

    res = await client.delete(f"{API}/notifications", params={"device_id": first.id}, headers=owner.headers)

    assert res.status_code == 200 and res.json() == {"deleted": 2}
    left = await db.fetch("SELECT user_id, device_id FROM notifications")
    assert {(r["user_id"], str(r["device_id"])) for r in left} == {(owner.id, second.id), (viewer.id, first.id)}
    unknown = await client.delete(f"{API}/notifications", params={"device_id": str(uuid.uuid4())}, headers=owner.headers)
    assert unknown.json() == {"deleted": 0}
    neither = await client.delete(f"{API}/notifications", headers=owner.headers)
    assert neither.status_code == 422
