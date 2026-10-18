from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import utcnow


class IngestNonce(Base):
    """设备推送防重放 nonce（持久化）：重启/多 worker 均有效。

    (device_code, nonce) 唯一；过期行由定时清理删除。
    """

    __tablename__ = "ingest_nonces"

    device_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
