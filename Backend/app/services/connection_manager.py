"""Active device WebSockets and backend -> device commands with acks.

Command flow:
    server -> device  {"type": "command", "command_id", "command", "payload", "issued_at"}
    device -> server  {"type": "ack", "command_id", "ok": bool, "result"?: {...}, "error"?: str}

send_command() waits for the ack and raises a specific error when the device
is not connected, disconnects mid-command, or does not ack in time, so callers
never report success for a command the device did not confirm.

State lives in this process only: run uvicorn with ONE worker, or a command
issued on worker A cannot reach a socket held by worker B.
"""

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from fastapi import WebSocket, WebSocketDisconnect

from app.core import timing
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# WebSocket close codes (docs/DEVICE_CONTRACT.md §3).
WS_CLOSE_AUTH_FAILED = 4401
WS_CLOSE_REPLACED = 4000
# Server-side failure or a send the device did not read in time: reconnect with backoff.
WS_CLOSE_INTERNAL_ERROR = 1011


class DeviceCommand(StrEnum):
    TRIGGER_ALARM = "trigger_alarm"
    STOP_ALARM = "stop_alarm"
    SCHEDULE_UPDATED = "schedule_updated"
    TIME_SYNC = "time_sync"
    REFILL_MODE = "refill_mode"
    RELEASE_SLOT = "release_slot"


class CommandError(Exception):
    code = "DEVICE_COMMAND_FAILED"


class DeviceNotConnectedError(CommandError):
    code = "DEVICE_NOT_CONNECTED"


class DeviceDisconnectedError(CommandError):
    code = "DEVICE_DISCONNECTED"


class CommandTimeoutError(CommandError):
    code = "DEVICE_ACK_TIMEOUT"


@dataclass
class CommandAck:
    command_id: str
    ok: bool
    result: dict[str, Any] | None
    error: str | None
    acked_at: datetime


@dataclass
class _Pending:
    device_id: UUID
    command: str
    future: asyncio.Future[CommandAck]


@dataclass
class DeviceConnection:
    device_id: UUID
    device_code: str
    websocket: WebSocket
    connected_at: datetime
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass
class CommandRecord:
    command_id: str
    device_id: UUID
    command: str
    issued_at: datetime
    status: str  # SENT | ACKED | REJECTED | TIMEOUT | DISCONNECTED | FIRE_AND_FORGET
    detail: str | None = None


