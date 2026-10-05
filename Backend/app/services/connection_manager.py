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

logger = logging.getLogger(__name__)


class DeviceCommand(StrEnum):
    TRIGGER_ALARM = "trigger_alarm"
    SCHEDULE_UPDATED = "schedule_updated"
    TIME_SYNC = "time_sync"
    REFILL_MODE = "refill_mode"


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
    def __init__(self, history_size: int = 200) -> None:
        self._connections: dict[UUID, DeviceConnection] = {}
        self._pending: dict[str, _Pending] = {}
        self.history: deque[CommandRecord] = deque(maxlen=history_size)

    # --- connections --------------------------------------------------
    def is_connected(self, device_id: UUID) -> bool:
        return device_id in self._connections

    def get(self, device_id: UUID) -> DeviceConnection | None:
        return self._connections.get(device_id)

    def register(self, conn: DeviceConnection) -> DeviceConnection | None:
        """Returns the connection this one replaced (caller should close it)."""
        previous = self._connections.get(conn.device_id)
        self._connections[conn.device_id] = conn
        return previous

    def unregister(self, conn: DeviceConnection) -> bool:
        """Returns True if `conn` was the current connection for its device."""
        if self._connections.get(conn.device_id) is not conn:
            return False
        del self._connections[conn.device_id]
        for command_id, pending in list(self._pending.items()):
            if pending.device_id == conn.device_id and not pending.future.done():
                pending.future.set_exception(DeviceDisconnectedError(command_id))
        return True

    # --- commands -----------------------------------------------------
    async def _send(self, conn: DeviceConnection, message: dict[str, Any]) -> None:
        async with conn.send_lock:
            await conn.websocket.send_json(message)

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
        try:
            try:
                await self._send(conn, message)
            except (WebSocketDisconnect, RuntimeError, OSError) as exc:
                record.status = "DISCONNECTED"
                raise DeviceDisconnectedError(command_id) from exc
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
            await self._send(conn, message)
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
                ok=bool(message.get("ok", False)),
                result=result if isinstance(result, dict) else None,
                error=str(error) if error is not None else None,
                acked_at=datetime.now(UTC),
            )
        )


connection_manager = ConnectionManager()
