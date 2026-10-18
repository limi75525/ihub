from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import utcnow


class LogoGroup(Base):
    """头像库企业分组：一个企业（单位）一个名称与默认头像，下辖多条匹配规则。

    规则侧（logo_rules.group_id）持有具体匹配字段；规则可另设「精确头像」
    覆盖同企业不同部门/子品牌（如 美团外卖 vs 美团），未设则回退企业默认头像。
    空字段以 '' 存储，便于唯一约束判定重复；删除 = 软删（级联软删成员规则），
    30 天后由 purge 物理清除。
    """

    __tablename__ = "logo_groups"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_logo_group"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    logo_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
