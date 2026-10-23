"""Routes called by the smart device itself (auth: X-Device-Key).
Path {device_id} is the device_code (e.g. "sim-01") or the device UUID."""

from datetime import UTC, datetime

from fastapi import APIRouter, Query, Response, status

from app.api.deps import AuthenticatedDevice, DbSession, SettingsDep
from app.schemas.device_protocol import (
    ConfigAckRequest,
    ConfigAckResponse,
    ConfigResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    TelemetryRequest,
    TelemetryResponse,
)
from app.services import device_protocol, telemetry
from app.services.presence import mark_seen

router = APIRouter(prefix="/devices", tags=["device protocol"])


@router.post("/{device_id}/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    body: HeartbeatRequest, device: AuthenticatedDevice, db: DbSession, settings: SettingsDep
) -> HeartbeatResponse:
    return await device_protocol.process_heartbeat(db, device, body, datetime.now(UTC), settings)


@router.get(
    "/{device_id}/config",
    response_model=ConfigResponse,
    responses={304: {"description": "since_version is already the latest"}},
)
async def get_config(
    device: AuthenticatedDevice,
    db: DbSession,
    since_version: int | None = Query(None, ge=0),
) -> ConfigResponse | Response:
    await mark_seen(db, device, datetime.now(UTC))
    await db.commit()
    if since_version is not None and since_version >= device.config_version:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED)
    return await device_protocol.build_config(db, device)


@router.post("/{device_id}/config-ack", response_model=ConfigAckResponse)
async def config_ack(body: ConfigAckRequest, device: AuthenticatedDevice, db: DbSession) -> ConfigAckResponse:
    now = datetime.now(UTC)
    await mark_seen(db, device, now)
    return await device_protocol.ack_config(db, device, body.config_version, body.applied_at, now)


@router.post("/{device_id}/telemetry", response_model=TelemetryResponse)
async def post_telemetry(
    body: TelemetryRequest, device: AuthenticatedDevice, db: DbSession, settings: SettingsDep
) -> TelemetryResponse:
    """Idempotent per event_id; batches may be large post-offline flushes."""
    return await telemetry.ingest_batch(db, device, body, datetime.now(UTC), settings)
