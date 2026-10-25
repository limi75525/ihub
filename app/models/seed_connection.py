"""种子模块的上游连接（qBittorrent / MoviePilot）。

只保存连接配置与事件水位，不保存种子/订阅等业务数据：
- qBittorrent 是下载器事实源；
- MoviePilot 是订阅、站点、搜索等业务事实源；
- 种子列表与订阅列表按需从上游读取，短 TTL 缓存。

secret_cipher 使用 Fernet 加密（qB 密码或 MoviePilot API_TOKEN），
API 输出永不回传明文，只回 secret_set 布尔值。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import utcnow


class SeedConnection(Base):
    __tablename__ = "seed_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # qbittorrent / moviepilot
    kind: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    base_url: Mapped[str] = mapped_column(String(1024), default="")
    username: Mapped[str] = mapped_column(String(256), default="")
    secret_cipher: Mapped[str] = mapped_column(String(1024), default="")
    # qB: password / none；MP: api_token / password
    auth_mode: Mapped[str] = mapped_column(String(16), default="password")
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    poll_interval: Mapped[int] = mapped_column(Integer, default=0)

    # 上游版本与能力探测结果（JSON 字符串；失败不影响功能）
    server_version: Mapped[str] = mapped_column(String(64), default="")
    capabilities_json: Mapped[str] = mapped_column(Text, default="")

    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(String(512), default="")

    # 事件水位：qB 用 completion_on（秒），MP 用通知 id
    last_completed_at: Mapped[int] = mapped_column(Integer, default=0)
    last_notification_id: Mapped[int] = mapped_column(Integer, default=0)

    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)


Index("ix_seed_connections_kind_sort", SeedConnection.kind, SeedConnection.sort_order)
