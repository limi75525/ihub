from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.user import utcnow


class Book(Base):
    """书架图书：文件存 data/books/，封面存 data/book_covers/，章节在 book_chapters。"""

    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    author: Mapped[str] = mapped_column(String(128), default="")
    # epub / txt
    format: Mapped[str] = mapped_column(String(8), default="txt")
    # 相对 data 目录的书籍文件路径；封面为空时前端出占位封面
    file_path: Mapped[str] = mapped_column(String(512), default="")
    cover_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    size: Mapped[int] = mapped_column(Integer, default=0)
    chapter_count: Mapped[int] = mapped_column(Integer, default=0)
    total_chars: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # 逻辑删除：与消息/来源一致，30 天后由 purge 物理清除（回收站可恢复）
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BookChapter(Base):
    """书籍章节内容（统一存 HTML）。book_id + idx 唯一，idx 从 0 开始。"""

    __tablename__ = "book_chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    idx: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(256), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    char_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("book_id", "idx", name="uq_book_chapters"),)


class BookProgress(Base):
    """阅读进度：每用户每书一条。frac 为章节内位置（滚动比例或页码比例 0~1）。"""

    __tablename__ = "book_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    chapter_idx: Mapped[int] = mapped_column(Integer, default=0)
    frac: Mapped[float] = mapped_column(Float, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "book_id", name="uq_book_progress"),)


Index("ix_book_chapters_book", BookChapter.book_id, BookChapter.idx)