class ConnectionManager:
    def __init__(self, history_size: int | None = None) -> None:
        self._connections: dict[UUID, DeviceConnection] = {}
        self._pending: dict[str, _Pending] = {}
        self._closing: set[asyncio.Task[None]] = set()  # bounded closes of dropped sockets
        self.history: deque[CommandRecord] = deque(
            maxlen=history_size if history_size is not None else get_settings().device_command_history_size
        )

    # --- connections --------------------------------------------------
    def is_connected(self, device_id: UUID) -> bool:
        return device_id in self._connections

    def get(self, device_id: UUID) -> DeviceConnection | None:
        return self._connections.get(device_id)

    def register(self, conn: DeviceConnection) -> DeviceConnection | None:
        """Returns the connection this one replaced (caller should close it). Commands sent on
        the replaced socket are failed now (502 DEVICE_DISCONNECTED) instead of waiting for the
        ack timeout: the old socket will never deliver their acks."""
        previous = self._connections.get(conn.device_id)
        self._connections[conn.device_id] = conn
        if previous is not None:
            self._fail_pending(conn.device_id)
        return previous

    def unregister(self, conn: DeviceConnection) -> bool:
        """Returns True if `conn` was the current connection for its device."""
        if self._connections.get(conn.device_id) is not conn:
            return False
        del self._connections[conn.device_id]
        self._fail_pending(conn.device_id)
        return True

    def _fail_pending(self, device_id: UUID) -> None:
        for command_id, pending in list(self._pending.items()):
            if pending.device_id == device_id and not pending.future.done():
                pending.future.set_exception(DeviceDisconnectedError(command_id))

    async def close(self, device_id: UUID, code: int, reason: str) -> bool:
        """Closes the device's socket (e.g. its secret was rotated). The socket handler then
        unregisters it, fails its pending commands and marks the device offline.
        Returns False when the device had no socket."""
        conn = self._connections.get(device_id)
        if conn is None:
            return False
        try:
            await asyncio.wait_for(self._locked_close(conn, code, reason), get_settings().device_ws_send_timeout_seconds)
        except TimeoutError:
            # The socket does not drain: forget it now so no command waits on it. Its handler
            # cleans up whenever the transport finally fails.
            logger.warning("device_ws_close_timeout", extra={"device_id": str(device_id)})
            self.unregister(conn)
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass  # already gone
        logger.info("device_ws_closed_by_server", extra={"device_id": str(device_id), "code": code})
        return True

    # --- commands -----------------------------------------------------
    async def close_socket(self, conn: DeviceConnection, code: int, reason: str) -> None:
        """Closes one (already unregistered) socket, bounded by the send timeout."""
        try:
            await asyncio.wait_for(self._locked_close(conn, code, reason), get_settings().device_ws_send_timeout_seconds)
        except (TimeoutError, WebSocketDisconnect, RuntimeError, OSError):
            pass  # gone or stalled; its handler cleans up when the transport fails

    async def _locked_close(self, conn: DeviceConnection, code: int, reason: str) -> None:
        async with conn.send_lock:
            await conn.websocket.close(code=code, reason=reason)

    async def _locked_send(self, conn: DeviceConnection, message: dict[str, Any]) -> None:
        async with conn.send_lock:
            await conn.websocket.send_json(message)

    async def send(self, conn: DeviceConnection, message: dict[str, Any]) -> None:
        """Bounded by DEVICE_WS_SEND_TIMEOUT_SECONDS (waiting for the lock included), so one
        pillbox whose TCP connection stalled cannot hang the caregiver request that notifies it.
        A timeout drops the socket and raises TimeoutError (an OSError, like a broken pipe)."""
        try:
            await asyncio.wait_for(self._locked_send(conn, message), get_settings().device_ws_send_timeout_seconds)
        except TimeoutError:
            logger.warning("device_ws_send_timeout", extra={"device_id": str(conn.device_id)})
            self.unregister(conn)
            # Close it in the background (also bounded) so the device notices and reconnects.
            task = asyncio.get_running_loop().create_task(
                self.close_socket(conn, WS_CLOSE_INTERNAL_ERROR, "send timed out")
            )
            self._closing.add(task)
            task.add_done_callback(self._closing.discard)
            raise

    def _envelope(self, command: DeviceCommand, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "command",
            "command_id": str(uuid4()),
            "command": command.value,
            "payload": payload,
            "issued_at": datetime.now(UTC).isoformat(),
        }

    async def send_command(
        self, device_id: UUID, command: DeviceCommand, payload: dict[str, Any], timeout: float
    ) -> CommandAck:
        conn = self._connections.get(device_id)
        if conn is None:
            raise DeviceNotConnectedError(str(device_id))
        message = self._envelope(command, payload)
        command_id = message["command_id"]
        record = CommandRecord(command_id, device_id, command.value, datetime.now(UTC), "SENT")
        self.history.append(record)
        future: asyncio.Future[CommandAck] = asyncio.get_running_loop().create_future()
        self._pending[command_id] = _Pending(device_id, command.value, future)
        started = timing.now_ms()
        try:
            try:
                await self.send(conn, message)
            except (WebSocketDisconnect, RuntimeError, OSError) as exc:
                record.status = "DISCONNECTED"
                raise DeviceDisconnectedError(command_id) from exc
            timing.log_timing("app_to_iot", "ws_command_sent", command=command.value, send_ms=timing.since_ms(started))
            try:
                ack = await asyncio.wait_for(future, timeout=timeout)
            except TimeoutError as exc:
                record.status = "TIMEOUT"
                raise CommandTimeoutError(command_id) from exc
            except DeviceDisconnectedError:
                record.status = "DISCONNECTED"
                raise
            record.status = "ACKED" if ack.ok else "REJECTED"
            record.detail = ack.error
            return ack
        finally:
            self._pending.pop(command_id, None)
            timing.log_timing(
                "app_to_iot", "device_ack_received", command=command.value,
                status=record.status, ack_wait_ms=timing.since_ms(started),
            )
            logger.info(
                "device_command",
                extra={"device_id": str(device_id), "command": command.value,
                       "command_id": command_id, "status": record.status},
            )

    async def notify(self, device_id: UUID, command: DeviceCommand, payload: dict[str, Any]) -> bool:
        """Best-effort command (no wait for ack). Returns False if not delivered."""
        conn = self._connections.get(device_id)
        if conn is None:
            return False
        message = self._envelope(command, payload)
        try:
            await self.send(conn, message)
        except (WebSocketDisconnect, RuntimeError, OSError):
            return False
        self.history.append(
            CommandRecord(message["command_id"], device_id, command.value, datetime.now(UTC), "FIRE_AND_FORGET")
        )
        return True

    def handle_ack(self, device_id: UUID, message: dict[str, Any]) -> None:
        command_id = str(message.get("command_id", ""))
        pending = self._pending.get(command_id)
        if pending is None or pending.device_id != device_id:
            # Ack for a fire-and-forget command, a timed-out one, or another device.
            logger.debug("unmatched_ack", extra={"device_id": str(device_id), "command_id": command_id})
            return
        if pending.future.done():
            return
        result = message.get("result")
        error = message.get("error")
        pending.future.set_result(
            CommandAck(
                command_id=command_id,
                # Only a JSON true is success: a string "false" is truthy.
                ok=message.get("ok") is True,
                result=result if isinstance(result, dict) else None,
                error=str(error) if error is not None else None,
                acked_at=datetime.now(UTC),
            )
        )


connection_manager = ConnectionManager()
