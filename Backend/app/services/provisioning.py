"""Factory provisioning: registers a physical device (device_code + secret)
before any caregiver pairs it. Guarded by PROVISIONING_TOKEN; disabled when
that variable is unset. The plain secret is returned once and never stored."""

import hmac
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, conflict, not_found, unprocessable
from app.core.security import generate_device_code, generate_device_secret, hash_device_secret
from app.models import Device
from app.schemas.admin import ProvisionDeviceIn, ProvisionDeviceOut, RotateSecretOut

logger = logging.getLogger(__name__)


def qr_payload(device_code: str) -> str:
    return f"pillcare://device/{device_code}"


def check_provisioning_token(settings: Settings, provided: str | None) -> None:
    if settings.provisioning_token is None:
        raise not_found(message="Provisioning is disabled (PROVISIONING_TOKEN is not set)")
    expected = settings.provisioning_token.get_secret_value()
    if provided is None or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise AppError(401, "PROVISIONING_TOKEN_INVALID", "Invalid provisioning token")


def _secret(requested: str | None, settings: Settings) -> str:
    if requested is None:
        return generate_device_secret()
    if len(requested) < settings.device_secret_min_length:
        raise unprocessable(
            "DEVICE_SECRET_TOO_SHORT",
            f"device_secret must be at least {settings.device_secret_min_length} characters",
        )
    return requested


async def provision(session: AsyncSession, body: ProvisionDeviceIn, settings: Settings) -> ProvisionDeviceOut:
    code = body.device_code or generate_device_code()
    exists = (await session.execute(select(Device.id).where(Device.device_code == code))).scalar_one_or_none()
    if exists is not None:
        raise conflict("DEVICE_CODE_TAKEN", f"Device code {code} is already provisioned")
    secret = _secret(body.device_secret, settings)
    device = Device(device_code=code, device_secret_hash=hash_device_secret(secret))
    session.add(device)
    await session.commit()
    await session.refresh(device)
    logger.info("device_provisioned", extra={"device_id": str(device.id), "device_code": code})
    return ProvisionDeviceOut(
        id=device.id, device_code=code, device_secret=secret, qr_payload=qr_payload(code), created_at=device.created_at
    )


async def rotate_secret(
    session: AsyncSession, device_code: str, requested: str | None, settings: Settings
) -> RotateSecretOut:
    device = (
        await session.execute(select(Device).where(Device.device_code == device_code).with_for_update())
    ).scalar_one_or_none()
    if device is None:
        raise not_found(message="Device not found")
    secret = _secret(requested, settings)
    device.device_secret_hash = hash_device_secret(secret)
    await session.commit()
    logger.info("device_secret_rotated", extra={"device_id": str(device.id)})
    return RotateSecretOut(device_code=device_code, device_secret=secret)
