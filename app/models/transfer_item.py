from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import utcnow


class TransferItem(Base):
    """快传条目：文本 / 文件 / 图片，仅创建者本人可见（两台设备互传的中转站）。"""

    __tablename__ = "transfer_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # text / file / image
    kind: Mapped[str] = mapped_column(String(8), index=True)

    # kind=text 时的文本内容；文件类为空
    content: Mapped[str] = mapped_column(Text, default="")
    file_name: Mapped[str] = mapped_column(String(512), default="")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    content_type: Mapped[str] = mapped_column(String(128), default="")
    # 相对 DATA_DIR 的存储路径（transfer/<uid>/<hex><ext>）
    file_path: Mapped[str] = mapped_column(String(512), default="")

    # share=快传（出现在总览快传卡）/ library=文件库上传（不进快传卡，文件库可见）
    origin: Mapped[str] = mapped_column(String(16), server_default=text("'share'"), default="share")

    # 逻辑目录（文件库视图用）："" = 根目录，"a/b" = 归一化目录路径；物理存储始终平铺
    dir_path: Mapped[str] = mapped_column(String(256), server_default=text("''"), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_transfer_user_created", TransferItem.user_id, TransferItem.created_at.desc())
