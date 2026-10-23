from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ProvisionDeviceIn(BaseModel):
    # Omit to generate. A custom code lets you provision the emulator's "sim-01".
    device_code: str | None = Field(None, min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    # Omit to generate (recommended). Length is checked against DEVICE_SECRET_MIN_LENGTH.
    device_secret: str | None = Field(None, max_length=256)


class ProvisionDeviceOut(BaseModel):
    id: UUID
    device_code: str
    # Returned exactly once; only its hash is stored.
    device_secret: str
    qr_payload: str
    created_at: datetime


class RotateSecretOut(BaseModel):
    device_code: str
    device_secret: str
