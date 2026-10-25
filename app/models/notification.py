"""站内系统通知：顶栏铃铛的数据源（与消息中心的普通消息分开）。"""

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutil import utcnow
from app.db.base import Base


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    type: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(256), default="")
    dedup_key: Mapped[str] = mapped_column(String(160), default="", index=True)
    created_at: Mapped[object] = mapped_column(DateTime, default=utcnow)
    read_at: Mapped[object] = mapped_column(DateTime, nullable=True)
