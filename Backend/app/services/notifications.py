"""Writes caregiver notifications to the DB, honoring notification_preferences.

Idempotency: every notification carries an `event_key` naming the incident
(e.g. "DOSE_MISSED:<telemetry_log_id>"). (event_key, user_id) is unique, so
re-running the rules engine, retrying telemetry, or restarting the server
can never create the same notification twice.

Push delivery (Expo/FCM) is NOT implemented: see dispatch_push().
"""

import logging
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Elderly, Notification, NotificationPreference, User, UserElderlyRole
from app.models.enums import NotificationType, Severity

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Preferences:
    """Effective preferences. Defaults mirror the column defaults in
    migrations/0001 and apply when a caregiver never saved preferences."""

    push_enabled: bool = True
    notify_on_missed: bool = True
    notify_on_taken: bool = False
    notify_on_device_offline: bool = True
    device_offline_after_minutes: int = 10
    notify_on_low_battery: bool = True

    @classmethod
    def from_row(cls, row: NotificationPreference | None) -> "Preferences":
        if row is None:
            return cls()
        return cls(
            push_enabled=row.push_enabled,
            notify_on_missed=row.notify_on_missed,
            notify_on_taken=row.notify_on_taken,
            notify_on_device_offline=row.notify_on_device_offline,
            device_offline_after_minutes=row.device_offline_after_minutes,
            notify_on_low_battery=row.notify_on_low_battery,
        )


@dataclass(frozen=True)
class Recipient:
    user_id: UUID
    language: str  # "ID" | "EN"
    prefs: Preferences


def wants(prefs: Preferences, ntype: NotificationType) -> bool:
    # ASSUMPTION: the API List only has notify_on_missed (always true) and
    # notify_on_taken. DOSE_LATE belongs to the mandatory "Terlambat &
    # Terlewat" tab, so it follows notify_on_missed; UNSCHEDULED_OPEN is a
    # safety alert and is always sent.
    match ntype:
        case NotificationType.DOSE_MISSED | NotificationType.DOSE_LATE:
            return prefs.notify_on_missed
        case NotificationType.DOSE_TAKEN:
            return prefs.notify_on_taken
        case NotificationType.DEVICE_OFFLINE | NotificationType.DEVICE_ONLINE:
            return prefs.notify_on_device_offline
        case NotificationType.LOW_BATTERY:
            return prefs.notify_on_low_battery
        case NotificationType.UNSCHEDULED_OPEN:
            return True
    return False


async def load_recipients(session: AsyncSession, elderly_id: UUID) -> list[Recipient]:
    rows = await session.execute(
        select(User.id, User.interface_language, NotificationPreference)
        .join(UserElderlyRole, UserElderlyRole.user_id == User.id)
        .join(Elderly, Elderly.id == UserElderlyRole.elderly_id)
        .outerjoin(
            NotificationPreference,
            (NotificationPreference.user_id == User.id)
            & (NotificationPreference.elderly_id == UserElderlyRole.elderly_id),
        )
        .where(UserElderlyRole.elderly_id == elderly_id, Elderly.deleted_at.is_(None))
    )
    return [
        Recipient(user_id=uid, language=(lang or "ID").upper(), prefs=Preferences.from_row(pref))
        for uid, lang, pref in rows.all()
    ]


# --- message templates ------------------------------------------------------

