from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    nickname: Mapped[str] = mapped_column(String(64), default="")
    # 个性签名：用户卡昵称下方展示，空则不展示
    signature: Mapped[str] = mapped_column(String(128), default="")
    email: Mapped[str] = mapped_column(String(128), default="")
    avatar_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # 上次登录 IP：与本次不同时触发登录提醒（首次登录不提醒）
    last_login_ip: Mapped[str] = mapped_column(String(64), default="")
    role: Mapped[str] = mapped_column(String(16), default="user")  # admin / user
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 密码版本号：改密码/管理员重置密码时 +1，使旧 JWT 全部失效（token 内携带该版本）
    pwd_version: Mapped[int] = mapped_column(Integer, default=0)
    # 媒体访问密钥：仅用于图片/附件等 GET 资源的 ?token= 鉴权，改密码时轮换
    media_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # 逻辑删除：删除=软删置位，默认 30 天后由 purge 物理清除（吊销/停用请用 is_active）
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
