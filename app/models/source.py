from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import utcnow


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    # sms / email / api
    type: Mapped[str] = mapped_column(String(16))
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    # ---- email 类型专用字段 ----
    imap_host: Mapped[str | None] = mapped_column(String(128), nullable=True)
    imap_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imap_ssl: Mapped[bool] = mapped_column(Boolean, default=True)
    # SSL 证书校验（默认开）：自签证书服务器可按来源关闭；关闭时仍加密但不验证对端身份。
    # server_default 必须有：冒烟测试等裸 SQL INSERT 不带此列时依赖库级默认值
    imap_verify_tls: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("1")
    )
    email_account: Mapped[str | None] = mapped_column(String(128), nullable=True)
    email_password: Mapped[str | None] = mapped_column(String(256), nullable=True)
    poll_interval: Mapped[int] = mapped_column(Integer, default=120)
    folder: Mapped[str] = mapped_column(String(128), default="INBOX")
    # 增量拉取游标
    last_uid: Mapped[int] = mapped_column(Integer, default=0)
    uidvalidity: Mapped[int] = mapped_column(Integer, default=0)
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 排序：设置页拖拽调整，消息页右栏与接入状态卡按此顺序展示
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 来源 Logo：本地上传文件相对路径 或 在线图片 URL（二选一）
    logo_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # 逻辑删除：删除=软删置位，默认 30 天后由 purge 物理清除（吊销/停用请用 is_active）
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages = relationship("Message", back_populates="source", cascade="all, delete-orphan")
