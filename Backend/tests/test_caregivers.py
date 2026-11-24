"""Caregiver roles and invitations by code (docs/ROLES_FEATURE_PLAN.md, phases R1 and R2)."""

import asyncio
import uuid
from typing import Any

import asyncpg
import httpx

from app.core.config import get_settings
from app.services.app_hub import AppConnection, app_hub
from app.services.invitations import hash_code, normalize_code
from tests.helpers import API, Caregiver, PairedDevice, create_caregiver, paired_device


class _FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, message: dict[str, Any]) -> None:
        self.sent.append(message)


async def _settle_hub() -> None:
    """Role refreshes run in tasks scheduled after commit (they query the database)."""
    for _ in range(50):
        await asyncio.sleep(0)
        pending = list(app_hub._tasks)
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


async def _invite(client: httpx.AsyncClient, by: Caregiver, elderly_id: str, role: str, label: str | None = None) -> httpx.Response:
    body: dict[str, Any] = {"role": role}
    if label is not None:
        body["relationship_label"] = label
    return await client.post(f"{API}/elderly/{elderly_id}/invitations", json=body, headers=by.headers)


async def _member(client: httpx.AsyncClient, db: asyncpg.Connection, owner: Caregiver, device: PairedDevice, role: str, name: str) -> Caregiver:
    """A caregiver who joined through an invitation code."""
    res = await _invite(client, owner, device.elderly_id, role)
    assert res.status_code == 201, res.text
    who = await create_caregiver(db, name)
    accepted = await client.post(f"{API}/invitations/accept", json={"code": res.json()["code"]}, headers=who.headers)
    assert accepted.status_code == 200, accepted.text
    return who


def _role_of(page: dict[str, Any], user_id: uuid.UUID) -> str:
    return next(c["role"] for c in page["data"] if c["caregiver_id"] == str(user_id))


# --- R1: change a caregiver's role -------------------------------------------------------

