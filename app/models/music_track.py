from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import utcnow


class MusicTrack(Base):
    """NAS 本地音乐库索引：扫描挂载目录生成，全局共享（文件不复制，只存路径与标签）。"""

    __tablename__ = "music_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 相对音乐根目录的文件路径（含扩展名），同一根目录内唯一
    path: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(512), default="")
    artist: Mapped[str] = mapped_column(String(512), default="")
    album: Mapped[str] = mapped_column(String(512), default="")
    # FLAC/MP3/M4A 等标签扩展信息（NAS 扫描时由 mutagen 解析）
    album_artist: Mapped[str] = mapped_column(String(512), default="")
    genre: Mapped[str] = mapped_column(String(128), default="")
    year: Mapped[int] = mapped_column(Integer, default=0)  # 发行年份（标签日期取 4 位年）
    track_no: Mapped[int] = mapped_column(Integer, default=0)  # 曲目号（含总轨数时取前值）
    disc_no: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[float] = mapped_column(Float, default=0)  # 秒
    bitrate: Mapped[int] = mapped_column(Integer, default=0)  # kbps
    sample_rate: Mapped[int] = mapped_column(Integer, default=0)  # Hz
    ext: Mapped[str] = mapped_column(String(16), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    mtime: Mapped[int] = mapped_column(Integer, default=0)
    # 内嵌封面落盘后的相对路径（data/music_covers/ 下），无封面为空
    cover_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # 标签解析失败的原始备注（如 “无标签，按文件名识别”）备用
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("path", name="uq_music_tracks_path"),)


Index("ix_music_tracks_title", MusicTrack.title)
