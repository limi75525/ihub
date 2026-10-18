from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.session import SessionLocal


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(256))
    # 逻辑删除：删除=软删置位，默认 30 天后由 purge 物理清除（吊销/停用请用 is_active）
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def get_setting(key: str, default: str = "") -> str:
    db = SessionLocal()
    try:
        row = db.get(SystemSetting, key)
        return row.value if row else default
    finally:
        db.close()


def get_setting_db(db, key: str, default: str = "") -> str:
    row = db.get(SystemSetting, key)
    return row.value if row else default


def set_setting(key: str, value: str) -> None:
    db = SessionLocal()
    try:
        row = db.get(SystemSetting, key)
        if row:
            row.value = value
        else:
            db.add(SystemSetting(key=key, value=value))
        db.commit()
    finally:
        db.close()


def get_int_setting(key: str, default: int, lo: int, hi: int) -> int:
    """读取整型设置并夹在 [lo, hi] 内；值损坏/越界时回退 default。"""
    raw = get_setting(key, str(default))
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return default
    if v < lo or v > hi:
        return default
    return v
