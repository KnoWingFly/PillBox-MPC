"""Device WebSocket: /ws/device/{device_code}  (app WebSocket /ws/app: see app_socket)

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
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.api.deps import user_from_token
from app.core.config import get_settings
from app.core.errors import AppError, is_db_unavailable
from app.db.session import get_sessionmaker
from app.models import Device
from app.schemas.device_protocol import HeartbeatRequest
from app.services.app_hub import AppConnection, app_hub, followed_elderly
from app.services.connection_manager import (
    WS_CLOSE_AUTH_FAILED,
    WS_CLOSE_REPLACED,
    WS_CLOSE_INTERNAL_ERROR,
    DeviceCommand,
    DeviceConnection,
    connection_manager,
)
from app.services.device_protocol import authenticate_device, process_heartbeat
from app.services.presence import mark_offline, mark_seen

logger = logging.getLogger(__name__)
router = APIRouter()

# Server-side failure (database unreachable) while authenticating closes with
# WS_CLOSE_INTERNAL_ERROR (1011) so the client retries with backoff. 4401 would tell a device its
# key is wrong and make it stop retrying.


class _AuthUnavailable(Exception):
    pass


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
    try:
        async with get_sessionmaker()() as session:
            return await authenticate_device(session, device_code, key)
    except AppError:
        return None
    except Exception as exc:
        logger.warning("device_ws_auth_unavailable", extra={"error": type(exc).__name__}, exc_info=not is_db_unavailable(exc))
        raise _AuthUnavailable from exc


async def _send(conn: DeviceConnection, message: dict[str, Any]) -> None:
    await connection_manager.send(conn, message)


@router.websocket("/ws/device/{device_code}")
async def device_socket(websocket: WebSocket, device_code: str) -> None:
    settings = get_settings()
    await websocket.accept()
    try:
        device = await _authenticate(websocket, device_code, settings.ws_auth_timeout_seconds)
    except _AuthUnavailable:
        await _close_quietly(websocket, WS_CLOSE_INTERNAL_ERROR, "service unavailable, retry later")
        return
    if device is None:
        await websocket.close(code=WS_CLOSE_AUTH_FAILED, reason="device authentication failed")
        return

    conn = DeviceConnection(device.id, device.device_code, websocket, datetime.now(UTC))
    replaced = connection_manager.register(conn)
    if replaced is not None:
        await connection_manager.close_socket(replaced, WS_CLOSE_REPLACED, "replaced by a newer connection")
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
            device_tz = fresh.timezone
        await _send(conn, {
            "type": "welcome",
            "server_time": datetime.now(UTC).isoformat(),
            # Lets the device set its clock to local time (no NTP on the emulator).
            "timezone": device_tz,
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
                    # Paths and messages only: the submitted values are not echoed back.
                    details = exc.errors(include_url=False, include_input=False, include_context=False)
                    await _send(conn, {"type": "error", "error": "invalid heartbeat", "details": details})
                    continue
                try:
                    async with sessionmaker() as session:
                        current = await session.get(Device, device.id)
                        if current is None:
                            break
                        response = await process_heartbeat(session, current, hb, datetime.now(UTC), settings)
                except Exception as exc:
                    # A short database outage must not drop every device socket (and fail their
                    # pending commands): answer this heartbeat with an error and keep the socket.
                    if is_db_unavailable(exc):
                        logger.warning("device_ws_heartbeat_unavailable", extra={"device_id": str(device.id)})
                    else:
                        logger.exception("device_ws_heartbeat_failed", extra={"device_id": str(device.id)})
                    await _send(conn, {"type": "error", "error": "heartbeat not stored, retry later"})
                    continue
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
        await _close_quietly(websocket, WS_CLOSE_INTERNAL_ERROR, "internal error")
    finally:
        if connection_manager.unregister(conn):
            # Only the current connection may flip the device offline; a socket
            # that was replaced by a reconnect must not.
            try:
                async with sessionmaker() as session:
                    await mark_offline(session, device.id, datetime.now(UTC), reason="ws_disconnect")
                    await session.commit()
            except Exception:
                # The presence sweep flips it after the heartbeat timeout instead.
                logger.warning("device_ws_mark_offline_failed", extra={"device_id": str(device.id)}, exc_info=True)


async def _close_quietly(websocket: WebSocket, code: int, reason: str) -> None:
    try:
        await websocket.close(code=code, reason=reason)
    except (RuntimeError, OSError, WebSocketDisconnect):
        pass  # already gone


async def _app_user(websocket: WebSocket, timeout: float) -> tuple[UUID, set[UUID], float | None] | None:
    """First message must be {"type": "auth", "token": "<access token>"}. Returns the user, the
    elderly they follow, and the token's expiry (epoch seconds)."""
    try:
        first = json.loads(await asyncio.wait_for(websocket.receive_text(), timeout=timeout))
    except (TimeoutError, ValueError, WebSocketDisconnect):
        return None
    token = first.get("token") if isinstance(first, dict) and first.get("type") == "auth" else None
    if not isinstance(token, str):
        return None
    try:
        async with get_sessionmaker()() as session:
            try:
                user = await user_from_token(token, get_settings(), session)
            except AppError:
                return None
            # Signature and expiry were verified above; only the expiry is read here.
            expires_at = jwt.decode(token, options={"verify_signature": False}).get("exp")
            followed = await followed_elderly(session, {user.id})
            return user.id, followed[user.id], float(expires_at) if expires_at is not None else None
    except Exception as exc:
        logger.warning("app_ws_auth_unavailable", extra={"error": type(exc).__name__}, exc_info=not is_db_unavailable(exc))
        raise _AuthUnavailable from exc


