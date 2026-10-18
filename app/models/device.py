from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import utcnow


class Device(Base):
    """已注册的转发设备（接入源的唯一身份）。

    id 为 8 位唯一码（大写英文+数字，去除易混字符）；
    kind 决定推送渠道：sms（手机/短信硬件）→ channel=sms；notify（服务通知）→ channel=api。
    device_secret_cipher 为主密钥 Fernet 加密后的设备密钥。
    """

    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(8), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    kind: Mapped[str] = mapped_column(String(8), default="sms")  # sms / notify
    platform: Mapped[str] = mapped_column(String(16), default="android")
    app_version: Mapped[str] = mapped_column(String(32), default="")
    # 设备推送的消息挂到该短信来源（注册时自动创建/复用）
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    device_secret_cipher: Mapped[str] = mapped_column(String(256))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # 逻辑删除：删除=软删置位，默认 30 天后由 purge 物理清除（吊销/停用请用 is_active）
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
