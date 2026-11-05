"""Caregiver-app WebSockets (/ws/app) and the updates pushed on them.

Messages carry the changed data, so the app updates without a refetch (each
refetch is several round trips to the remote database):
    {"type": "notifications", "items": [<NotificationItem subset>, ...]}
        new notification rows for this user, oldest first. Fields: id, type,
        severity, elderly_id, device_id, slot_number, delay_minutes, message,
        is_read, is_resolved, created_at (same values GET /notifications returns).
    {"type": "device", "device_id": "<uuid>", "status": <DeviceStatusOut> | absent}
        a device the user follows changed; `status` is the GET
        /devices/{id}/status body. Without `status` the app refetches.
Who receives what follows the REST rules: notifications go only to their
user, device updates only to users with a role on the device's elderly.
The app keeps polling as a fallback, so a lost message costs one poll interval.

Messages are queued on the DB session (queue_*) and sent only AFTER the
transaction commits, so the app never sees uncommitted data and a rollback
sends nothing.

State lives in this process only: run uvicorn with ONE worker (same rule as
connection_manager.py).
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from app.core.config import get_settings
from app.models import UserElderlyRole

logger = logging.getLogger(__name__)

# Status fields that change on every heartbeat by themselves. A status that differs only in
# these is pushed at most every APP_WS_DEVICE_PUSH_MIN_INTERVAL_SECONDS (it used to go to every
# follower on every heartbeat); any other change is pushed at once.
_VOLATILE_STATUS_FIELDS = frozenset({"last_seen_at", "device_time", "estimated_battery_days_remaining"})

_USERS_KEY = "app_hub_notifications"  # {user_id: [item, ...]}
_DEVICES_KEY = "app_hub_device_changes"  # {device_id: _DeviceChange}
_ROLES_KEY = "app_hub_roles_changed"  # {user_id, ...}

StatusBuilder = Callable[[], dict[str, Any]]


@dataclass
class _DeviceChange:
    device_id: UUID
    elderly_id: UUID
    # Called after commit, so it sees the committed values of the loaded row.
    status: StatusBuilder | None


@dataclass(eq=False)
class AppConnection:
    user_id: UUID
    elderly_ids: set[UUID]
    websocket: WebSocket
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class AppHub:
    def __init__(self) -> None:
        self._connections: set[AppConnection] = set()
        # Indexes, so a publish touches only the sockets it addresses (not every socket).
        self._by_user: dict[UUID, set[AppConnection]] = {}
        self._by_elderly: dict[UUID, set[AppConnection]] = {}
        # device_id -> (status without volatile fields, monotonic time it was last pushed)
        self._last_status: dict[UUID, tuple[dict[str, Any], float]] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def register(self, conn: AppConnection) -> None:
        self._connections.add(conn)
        self._by_user.setdefault(conn.user_id, set()).add(conn)
        self._index_elderly(conn, conn.elderly_ids)

    def unregister(self, conn: AppConnection) -> None:
        self._connections.discard(conn)
        _discard(self._by_user, conn.user_id, conn)
        for elderly_id in conn.elderly_ids:
            _discard(self._by_elderly, elderly_id, conn)

    def set_elderly(self, conn: AppConnection, elderly_ids: set[UUID]) -> None:
        """The elderly a connected user follows changed (resubscribe)."""
        for elderly_id in conn.elderly_ids - elderly_ids:
            _discard(self._by_elderly, elderly_id, conn)
        conn.elderly_ids = elderly_ids
        if conn in self._connections:
            self._index_elderly(conn, elderly_ids)

    def clear(self) -> None:
        self._connections.clear()
        self._by_user.clear()
        self._by_elderly.clear()
        self._last_status.clear()

    def _index_elderly(self, conn: AppConnection, elderly_ids: set[UUID]) -> None:
        for elderly_id in elderly_ids:
            self._by_elderly.setdefault(elderly_id, set()).add(conn)

    async def _send(self, conn: AppConnection, message: dict[str, Any], timeout: float) -> None:
        try:
            async with conn.send_lock:
                await asyncio.wait_for(conn.websocket.send_json(message), timeout=timeout)
        except TimeoutError:
            # A client that does not read would otherwise pile up publish tasks behind its lock.
            logger.warning("app_ws_send_timeout", extra={"user_id": str(conn.user_id)})
            self.unregister(conn)
            try:
                await conn.websocket.close()
            except (WebSocketDisconnect, RuntimeError, OSError):
                pass
        except (WebSocketDisconnect, RuntimeError, OSError):
            self.unregister(conn)  # the handler's finally also cleans up

    async def publish(
        self, notifications: dict[UUID, list[dict[str, Any]]], devices: list[tuple[UUID, dict[str, Any]]]
    ) -> None:
        """notifications: {user_id: items}; devices: [(elderly_id, device message)]."""
        timeout = get_settings().app_ws_send_timeout_seconds
        sends = []
        for user_id, items in notifications.items():
            if items:
                for conn in list(self._by_user.get(user_id, ())):
                    sends.append(self._send(conn, {"type": "notifications", "items": items}, timeout))
        for elderly_id, message in devices:
            for conn in list(self._by_elderly.get(elderly_id, ())):
                sends.append(self._send(conn, message, timeout))
        if sends:
            await asyncio.gather(*sends)
        logger.info(
            "app_hints_sent",
            extra={"notifications": len(notifications), "devices": len(devices), "sockets_hinted": len(sends)},
        )

    def publish_soon(
        self, notifications: dict[UUID, list[dict[str, Any]]], changes: dict[UUID, _DeviceChange]
    ) -> None:
        """Called from the commit hook (sync code on the event-loop thread)."""
        if not self._connections:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # not inside the server's loop (e.g. a script)
        devices = [
            (change.elderly_id, message)
            for change in changes.values()
            if self._worth_pushing(message := _device_message(change))
        ]
        if not notifications and not devices:
            return
        task = loop.create_task(self.publish(notifications, devices))
        self._tasks.add(task)  # keep a reference until it finishes
        task.add_done_callback(self._task_done)


    def refresh_roles_soon(self, user_ids: set[UUID]) -> None:
        """Called from the commit hook: reload which elderly these users' open sockets follow, so
        a removed caregiver stops (and a new one starts) receiving that elderly's pushes without
        the app sending "resubscribe"."""
        connected = {user_id for user_id in user_ids if user_id in self._by_user}
        if not connected:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._refresh_roles(connected))
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: "asyncio.Task[None]") -> None:
        """Never-awaited tasks would otherwise lose their exception silently."""
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("app_hub_task_failed", exc_info=task.exception())

    async def _refresh_roles(self, user_ids: set[UUID]) -> None:
        # Imported here: app.db.session is not needed by the rest of this module.
        from app.db.session import get_sessionmaker

        try:
            async with get_sessionmaker()() as session:
                followed = await followed_elderly(session, user_ids)
        except Exception:
            # Without fresh roles a removed caregiver would keep receiving pushes: close their
            # sockets instead; the app reconnects and the roles are read again at auth.
            logger.warning("app_hub_role_refresh_failed", exc_info=True)
            for user_id in user_ids:
                for conn in list(self._by_user.get(user_id, ())):
                    self.unregister(conn)
                    try:
                        await asyncio.wait_for(conn.websocket.close(), get_settings().app_ws_send_timeout_seconds)
                    except (TimeoutError, WebSocketDisconnect, RuntimeError, OSError):
                        pass
            return
        for user_id in user_ids:
            for conn in list(self._by_user.get(user_id, ())):
                self.set_elderly(conn, followed.get(user_id, set()))

    def _worth_pushing(self, message: dict[str, Any]) -> bool:
        """False for a status that only moved its volatile fields and was pushed recently."""
        status = message.get("status")
        if status is None:
            return True  # a refetch hint: always worth it
        device_id = UUID(message["device_id"])
        significant = {k: v for k, v in status.items() if k not in _VOLATILE_STATUS_FIELDS}
        now = time.monotonic()
        previous = self._last_status.get(device_id)
        min_interval = get_settings().app_ws_device_push_min_interval_seconds
        if previous is not None and previous[0] == significant and now - previous[1] < min_interval:
            return False
        self._last_status[device_id] = (significant, now)
        return True


def _discard(index: dict[UUID, set[AppConnection]], key: UUID, conn: AppConnection) -> None:
    conns = index.get(key)
    if conns is not None:
        conns.discard(conn)
        if not conns:
            del index[key]


def _device_message(change: _DeviceChange) -> dict[str, Any]:
    message: dict[str, Any] = {"type": "device", "device_id": str(change.device_id)}
    if change.status is not None:
        try:
            message["status"] = change.status()
        except Exception:
            # Never fail a commit hook: the app refetches when status is absent.
            logger.exception("app_hub_status_build_failed", extra={"device_id": str(change.device_id)})
    return message


app_hub = AppHub()


async def followed_elderly(session: AsyncSession, user_ids: set[UUID]) -> dict[UUID, set[UUID]]:
    """user_id -> the elderly the user has a role on (what their app socket follows)."""
    rows = await session.execute(
        select(UserElderlyRole.user_id, UserElderlyRole.elderly_id).where(UserElderlyRole.user_id.in_(list(user_ids)))
    )
    followed: dict[UUID, set[UUID]] = {user_id: set() for user_id in user_ids}
    for user_id, elderly_id in rows.all():
        followed[user_id].add(elderly_id)
    return followed


# --- queuing on the DB session ----------------------------------------------

def queue_notifications(session: AsyncSession, items_by_user: dict[UUID, list[dict[str, Any]]]) -> None:
    queued: dict[UUID, list[dict[str, Any]]] = session.info.setdefault(_USERS_KEY, {})
    for user_id, items in items_by_user.items():
        queued.setdefault(user_id, []).extend(items)


def queue_roles_changed(session: AsyncSession, *user_ids: UUID) -> None:
    """A caregiver gained or lost a role: refresh their open app sockets after commit."""
    session.info.setdefault(_ROLES_KEY, set()).update(user_ids)


def queue_device_change(
    session: AsyncSession, elderly_id: UUID | None, device_id: UUID, status: StatusBuilder | None = None
) -> None:
    """status builds the GET /devices/{id}/status body; pass it when the device
    row is loaded so the app needs no refetch."""
    if elderly_id is None:
        return
    queued: dict[UUID, _DeviceChange] = session.info.setdefault(_DEVICES_KEY, {})
    previous = queued.get(device_id)
    if status is None and previous is not None:
        status = previous.status  # keep the richer message
    queued[device_id] = _DeviceChange(device_id, elderly_id, status)


QueuedPushes = tuple[dict[UUID, list[dict[str, Any]]], dict[UUID, _DeviceChange], set[UUID]]


def snapshot_queued(session: AsyncSession) -> QueuedPushes:
    """The pushes queued so far, for restore_queued() after a rolled-back SAVEPOINT (the queue is
    only dropped when the outermost transaction ends)."""
    return (
        {user_id: list(items) for user_id, items in session.info.get(_USERS_KEY, {}).items()},
        dict(session.info.get(_DEVICES_KEY, {})),
        set(session.info.get(_ROLES_KEY, set())),
    )


def restore_queued(session: AsyncSession, snapshot: QueuedPushes) -> None:
    for key, value in zip((_USERS_KEY, _DEVICES_KEY, _ROLES_KEY), snapshot, strict=True):
        if value:
            session.info[key] = value
        else:
            session.info.pop(key, None)


@event.listens_for(Session, "after_commit")
def _publish_after_commit(session: Session) -> None:
    notifications = session.info.pop(_USERS_KEY, None) or {}
    changes = session.info.pop(_DEVICES_KEY, None) or {}
    roles_changed = session.info.pop(_ROLES_KEY, None) or set()
    if notifications or changes:
        app_hub.publish_soon(notifications, changes)
    if roles_changed:
        app_hub.refresh_roles_soon(roles_changed)


@event.listens_for(Session, "after_transaction_end")
def _drop_after_rollback(session: Session, transaction: SessionTransaction) -> None:
    # after_commit already consumed the queue; anything left was rolled back.
    if transaction.parent is None:
        session.info.pop(_USERS_KEY, None)
        session.info.pop(_DEVICES_KEY, None)
        session.info.pop(_ROLES_KEY, None)
