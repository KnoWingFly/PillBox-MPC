"""Device WebSocket: /ws/device/{device_code}

Auth: header `X-Device-Key: <secret>` on the upgrade request, or (for clients
that cannot set headers) a first message {"type": "auth", "device_key": "..."}
within WS_AUTH_TIMEOUT_SECONDS. Failure closes with code 4401.

Device -> server:  heartbeat | ack | ping
Server -> device:  welcome | heartbeat_ack | command | pong | error
Formats: docs/DEVICE_CONTRACT.md.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import get_sessionmaker
from app.models import Device
from app.schemas.device_protocol import HeartbeatRequest
from app.services.connection_manager import DeviceCommand, DeviceConnection, connection_manager
from app.services.device_protocol import authenticate_device, process_heartbeat
from app.services.presence import mark_offline, mark_seen

logger = logging.getLogger(__name__)
router = APIRouter()

WS_CLOSE_AUTH_FAILED = 4401
WS_CLOSE_REPLACED = 4000


async def _authenticate(websocket: WebSocket, device_code: str, timeout: float) -> Device | None:
    key = websocket.headers.get("x-device-key")
    if key is None:
        try:
            first = json.loads(await asyncio.wait_for(websocket.receive_text(), timeout=timeout))
        except (TimeoutError, ValueError, KeyError, WebSocketDisconnect):
            return None
        if not isinstance(first, dict) or first.get("type") != "auth":
            return None
        key = first.get("device_key")
        if not isinstance(key, str):
            return None
    async with get_sessionmaker()() as session:
        try:
            return await authenticate_device(session, device_code, key)
        except AppError:
            return None


async def _send(conn: DeviceConnection, message: dict[str, Any]) -> None:
    async with conn.send_lock:
        await conn.websocket.send_json(message)


@router.websocket("/ws/device/{device_code}")
async def device_socket(websocket: WebSocket, device_code: str) -> None:
    settings = get_settings()
    await websocket.accept()
    device = await _authenticate(websocket, device_code, settings.ws_auth_timeout_seconds)
    if device is None:
        await websocket.close(code=WS_CLOSE_AUTH_FAILED, reason="device authentication failed")
        return

    conn = DeviceConnection(device.id, device.device_code, websocket, datetime.now(UTC))
    replaced = connection_manager.register(conn)
    if replaced is not None:
        try:
            await replaced.websocket.close(code=WS_CLOSE_REPLACED, reason="replaced by a newer connection")
        except (RuntimeError, OSError, WebSocketDisconnect):
            pass  # the old socket was already gone
    logger.info("device_ws_connected", extra={"device_id": str(device.id)})

    sessionmaker = get_sessionmaker()
    try:
        async with sessionmaker() as session:
            fresh = await session.get(Device, device.id)
            if fresh is None:
                return
            await mark_seen(session, fresh, datetime.now(UTC))
            await session.commit()
            latest = fresh.config_version
            applied = fresh.config_version_applied or 0
        await _send(conn, {
            "type": "welcome",
            "server_time": datetime.now(UTC).isoformat(),
            "heartbeat_interval_seconds": settings.device_heartbeat_interval_seconds,
            "latest_config_version": latest,
        })
        if latest > applied:
            await connection_manager.notify(device.id, DeviceCommand.SCHEDULE_UPDATED, {"config_version": latest})

        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except ValueError:
                await _send(conn, {"type": "error", "error": "invalid JSON"})
                continue
            if not isinstance(message, dict):
                await _send(conn, {"type": "error", "error": "message must be a JSON object"})
                continue
            kind = message.get("type")
            if kind == "heartbeat":
                try:
                    hb = HeartbeatRequest.model_validate(message)
                except ValidationError as exc:
                    await _send(conn, {"type": "error", "error": "invalid heartbeat", "details": exc.errors(include_url=False)})
                    continue
                async with sessionmaker() as session:
                    current = await session.get(Device, device.id)
                    if current is None:
                        break
                    response = await process_heartbeat(session, current, hb, datetime.now(UTC), settings)
                await _send(conn, {"type": "heartbeat_ack", **response.model_dump(mode="json")})
            elif kind == "ack":
                connection_manager.handle_ack(device.id, message)
            elif kind == "ping":
                await _send(conn, {"type": "pong", "server_time": datetime.now(UTC).isoformat()})
            else:
                await _send(conn, {"type": "error", "error": f"unknown message type {kind!r}"})
    except WebSocketDisconnect as exc:
        logger.info("device_ws_disconnected", extra={"device_id": str(device.id), "code": exc.code})
    except Exception:
        logger.exception("device_ws_error", extra={"device_id": str(device.id)})
        try:
            await websocket.close(code=1011, reason="internal error")
        except (RuntimeError, OSError, WebSocketDisconnect):
            pass
    finally:
        if connection_manager.unregister(conn):
            # Only the current connection may flip the device offline; a socket
            # that was replaced by a reconnect must not.
            async with sessionmaker() as session:
                await mark_offline(session, device.id, datetime.now(UTC), reason="ws_disconnect")
                await session.commit()
