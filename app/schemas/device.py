from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.core.timeutil import as_utc


def _ensure_utc(cls, v):
    return as_utc(v)


class DeviceOut(BaseModel):
    id: str
    name: str
    kind: str
    platform: str
    app_version: str
    source_id: int | None
    is_active: bool
    last_seen_at: datetime | None
    created_at: datetime

    _tz = field_validator("last_seen_at", "created_at", mode="before")(_ensure_utc)
    model_config = {"from_attributes": True}