_TEMPLATES: dict[NotificationType, dict[str, str]] = {
    NotificationType.DOSE_MISSED: {
        "ID": "Dosis {slot} ({period}) jadwal {time} untuk {elderly} tidak diminum. Segera hubungi lansia.",
        "EN": "Dose {slot} ({period}) scheduled at {time} for {elderly} was missed. Please contact them.",
    },
    NotificationType.DOSE_LATE: {
        "ID": "Obat {slot} ({period}) untuk {elderly} diminum terlambat {delay} menit dari jadwal {time}.",
        "EN": "{elderly} took dose {slot} ({period}) {delay} minutes late (scheduled {time}).",
    },
    NotificationType.DOSE_TAKEN: {
        "ID": "Obat {slot} ({period}) untuk {elderly} diminum tepat waktu sesuai jadwal {time}.",
        "EN": "{elderly} took dose {slot} ({period}) on time (scheduled {time}).",
    },
    NotificationType.DEVICE_OFFLINE: {
        "ID": "{device} tidak terhubung sejak {since}. Periksa daya dan Wi-Fi.",
        "EN": "{device} has been offline since {since}. Check power and Wi-Fi.",
    },
    NotificationType.DEVICE_ONLINE: {
        "ID": "{device} kembali online dan data tersinkron.",
        "EN": "{device} is back online and synced.",
    },
    NotificationType.LOW_BATTERY: {
        "ID": "Baterai {device} tinggal {battery}%. Segera isi daya.",
        "EN": "{device} battery is at {battery}%. Please charge it.",
    },
    NotificationType.UNSCHEDULED_OPEN: {
        "ID": "Bilik {slot} pada {device} dibuka di luar jadwal pada {time}!",
        "EN": "Compartment {slot} on {device} was opened outside its schedule at {time}!",
    },
}


def render_message(ntype: NotificationType, language: str, params: dict[str, Any]) -> str:
    """A param value may be a {"ID": ..., "EN": ...} dict for localized fragments."""
    templates = _TEMPLATES[ntype]
    template = templates.get(language, templates["ID"])
    resolved = {
        key: (value.get(language, value.get("ID")) if isinstance(value, dict) else value)
        for key, value in params.items()
    }
    return template.format_map(_SafeDict(resolved))


class _SafeDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "-"


# --- writing ------------------------------------------------------------------

@dataclass
class NotificationSpec:
    type: NotificationType
    severity: Severity
    event_key: str
    elderly_id: UUID
    device_id: UUID | None = None
    telemetry_log_id: UUID | None = None
    params: dict[str, Any] = field(default_factory=dict)


async def notify(
    session: AsyncSession,
    spec: NotificationSpec,
    *,
    recipients: list[Recipient] | None = None,
    only_user_ids: Collection[UUID] | None = None,
) -> list[UUID]:
    """Inserts one notification per interested caregiver; returns new row ids.
    Does not commit."""
    if recipients is None:
        recipients = await load_recipients(session, spec.elderly_id)
    targets = [
        r for r in recipients
        if wants(r.prefs, spec.type) and (only_user_ids is None or r.user_id in only_user_ids)
    ]
    if not targets:
        return []
    values = [
        {
            "user_id": r.user_id,
            "elderly_id": spec.elderly_id,
            "device_id": spec.device_id,
            "telemetry_log_id": spec.telemetry_log_id,
            "type": spec.type.value,
            "severity": spec.severity.value,
            "message": render_message(spec.type, r.language, spec.params),
            "event_key": spec.event_key,
        }
        for r in targets
    ]
    stmt = (
        insert(Notification)
        .values(values)
        .on_conflict_do_nothing(
            index_elements=[Notification.event_key, Notification.user_id],
            index_where=Notification.event_key.is_not(None),
        )
        .returning(Notification.id, Notification.user_id)
    )
    inserted = (await session.execute(stmt)).all()
    if inserted:
        logger.info(
            "notifications_created",
            extra={"type": spec.type.value, "event_key": spec.event_key, "count": len(inserted)},
        )
        push_targets = {r.user_id for r in targets if r.prefs.push_enabled}
        await dispatch_push(
            session, [(nid, uid) for nid, uid in inserted if uid in push_targets]
        )
    return [nid for nid, _ in inserted]


async def dispatch_push(session: AsyncSession, notifications: list[tuple[UUID, UUID]]) -> None:
    """EXTENSION POINT for real push delivery (deliberately not implemented).

    To add Expo/FCM push: for each (notification_id, user_id), read
    push_tokens WHERE user_id = :user_id (app.models.PushToken), send via the
    Expo Push API / FCM, and delete tokens the provider reports as
    unregistered. Run delivery after the surrounding transaction commits
    (e.g. collect ids here and send from a background task) so a rollback
    never produces a push for a notification that does not exist.
    """
    if notifications:
        logger.debug("push_dispatch_not_implemented", extra={"count": len(notifications)})


def ts_key(dt: datetime) -> str:
    """Stable string form of a timestamp for event keys."""
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
