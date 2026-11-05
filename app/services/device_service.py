"""接入服务 API 来源的设备领域逻辑（设备码生成 / 密钥加密 / 出参序列化）。

从 api/v1/devices.py 下沉：sources.py 注册 API 来源时要同步建一台设备，
路由层互相 import 私有函数违反依赖方向。
"""

import secrets

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.crypto import encrypt_text
from app.models.device import Device
from app.schemas.device import DeviceOut

CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def gen_device_code(db: Session) -> str:
    for _ in range(50):
        code = "".join(secrets.choice(CODE_CHARS) for _ in range(8))
        if db.get(Device, code) is None:
            return code
    raise HTTPException(500, "设备码生成失败，请重试")


def encrypt_secret(secret: str) -> str:
    return encrypt_text(secret)


def device_out(d: Device) -> DeviceOut:
    out = DeviceOut.model_validate(d)
    out.created_at = d.created_at
    out.last_seen_at = d.last_seen_at
    return out