async def test_owner_changes_a_caregivers_role(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    viewer = await _member(client, db, owner, device, "PEMANTAU", "Viewer")
    url = f"{API}/elderly/{device.elderly_id}/caregivers/{viewer.id}"

    edit = await client.put(f"{API}/elderly/{device.elderly_id}", json={"full_name": "Oma Sari"}, headers=viewer.headers)
    assert edit.status_code == 403

    res = await client.put(url, json={"role": "ADMIN"}, headers=owner.headers)
    assert res.status_code == 200, res.text
    assert res.json()["role"] == "ADMIN" and res.json()["full_name"] == "Viewer"
    edit = await client.put(f"{API}/elderly/{device.elderly_id}", json={"full_name": "Oma Sari"}, headers=viewer.headers)
    assert edit.status_code == 200, edit.text

    res = await client.put(url, json={"role": "PEMANTAU"}, headers=owner.headers)
    assert res.status_code == 200
    page = (await client.get(f"{API}/elderly/{device.elderly_id}/caregivers", headers=owner.headers)).json()
    assert _role_of(page, viewer.id) == "PEMANTAU"


async def test_only_the_owner_changes_roles(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    admin = await _member(client, db, owner, device, "ADMIN", "Admin")
    viewer = await _member(client, db, owner, device, "PEMANTAU", "Viewer")
    stranger = await create_caregiver(db, "Stranger")
    base = f"{API}/elderly/{device.elderly_id}/caregivers"

    res = await client.put(f"{base}/{viewer.id}", json={"role": "ADMIN"}, headers=admin.headers)
    assert res.status_code == 403 and res.json()["error"]["code"] == "OWNER_ONLY"
    res = await client.put(f"{base}/{viewer.id}", json={"role": "ADMIN"}, headers=stranger.headers)
    assert res.status_code == 404
    res = await client.put(f"{base}/{owner.id}", json={"role": "ADMIN"}, headers=owner.headers)
    assert res.status_code == 409 and res.json()["error"]["code"] == "CANNOT_CHANGE_OWNER_ROLE"
    res = await client.put(f"{base}/{uuid.uuid4()}", json={"role": "ADMIN"}, headers=owner.headers)
    assert res.status_code == 404 and res.json()["error"]["code"] == "CAREGIVER_NOT_FOUND"
    res = await client.put(f"{base}/{viewer.id}", json={"role": "OWNER"}, headers=owner.headers)
    assert res.status_code == 422


async def test_an_admin_grants_monitor_access_only(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    admin = await _member(client, db, owner, device, "ADMIN", "Admin")
    other = await create_caregiver(db, "Other")

    res = await _invite(client, admin, device.elderly_id, "ADMIN")
    assert res.status_code == 403
    res = await client.post(
        f"{API}/elderly/{device.elderly_id}/caregivers", json={"email": other.email, "role": "ADMIN"}, headers=admin.headers
    )
    assert res.status_code == 403  # the legacy email invite follows the same rule
    res = await _invite(client, admin, device.elderly_id, "PEMANTAU")
    assert res.status_code == 201, res.text


async def test_invitations_are_rate_limited_per_inviter(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    allowed = get_settings().caregiver_invite_max_attempts
    for _ in range(allowed):
        assert (await _invite(client, owner, device.elderly_id, "PEMANTAU")).status_code == 201
    res = await _invite(client, owner, device.elderly_id, "PEMANTAU")
    assert res.status_code == 429 and res.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"
    assert "Retry-After" in res.headers


async def test_member_limit(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    limit = get_settings().max_caregivers_per_elderly
    for i in range(limit - 2):  # owner + these = limit - 1 members
        await _member(client, db, owner, device, "PEMANTAU", f"Member{i}")
    late_code = (await _invite(client, owner, device.elderly_id, "PEMANTAU")).json()["code"]
    await _member(client, db, owner, device, "PEMANTAU", "Last")  # now exactly at the limit

    res = await _invite(client, owner, device.elderly_id, "PEMANTAU")
    assert res.status_code == 409 and res.json()["error"]["code"] == "MEMBER_LIMIT_REACHED"
    late = await create_caregiver(db, "Late")
    res = await client.post(f"{API}/invitations/accept", json={"code": late_code}, headers=late.headers)
    assert res.status_code == 409 and res.json()["error"]["code"] == "MEMBER_LIMIT_REACHED"
    joiner = await create_caregiver(db, "Joiner")
    res = await client.post(f"{API}/devices/{device.id}/join", json={"device_pin": device.pin}, headers=joiner.headers)
    assert res.status_code == 409 and res.json()["error"]["code"] == "MEMBER_LIMIT_REACHED"


# --- R2: invitations by code -------------------------------------------------------------

async def test_invitation_code_round_trip(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    created = await _invite(client, owner, device.elderly_id, "PEMANTAU", label="Cucu")
    assert created.status_code == 201, created.text
    body = created.json()
    code = body["code"]
    assert normalize_code(code) is not None and body["role"] == "PEMANTAU" and body["relationship_label"] == "Cucu"

    pending = (await client.get(f"{API}/elderly/{device.elderly_id}/invitations", headers=owner.headers)).json()
    assert pending["total"] == 1 and "code" not in pending["data"][0]
    assert pending["data"][0]["invited_by_name"] == "Owner"

    invitee = await create_caregiver(db, "Invitee")
    assert (await client.get(f"{API}/elderly/{device.elderly_id}", headers=invitee.headers)).status_code == 404
    # Typed by a person: lowercase, spaces instead of the dash.
    typed = code.lower().replace("-", " ")
    preview = await client.post(f"{API}/invitations/preview", json={"code": typed}, headers=invitee.headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["elderly_name"] == "Oma" and preview.json()["invited_by_name"] == "Owner"
    assert preview.json()["role"] == "PEMANTAU" and "elderly_id" not in preview.json()

    accepted = await client.post(f"{API}/invitations/accept", json={"code": code}, headers=invitee.headers)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {"elderly_id": device.elderly_id, "my_role": "PEMANTAU"}
    assert (await client.get(f"{API}/elderly/{device.elderly_id}", headers=invitee.headers)).status_code == 200
    page = (await client.get(f"{API}/elderly/{device.elderly_id}/caregivers", headers=owner.headers)).json()
    assert _role_of(page, invitee.id) == "PEMANTAU"
    assert next(c for c in page["data"] if c["caregiver_id"] == str(invitee.id))["relationship_label"] == "Cucu"

    pending = (await client.get(f"{API}/elderly/{device.elderly_id}/invitations", headers=owner.headers)).json()
    assert pending["total"] == 0
    other = await create_caregiver(db, "Other")
    reused = await client.post(f"{API}/invitations/accept", json={"code": code}, headers=other.headers)
    assert reused.status_code == 404 and reused.json()["error"]["code"] == "INVITATION_INVALID"


async def test_every_unusable_code_answers_the_same(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    invitee = await create_caregiver(db, "Invitee")
    revoked = (await _invite(client, owner, device.elderly_id, "PEMANTAU")).json()
    res = await client.delete(
        f"{API}/elderly/{device.elderly_id}/invitations/{revoked['invitation_id']}", headers=owner.headers
    )
    assert res.status_code == 204
    expired = (await _invite(client, owner, device.elderly_id, "PEMANTAU")).json()
    await db.execute(
        "UPDATE invitations SET expires_at = now() - interval '1 minute' WHERE id = $1", uuid.UUID(expired["invitation_id"])
    )

    for code in ("not-a-code", "ABCD-EFGH", revoked["code"], expired["code"]):
        for action in ("preview", "accept"):
            res = await client.post(f"{API}/invitations/{action}", json={"code": code}, headers=invitee.headers)
            assert res.status_code == 404, (code, action, res.text)
            assert res.json()["error"]["code"] == "INVITATION_INVALID"


async def test_a_member_cannot_use_another_code(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    viewer = await _member(client, db, owner, device, "PEMANTAU", "Viewer")
    code = (await _invite(client, owner, device.elderly_id, "ADMIN")).json()["code"]
    for action in ("preview", "accept"):
        res = await client.post(f"{API}/invitations/{action}", json={"code": code}, headers=viewer.headers)
        assert res.status_code == 409 and res.json()["error"]["code"] == "ALREADY_CAREGIVER"
    # The code stays usable for someone else.
    pending = (await client.get(f"{API}/elderly/{device.elderly_id}/invitations", headers=owner.headers)).json()
    assert pending["total"] == 1


async def test_code_guesses_are_rate_limited(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    guesser = await create_caregiver(db, "Guesser")
    allowed = get_settings().invitation_code_max_attempts
    for _ in range(allowed):
        res = await client.post(f"{API}/invitations/preview", json={"code": "ABCD-EFGH"}, headers=guesser.headers)
        assert res.status_code == 404
    res = await client.post(f"{API}/invitations/accept", json={"code": "ABCD-EFGH"}, headers=guesser.headers)
    assert res.status_code == 429 and res.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"


async def test_revoking_invitations(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    admin = await _member(client, db, owner, device, "ADMIN", "Admin")
    viewer = await _member(client, db, owner, device, "PEMANTAU", "Viewer")
    base = f"{API}/elderly/{device.elderly_id}/invitations"
    owners = (await _invite(client, owner, device.elderly_id, "PEMANTAU")).json()["invitation_id"]
    admins = (await _invite(client, admin, device.elderly_id, "PEMANTAU")).json()["invitation_id"]

    assert (await client.get(base, headers=viewer.headers)).status_code == 403
    assert (await client.delete(f"{base}/{admins}", headers=viewer.headers)).status_code == 403
    res = await client.delete(f"{base}/{owners}", headers=admin.headers)
    assert res.status_code == 404 and res.json()["error"]["code"] == "INVITATION_NOT_FOUND"
    assert (await client.delete(f"{base}/{admins}", headers=admin.headers)).status_code == 204
    assert (await client.delete(f"{base}/{owners}", headers=owner.headers)).status_code == 204
    assert (await client.get(base, headers=owner.headers)).json()["total"] == 0


async def test_codes_die_when_the_inviter_loses_the_right(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    admin = await _member(client, db, owner, device, "ADMIN", "Admin")
    outsider = await create_caregiver(db, "Outsider")
    caregivers = f"{API}/elderly/{device.elderly_id}/caregivers"
    base = f"{API}/elderly/{device.elderly_id}/invitations"

    # Demoted: the ADMIN's code is revoked, no longer listed, and refused.
    demoted = (await _invite(client, admin, device.elderly_id, "PEMANTAU")).json()["code"]
    res = await client.put(f"{caregivers}/{admin.id}", json={"role": "PEMANTAU"}, headers=owner.headers)
    assert res.status_code == 200
    assert (await client.get(base, headers=owner.headers)).json()["total"] == 0
    res = await client.post(f"{API}/invitations/preview", json={"code": demoted}, headers=outsider.headers)
    assert res.status_code == 404 and res.json()["error"]["code"] == "INVITATION_INVALID"
    # Promoting them back does not bring the old code back to life.
    await client.put(f"{caregivers}/{admin.id}", json={"role": "ADMIN"}, headers=owner.headers)
    res = await client.post(f"{API}/invitations/preview", json={"code": demoted}, headers=outsider.headers)
    assert res.status_code == 404

    # Removed: same.
    removed = (await _invite(client, admin, device.elderly_id, "PEMANTAU")).json()["code"]
    assert (await client.delete(f"{caregivers}/{admin.id}", headers=owner.headers)).status_code == 204
    res = await client.post(f"{API}/invitations/accept", json={"code": removed}, headers=outsider.headers)
    assert res.status_code == 404 and res.json()["error"]["code"] == "INVITATION_INVALID"

    # Former owner after a transfer: their ADMIN invitation is revoked, a PEMANTAU one stays valid.
    new_owner = await _member(client, db, owner, device, "ADMIN", "Next owner")
    as_admin = (await _invite(client, owner, device.elderly_id, "ADMIN")).json()["code"]
    as_monitor = (await _invite(client, owner, device.elderly_id, "PEMANTAU")).json()["code"]
    res = await client.post(
        f"{API}/elderly/{device.elderly_id}/transfer-ownership",
        json={"new_owner_caregiver_id": str(new_owner.id)},
        headers=owner.headers,
    )
    assert res.status_code == 200
    res = await client.post(f"{API}/invitations/preview", json={"code": as_admin}, headers=outsider.headers)
    assert res.status_code == 404
    res = await client.post(f"{API}/invitations/preview", json={"code": as_monitor}, headers=outsider.headers)
    assert res.status_code == 200 and res.json()["role"] == "PEMANTAU"


async def test_the_code_is_stored_only_as_a_hash(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    code = (await _invite(client, owner, device.elderly_id, "PEMANTAU")).json()["code"]
    row = await db.fetchrow("SELECT code_hash, invitee_email, status FROM invitations")
    assert row["code_hash"] == hash_code(normalize_code(code) or "")
    assert code not in row["code_hash"] and normalize_code(code) not in row["code_hash"]
    assert row["invitee_email"] is None and row["status"] == "PENDING"


async def test_role_changes_reach_the_apps_at_once(client: httpx.AsyncClient, db: asyncpg.Connection) -> None:
    owner = await create_caregiver(db, "Owner")
    device = await paired_device(client, owner)
    owner_socket = _FakeSocket()
    app_hub.register(AppConnection(owner.id, {uuid.UUID(device.elderly_id)}, owner_socket))  # type: ignore[arg-type]
    invitee = await create_caregiver(db, "Invitee")
    invitee_socket = _FakeSocket()
    invitee_conn = AppConnection(invitee.id, set(), invitee_socket)  # type: ignore[arg-type]
    app_hub.register(invitee_conn)

    code = (await _invite(client, owner, device.elderly_id, "PEMANTAU")).json()["code"]
    assert (await client.post(f"{API}/invitations/accept", json={"code": code}, headers=invitee.headers)).status_code == 200
    await _settle_hub()
    assert {"type": "roles"} in invitee_socket.sent and {"type": "roles"} in owner_socket.sent
    assert invitee_conn.elderly_ids == {uuid.UUID(device.elderly_id)}  # now follows the elderly

    invitee_socket.sent.clear()
    res = await client.put(
        f"{API}/elderly/{device.elderly_id}/caregivers/{invitee.id}", json={"role": "ADMIN"}, headers=owner.headers
    )
    assert res.status_code == 200
    await _settle_hub()
    assert {"type": "roles"} in invitee_socket.sent
