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
