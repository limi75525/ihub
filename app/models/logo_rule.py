from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import utcnow


class LogoRule(Base):
    """展示 LOGO 匹配规则：隶属于一个企业分组（logo_groups），一条规则一组匹配字段。

    匹配字段（空串存储便于唯一约束判重）：
    - signature：企业名称 / 短信签名（参与「签名精确 → 签名前缀」降级）
    - account：号码 / 邮箱地址（含 @ 按邮箱处理：精确 + @ 域名降级；否则按号码精确）
    logo_path / logo_url 是规则的「精确头像」（可空）：同企业不同部门/子品牌用不同
    Logo 时设置；未设置时消息侧回退企业默认头像（见 messages._match_logo）。
    """

    __tablename__ = "logo_rules"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "group_id", "signature", "account",
            name="uq_logo_rule",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    group_id: Mapped[int] = mapped_column(Integer, index=True)
    signature: Mapped[str] = mapped_column(String(64), default="")
    account: Mapped[str] = mapped_column(String(256), default="")
    # 规则自己的精确头像（可空）
    logo_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # 逻辑删除：删除=软删置位，默认 30 天后由 purge 物理清除
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