@router.websocket("/ws/app")
async def app_socket(websocket: WebSocket) -> None:
    """Caregiver app: receives "refetch" hints (services/app_hub.py).

    App -> server:  auth (first, within WS_AUTH_TIMEOUT_SECONDS) | ping | resubscribe
    Server -> app:  ready | notifications | device | pong
    `resubscribe` reloads the elderly the user follows (send it after pairing).
    The token is checked at connect and the socket is closed (4401) when it expires; the app
    reconnects with a fresh one. Role changes refresh the followed elderly on their own
    (app_hub.queue_roles_changed). Pushes carry the changed data (see
    app/services/app_hub.py); a message without data tells the app to refetch.
    """
    settings = get_settings()
    await websocket.accept()
    try:
        auth = await _app_user(websocket, settings.ws_auth_timeout_seconds)
    except _AuthUnavailable:
        await _close_quietly(websocket, WS_CLOSE_INTERNAL_ERROR, "service unavailable, retry later")
        return
    if auth is None:
        await websocket.close(code=WS_CLOSE_AUTH_FAILED, reason="authentication failed")
        return
    user_id, elderly_ids, expires_at = auth
    conn = AppConnection(user_id, elderly_ids, websocket)
    app_hub.register(conn)
    logger.info("app_ws_connected", extra={"user_id": str(user_id), "elderly_count": len(elderly_ids)})
    try:
        await websocket.send_json({"type": "ready"})
        while True:
            remaining = None if expires_at is None else expires_at - time.time()
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=remaining)
            except TimeoutError:
                await websocket.close(code=WS_CLOSE_AUTH_FAILED, reason="access token expired")
                break
            try:
                kind = json.loads(raw).get("type")
            except (ValueError, AttributeError):
                continue
            if kind == "ping":
                async with conn.send_lock:
                    await websocket.send_json({"type": "pong"})
            elif kind == "resubscribe":
                async with get_sessionmaker()() as session:
                    app_hub.set_elderly(conn, (await followed_elderly(session, {user_id}))[user_id])
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("app_ws_error", extra={"user_id": str(user_id)})
    finally:
        app_hub.unregister(conn)
        logger.info("app_ws_disconnected", extra={"user_id": str(user_id)})
