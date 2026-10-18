from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import utcnow


class TransferDir(Base):
    """文件库目录：逻辑目录（文件物理存储仍是 transfer/<uid>/ 平铺），
    仅作为文件的组织视图。path 为归一化相对路径（"a/b"，根目录不在本表）。"""

    __tablename__ = "transfer_dirs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # 归一化路径（不含首尾斜杠），如 "photos/2024"
    path: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "path", name="uq_transfer_dir"),)


Index("ix_transfer_dir_user_path", TransferDir.user_id, TransferDir.path)
