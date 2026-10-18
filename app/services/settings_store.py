"""system_settings 读写辅助（音乐 / 影视等配置类模块共用）。

- get_cfg / get_cfgs：单键与批量读取（批量走一条 SELECT，供一次取多键的配置输出）
- get_credential / set_credential：凭据字段的 Fernet 加解密（密文损坏一律回退空串，
  与授权码同策略：绝不把密文当明文提交给上游）
"""

from collections.abc import Sequence

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_text, encrypt_text
from app.models.system_setting import SystemSetting, get_setting_db, set_setting


def get_cfg(db: Session, key: str, default: str = "") -> str:
    return get_setting_db(db, key, default)


def get_cfgs(db: Session, keys: Sequence[str]) -> dict[str, str]:
    """批量读取设置：缺失的键不出现在结果里（调用方用 .get(key, default) 取默认值）。"""
    if not keys:
        return {}
    rows = (
        db.query(SystemSetting.key, SystemSetting.value)
        .filter(SystemSetting.key.in_(list(keys)))
        .all()
    )
    return {k: v for k, v in rows}


def get_credential(db: Session, key: str) -> str:
    """解密存储的凭据；未设置或密文损坏返回空串。"""
    raw = get_cfg(db, key)
    if not raw:
        return ""
    try:
        return decrypt_text(raw) or ""
    except Exception:
        return ""


def set_credential(key: str, plain: str) -> None:
    set_setting(key, encrypt_text(plain) if plain else "")


def require_configured(ok: bool, message: str) -> None:
    if not ok:
        raise HTTPException(400, message)
