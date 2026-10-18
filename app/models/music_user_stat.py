from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import utcnow


class MusicUserStat(Base):
    """音乐用户数据（收藏 / 播放统计），按用户与音源隔离。

    track_key：NAS 源为曲目数据库 id；Subsonic / Jellyfin 为其服务端的曲目 id。
    title/artist/album/duration 为播放时留下的快照，供「最近播放」直接展示，
    避免回查上游服务；Subsonic 源的 star/scrobble 会双写上游（尽力而为）。
    """

    __tablename__ = "user_music_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    source: Mapped[str] = mapped_column(String(16), default="")
    track_key: Mapped[str] = mapped_column(String(512), default="")
    title: Mapped[str] = mapped_column(String(512), default="")
    artist: Mapped[str] = mapped_column(String(512), default="")
    album: Mapped[str] = mapped_column(String(512), default="")
    duration: Mapped[float] = mapped_column(Float, default=0)
    starred: Mapped[bool] = mapped_column(Boolean, default=False)
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    # 最近一次播放的 UNIX 时间戳（秒），0 = 从未播放
    last_played: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "source", "track_key", name="uq_user_music_stats_key"),)


Index("ix_user_music_stats_user", MusicUserStat.user_id, MusicUserStat.source)
