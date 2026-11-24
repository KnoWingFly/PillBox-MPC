"""Phone push notifications through the Expo Push API (B3).

notifications.notify_many() queues one PushItem per new notification row on the DB session. After
the transaction commits, the items are sent from a background task, so a rollback never produces a
push for a notification that does not exist, and the request that created them never waits for
Expo. Without an open app the caregiver still learns about a missed dose.

Expo Push API (docs.expo.dev/push-notifications/sending-notifications, checked 24 Nov 2026):
POST EXPO_PUSH_SEND_URL with up to 100 messages; each ticket is "ok" (with a receipt id) or "error"
(details.error, e.g. DeviceNotRegistered). Receipts are fetched EXPO_PUSH_RECEIPT_DELAY_SECONDS
later from EXPO_PUSH_RECEIPTS_URL (up to 1000 ids per request).

push_tokens belongs to the Mobile auth server (Prisma): this module only reads it. Tokens Expo
reports as unregistered are logged by id; the auth server removes stale tokens when their session
ends (Mobile/BACKEND_HANDOFF.md item 9).
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from app.core.config import Settings, get_settings
from app.models import PushToken

logger = logging.getLogger(__name__)

_PUSH_KEY = "pending_phone_pushes"
# Expo message priority: "high" wakes the phone at once (missed doses, an offline pillbox).
HIGH_PRIORITY_SEVERITIES = frozenset({"CRITICAL", "WARNING"})
DEVICE_NOT_REGISTERED = "DeviceNotRegistered"


@dataclass(frozen=True)
class PushItem:
    """One notification row to deliver to every phone of its caregiver."""

    user_id: UUID
    title: str
    body: str
    severity: str
    data: dict[str, Any] = field(default_factory=dict)


def queue_push(session: AsyncSession, items: list[PushItem]) -> None:
    """Sent after the surrounding transaction commits; dropped if it rolls back."""
    if items:
        session.info.setdefault(_PUSH_KEY, []).extend(items)


@event.listens_for(Session, "after_commit")
def _send_after_commit(session: Session) -> None:
    items: list[PushItem] = session.info.pop(_PUSH_KEY, None) or []
    if items:
        push_sender.send_soon(items)


@event.listens_for(Session, "after_transaction_end")
def _drop_after_rollback(session: Session, transaction: SessionTransaction) -> None:
    if transaction.parent is None:
        session.info.pop(_PUSH_KEY, None)


def build_messages(items: list[PushItem], tokens_by_user: dict[UUID, list[str]], settings: Settings) -> list[dict[str, Any]]:
    """One Expo message per (item, phone of its caregiver)."""
    messages: list[dict[str, Any]] = []
    for item in items:
        for token in tokens_by_user.get(item.user_id, ()):
            messages.append(
                {
                    "to": token,
                    "title": item.title,
                    "body": item.body,
                    "data": item.data,
                    "sound": "default",
                    "priority": "high" if item.severity in HIGH_PRIORITY_SEVERITIES else "default",
                    "ttl": settings.expo_push_ttl_seconds,
                    # Unset: Expo uses the app's default Android channel.
                    **({"channelId": settings.expo_push_android_channel_id} if settings.expo_push_android_channel_id else {}),
                }
            )
    return messages


def _chunks(values: list[Any], size: int) -> list[list[Any]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


class PushSender:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()
        # Tests swap in httpx.MockTransport; None = real network.
        self.transport: httpx.AsyncBaseTransport | None = None

    async def settle(self) -> None:
        """Waits for sends in flight (tests)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def send_soon(self, items: list[PushItem]) -> None:
        """Called from the commit hook (sync code on the event-loop thread)."""
        settings = get_settings()
        if not settings.push_enabled:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # not inside the server's loop (e.g. a script)
        self._track(loop.create_task(self.send(items, settings)))

    def _track(self, task: "asyncio.Task[None]") -> None:
        self._tasks.add(task)
        task.add_done_callback(self._done)

    def _done(self, task: "asyncio.Task[None]") -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("push_task_failed", exc_info=task.exception())

    async def send(self, items: list[PushItem], settings: Settings) -> None:
        # Imported here: app.db.session is not needed by the rest of this module.
        from app.db.session import get_sessionmaker

        user_ids = {item.user_id for item in items}
        async with get_sessionmaker()() as session:
            rows = await session.execute(
                select(PushToken.user_id, PushToken.token, PushToken.id).where(PushToken.user_id.in_(user_ids))
            )
            token_rows = rows.all()
        tokens_by_user: dict[UUID, list[str]] = {}
        token_ids: dict[str, UUID] = {}
        for user_id, token, token_id in token_rows:
            tokens_by_user.setdefault(user_id, []).append(token)
            token_ids[token] = token_id
        messages = build_messages(items, tokens_by_user, settings)
        if not messages:
            return  # nobody to reach has a phone registered (web-only, or push disabled on the phone)

        receipt_ids: list[str] = []
        sent = failed = 0
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if settings.expo_access_token:
            headers["Authorization"] = f"Bearer {settings.expo_access_token.get_secret_value()}"
        async with httpx.AsyncClient(timeout=settings.expo_push_timeout_seconds, headers=headers, transport=self.transport) as client:
            for chunk in _chunks(messages, settings.expo_push_batch_size):
                try:
                    res = await client.post(settings.expo_push_send_url, json=chunk)
                    res.raise_for_status()
                    tickets = res.json().get("data", [])
                except (httpx.HTTPError, ValueError) as exc:
                    failed += len(chunk)
                    logger.warning("push_send_failed", extra={"messages": len(chunk), "error": type(exc).__name__})
                    continue
                for message, ticket in zip(chunk, tickets, strict=False):
                    if ticket.get("status") == "ok":
                        sent += 1
                        if ticket.get("id"):
                            receipt_ids.append(ticket["id"])
                        continue
                    failed += 1
                    error = (ticket.get("details") or {}).get("error")
                    logger.warning(
                        "push_ticket_error",
                        extra={
                            "error": error,
                            # The token id, never the token itself.
                            "push_token_id": str(token_ids.get(message["to"], "")),
                            "unregistered": error == DEVICE_NOT_REGISTERED,
                        },
                    )
        logger.info("push_sent", extra={"notifications": len(items), "messages": len(messages), "sent": sent, "failed": failed})
        if receipt_ids and settings.expo_push_receipt_delay_seconds > 0:
            self._track(asyncio.get_running_loop().create_task(self._check_receipts(receipt_ids, settings)))

    async def _check_receipts(self, receipt_ids: list[str], settings: Settings) -> None:
        """A ticket "ok" only means Expo accepted the message; the receipt says whether Apple or
        Google delivered it. Errors are logged (MessageTooBig, InvalidCredentials, ...)."""
        await asyncio.sleep(settings.expo_push_receipt_delay_seconds)
        errors: dict[str, int] = {}
        async with httpx.AsyncClient(timeout=settings.expo_push_timeout_seconds, transport=self.transport) as client:
            for chunk in _chunks(receipt_ids, settings.expo_push_receipts_batch_size):
                try:
                    res = await client.post(settings.expo_push_receipts_url, json={"ids": chunk})
                    res.raise_for_status()
                    receipts = res.json().get("data", {})
                except (httpx.HTTPError, ValueError) as exc:
                    logger.warning("push_receipts_failed", extra={"ids": len(chunk), "error": type(exc).__name__})
                    continue
                for receipt in receipts.values():
                    if receipt.get("status") == "error":
                        error = (receipt.get("details") or {}).get("error") or "unknown"
                        errors[error] = errors.get(error, 0) + 1
        if errors:
            logger.warning("push_receipt_errors", extra={"errors": errors})


push_sender = PushSender()
