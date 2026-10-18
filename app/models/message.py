from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import utcnow


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    # sms / email / api
    channel: Mapped[str] = mapped_column(String(16), index=True)

    sender: Mapped[str] = mapped_column(String(256), default="")
    recipient: Mapped[str] = mapped_column(String(256), default="")
    title: Mapped[str] = mapped_column(String(512), default="")
    content_text: Mapped[str] = mapped_column(Text, default="")
    content_html: Mapped[str | None] = mapped_column(Text, nullable=True)

    # [{filename, size, content_type, path}]
    attachments: Mapped[str] = mapped_column(Text, default="[]")
    extra: Mapped[str] = mapped_column(Text, default="{}")

    dedup_hash: Mapped[str] = mapped_column(String(64), index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # 逻辑删除：删除=软删置位，默认 30 天后由 purge 物理清除（吊销/停用请用 is_active）
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source = relationship("Source", back_populates="messages")


Index("ix_messages_user_created", Message.user_id, Message.created_at.desc())
Index("ix_messages_source_dedup", Message.source_id, Message.dedup_hash, unique=True)
