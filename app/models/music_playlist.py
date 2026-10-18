from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import utcnow


class MusicPlaylist(Base):
    """用户自建歌单（音乐中心）：按用户隔离；description/cover_path 可空
    （旧库由 _REQUIRED_COLUMNS 轻量迁移补齐）。"""

    __tablename__ = "music_playlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    description: Mapped[str] = mapped_column(String(1024), default="")
    # 自定义封面相对路径（data/playlist_covers/ 下）；空 = 用第一首曲目封面兜底
    cover_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MusicPlaylistItem(Base):
    """歌单曲目：source + track_key 指向原曲（NAS 为曲目 id，Subsonic/Jellyfin 为其服务端 id），
    title/artist/album/duration 为加入时的快照（与 user_music_stats 同策略，展示免回查）。"""

    __tablename__ = "music_playlist_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    playlist_id: Mapped[int] = mapped_column(Integer, index=True)
    source: Mapped[str] = mapped_column(String(16), default="")
    track_key: Mapped[str] = mapped_column(String(512), default="")
    title: Mapped[str] = mapped_column(String(512), default="")
    artist: Mapped[str] = mapped_column(String(512), default="")
    album: Mapped[str] = mapped_column(String(512), default="")
    duration: Mapped[float] = mapped_column(Float, default=0)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_music_playlist_items_pl", MusicPlaylistItem.playlist_id, MusicPlaylistItem.position)
