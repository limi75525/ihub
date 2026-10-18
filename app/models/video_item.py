from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import utcnow


class VideoItem(Base):
    """NAS 本地视频库索引：扫描挂载目录生成，全局共享（文件不复制，只存路径与解析结果）。

    kind=movie：title 为影片名；kind=episode：title/series 为剧名（同一剧集聚合），
    season/episode 取 SxxExx / 第x集 / EPxx 解析值。
    元数据在文件名启发式之上叠加同目录 NFO（movie / tvshow / episodedetails，解析见 services/nfo.py）；
    海报/剧照不做刮削：展示时按同目录与剧集目录探测图片文件（NFO 引用优先），无则前端渐变占位。
    meta_sig 记录 NFO 的 mtime+size：视频文件没动、刮削器重写 NFO 时也能触发重新解析。
    """

    __tablename__ = "video_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 相对视频根目录的文件路径（含扩展名），同一根目录内唯一
    path: Mapped[str] = mapped_column(String(1024))
    kind: Mapped[str] = mapped_column(String(8), default="movie", index=True)  # movie / episode
    title: Mapped[str] = mapped_column(String(512), default="", index=True)
    series: Mapped[str] = mapped_column(String(512), default="")  # 剧集名；组合索引见 __table_args__
    season: Mapped[int] = mapped_column(Integer, default=0)
    episode: Mapped[int] = mapped_column(Integer, default=0, index=True)
    ep_title: Mapped[str] = mapped_column(String(512), default="")
    year: Mapped[int] = mapped_column(Integer, default=0)
    # NFO 元数据（无 NFO 时为空/0）
    original_title: Mapped[str] = mapped_column(String(512), default="")
    plot: Mapped[str] = mapped_column(Text, default="")
    rating: Mapped[float] = mapped_column(Float, default=0.0)
    genres: Mapped[str] = mapped_column(String(256), default="")  # 逗号连接
    directors: Mapped[str] = mapped_column(String(512), default="")  # 逗号连接
    actors: Mapped[str] = mapped_column(Text, default="")  # JSON [[姓名, 角色, 头像URL], ...]
    runtime_min: Mapped[int] = mapped_column(Integer, default=0)
    poster_ref: Mapped[str] = mapped_column(String(512), default="")  # NFO 声明的本地海报文件名
    fanart_ref: Mapped[str] = mapped_column(String(512), default="")
    # 系列级（tvshow.nfo，仅分集行有值，聚合适配用）
    series_plot: Mapped[str] = mapped_column(Text, default="")
    series_rating: Mapped[float] = mapped_column(Float, default=0.0)
    series_genres: Mapped[str] = mapped_column(String(256), default="")
    # TMDB 编号（在线补全海报/剧照用；纯数字）；剧集取 tvshow.nfo 的编号
    tmdb_id: Mapped[str] = mapped_column(String(32), default="")
    series_tmdb_id: Mapped[str] = mapped_column(String(32), default="")
    meta_sig: Mapped[str] = mapped_column(String(64), default="")  # NFO mtime_ns:size，增量依据
    ext: Mapped[str] = mapped_column(String(16), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    mtime: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("path", name="uq_video_items_path"),)


Index("ix_video_items_series", VideoItem.series, VideoItem.season, VideoItem.episode)
