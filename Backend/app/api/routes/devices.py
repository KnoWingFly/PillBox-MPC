from fastapi import APIRouter, Depends, Query, Response, status
from typing import Annotated
from datetime import datetime, timezone

from app.schemas.device import (
    HeartbeatRequest, HeartbeatResponse,
    ConfigResponse, ScheduleConfig,
    ConfigAckRequest, ConfigAckResponse,
    TelemetryRequest, TelemetryResponse
)
from app.api.deps import verify_device_key

router = APIRouter(prefix="/devices", tags=["Devices"])

@router.post("/{device_id}/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    device_id: str,
    request: HeartbeatRequest,
    is_valid_device: bool = Depends(verify_device_key)
):
    """
    Called by the Smart Device periodically (e.g., every 15-30s).
    Registers device presence, battery, and WiFi strength.
    """
    # TODO: In production, save heartbeat details to database.
    return HeartbeatResponse(
        server_time=datetime.now(timezone.utc),
        latest_config_version=2,
        config_update_available=True  # Stub logic: Always returning true for dev
    )

@router.get("/{device_id}/config", response_model=ConfigResponse)
async def get_config(
    device_id: str,
    response: Response,
    since_version: int = Query(0),
    is_valid_device: bool = Depends(verify_device_key)
):
    """
    Called by the Smart Device to pull latest schedule configuration.
    Uses since_version to return HTTP 304 if no new updates are available.
    """
    latest_server_version = 2
    
    if since_version >= latest_server_version:
        response.status_code = status.HTTP_304_NOT_MODIFIED
        return None
        
    # TODO: Fetch actual configuration from `schedules` and `devices` tables.
    return ConfigResponse(
        config_version=latest_server_version,
        timezone="Asia/Jakarta",
        schedules=[
            ScheduleConfig(
                schedule_id="sch_01j8x9b",
                slot_number=1,
                window_start="07:00",
                window_end="08:00",
                tolerance_minutes=30,
                days_of_week=[1, 2, 3, 4, 5, 6, 7],
                active=True
            ),
            ScheduleConfig(
                schedule_id="sch_01j8x9c",
                slot_number=5,
                window_start="07:30",
                window_end="08:30",
                tolerance_minutes=30,
                days_of_week=[1, 2, 3, 4, 5, 6, 7],
                active=True
            )
        ]
    )

@router.post("/{device_id}/config-ack", response_model=ConfigAckResponse)
async def config_ack(
    device_id: str,
    request: ConfigAckRequest,
    is_valid_device: bool = Depends(verify_device_key)
):
    """
    Called by Smart Device after successfully applying a configuration update locally.
    Backend will use this to reconcile the applied configuration state.
    """
    # TODO: Update device's config_version in the database.
    return ConfigAckResponse(
        acknowledged=True,
        config_version_applied=request.config_version
    )

@router.post("/{device_id}/telemetry", response_model=TelemetryResponse)
async def telemetry(
    device_id: str,
    request: TelemetryRequest,
    is_valid_device: bool = Depends(verify_device_key)
):
    """
    Ingests physical events from the Smart Device (e.g. COMPARTMENT_OPENED).
    Should handle idempotency, returning `duplicates` if batch already processed.
    """
    # TODO: Save events to `telemetry_logs` table. Determine if any event triggers a push notification.
    return TelemetryResponse(
        server_time=datetime.now(timezone.utc),
        accepted=len(request.events),
        duplicates=0,
        rejected=[],
        latest_config_version=2
    )
