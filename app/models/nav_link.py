from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import utcnow


class NavLink(Base):
    """常用导航：每个用户自己的书签，支持双地址（默认/内网）与拖拽排序。"""

    __tablename__ = "nav_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    name: Mapped[str] = mapped_column(String(128))
    # 描述只在导航管理页展示，概览卡只显示 logo + 标题
    description: Mapped[str] = mapped_column(String(512), default="")
    # 默认地址（必填）与内网地址（选填）
    url: Mapped[str] = mapped_column(String(1024))
    url_lan: Mapped[str] = mapped_column(String(1024), default="")
    # 二选一：上传的 logo（相对 DATA_DIR）或在线地址（原样存储，展示端按头像库规则补全）
    logo_path: Mapped[str] = mapped_column(String(512), default="")
    logo_url: Mapped[str] = mapped_column(String(1024), default="")
    # new=新窗口打开 / current=当前页面打开
    open_mode: Mapped[str] = mapped_column(String(8), default="new")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_nav_user_sort", NavLink.user_id, NavLink.sort_order)
