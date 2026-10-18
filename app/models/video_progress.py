from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import utcnow


class VideoProgress(Base):
    """观影进度：按 用户+源+条目 一条，position/duration 单位秒。

    item_key：NAS 源为 video_items 数据库 id（字符串）；Jellyfin 源为其服务端的条目 id。
    Jellyfin 源上报进度时双写上游 /Sessions/Playing/Progress（尽力而为，失败不影响本地），
    继续观看列表在 Jellyfin 源直接读上游 /Items/Resume，本地行只作 NAS 侧与兜底。
    """

    __tablename__ = "video_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    source: Mapped[str] = mapped_column(String(16), default="")
    item_key: Mapped[str] = mapped_column(String(512), default="")
    position: Mapped[float] = mapped_column(Float, default=0)
    duration: Mapped[float] = mapped_column(Float, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "source", "item_key", name="uq_video_progress_key"),)


Index("ix_video_progress_user_src", VideoProgress.user_id, VideoProgress.source)
