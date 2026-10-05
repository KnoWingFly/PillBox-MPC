from typing import Annotated

from fastapi import APIRouter, Header, status
from pydantic import BaseModel, Field

from app.api.deps import DbSession, SettingsDep
from app.schemas.admin import ProvisionDeviceIn, ProvisionDeviceOut, RotateSecretOut
from app.services import provisioning

router = APIRouter(prefix="/admin", tags=["admin (provisioning)"])

ProvisioningToken = Annotated[str | None, Header(alias="X-Provisioning-Token")]


class RotateSecretIn(BaseModel):
    device_secret: str | None = Field(None, max_length=256)


@router.post("/devices", response_model=ProvisionDeviceOut, status_code=status.HTTP_201_CREATED)
async def provision_device(
    body: ProvisionDeviceIn, db: DbSession, settings: SettingsDep, token: ProvisioningToken = None
) -> ProvisionDeviceOut:
    """Registers a device at the 'factory'. Returns its secret exactly once."""
    provisioning.check_provisioning_token(settings, token)
    return await provisioning.provision(db, body, settings)


@router.post("/devices/{device_code}/rotate-secret", response_model=RotateSecretOut)
async def rotate_device_secret(
    device_code: str, body: RotateSecretIn, db: DbSession, settings: SettingsDep, token: ProvisioningToken = None
) -> RotateSecretOut:
    provisioning.check_provisioning_token(settings, token)
    return await provisioning.rotate_secret(db, device_code, body.device_secret, settings)
