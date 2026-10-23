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
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

logger = logging.getLogger(__name__)

_USERS_KEY = "app_hub_notifications"  # {user_id: [item, ...]}
_DEVICES_KEY = "app_hub_device_changes"  # {device_id: _DeviceChange}

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
        self._tasks: set[asyncio.Task[None]] = set()

    def register(self, conn: AppConnection) -> None:
        self._connections.add(conn)

    def unregister(self, conn: AppConnection) -> None:
        self._connections.discard(conn)

    async def _send(self, conn: AppConnection, message: dict[str, Any]) -> None:
        try:
            async with conn.send_lock:
                await conn.websocket.send_json(message)
        except (WebSocketDisconnect, RuntimeError, OSError):
            self._connections.discard(conn)  # the handler's finally also cleans up

    async def publish(
        self, notifications: dict[UUID, list[dict[str, Any]]], devices: list[tuple[UUID, dict[str, Any]]]
    ) -> None:
        """notifications: {user_id: items}; devices: [(elderly_id, device message)]."""
        sends = []
        for conn in list(self._connections):
            items = notifications.get(conn.user_id)
            if items:
                sends.append(self._send(conn, {"type": "notifications", "items": items}))
            for elderly_id, message in devices:
                if elderly_id in conn.elderly_ids:
                    sends.append(self._send(conn, message))
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
        devices = [(change.elderly_id, _device_message(change)) for change in changes.values()]
        task = loop.create_task(self.publish(notifications, devices))
        self._tasks.add(task)  # keep a reference until it finishes
        task.add_done_callback(self._tasks.discard)


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


# --- queuing on the DB session ----------------------------------------------

def queue_notifications(session: AsyncSession, items_by_user: dict[UUID, list[dict[str, Any]]]) -> None:
    queued: dict[UUID, list[dict[str, Any]]] = session.info.setdefault(_USERS_KEY, {})
    for user_id, items in items_by_user.items():
        queued.setdefault(user_id, []).extend(items)


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


@event.listens_for(Session, "after_commit")
def _publish_after_commit(session: Session) -> None:
    notifications = session.info.pop(_USERS_KEY, None) or {}
    changes = session.info.pop(_DEVICES_KEY, None) or {}
    if notifications or changes:
        app_hub.publish_soon(notifications, changes)


@event.listens_for(Session, "after_transaction_end")
def _drop_after_rollback(session: Session, transaction: SessionTransaction) -> None:
    # after_commit already consumed the queue; anything left was rolled back.
    if transaction.parent is None:
        session.info.pop(_USERS_KEY, None)
        session.info.pop(_DEVICES_KEY, None)
