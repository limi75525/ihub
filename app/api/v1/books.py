"""书架：TXT/EPUB 图书导入、目录、正文、阅读进度与删除。

上传复用快传分片管道（/transfer/upload/*，4MB 分片绕开反代体积限制），
导入时把文件从文件库移动到 data/books/ 并解析章节。
"""

import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_media_user
from app.core.fsutil import data_file, safe_mtime
from app.core.timeutil import as_utc
from app.db.session import get_db
from app.models.book import Book, BookChapter, BookProgress
from app.models.transfer_item import TransferItem
from app.models.user import User
from app.services import book_service
from app.core import data_dirs

router = APIRouter(prefix="/books", tags=["books"])

BOOK_MIME = {
    ".pdf": "application/pdf",
    ".epub": "application/epub+zip",
    ".mobi": "application/x-mobipocket-ebook",
    ".azw3": "application/vnd.amazon.ebook",
    ".fb2": "application/xml",
    ".txt": "text/plain",
}

BOOK_EXTS = {".txt", ".epub", ".pdf", ".mobi", ".azw3", ".fb2"}
BOOK_MAX_SIZE = 200 * 1024 * 1024  # 单本 200MB，书籍文件远小于该值
REFLOW_EXTS = {".txt", ".epub", ".mobi", ".azw3", ".fb2"}  # 可重排阅读的格式；PDF 走内嵌查看器


def _own_book(db: Session, user: User, book_id: int) -> Book:
    book = db.get(Book, book_id)
    if not book or book.user_id != user.id or book.is_deleted:
        raise HTTPException(404, "图书不存在")
    return book


def _progress_of(db: Session, user: User, book_id: int) -> BookProgress | None:
    return (
        db.query(BookProgress)
        .filter(BookProgress.user_id == user.id, BookProgress.book_id == book_id)
        .first()
    )


def _cover_url(book: Book) -> str | None:
    """封面展示地址（带 mtime 版本防缓存）；文件缺失回退 None。
    safe_mtime：并发换封面（stat 时文件已被删除）不抛错，列表接口不 500。"""
    if not book.cover_path:
        return None
    v = safe_mtime(Path(settings.DATA_DIR) / book.cover_path)
    if not v:
        return None
    return f"/api/v1/books/{book.id}/cover?v={v}"


def _book_dict(book: Book, prog: BookProgress | None) -> dict:
    percent = 0
    if prog and book.chapter_count:
        percent = round(min(100, (prog.chapter_idx + prog.frac) / book.chapter_count * 100))
    return {
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "format": book.format,
        "size": book.size,
        "cover": _cover_url(book),
        "chapter_count": book.chapter_count,
        "total_chars": book.total_chars,
        "created_at": as_utc(book.created_at),
        "progress": (
            {
                "chapter_idx": prog.chapter_idx,
                "frac": round(prog.frac, 4),
                "updated_at": as_utc(prog.updated_at),
            }
            if prog
            else None
        ),
        "percent": percent,
    }


def _out(db: Session, user: User, book: Book) -> dict:
    return _book_dict(book, _progress_of(db, user, book.id))


class ImportIn(BaseModel):
    item_id: int


@router.post("/import")
def import_book(
    body: ImportIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """从文件库导入 TXT/EPUB：解析章节 → 移动文件 → 建书（文件库条目随后删除）。

    先用文件库中的源文件解析，成功后才移动：解析失败时源文件原地不动，
    避免「文件已移走又删掉、文件库条目却还在」的数据丢失。
    """
    item = (
        db.query(TransferItem)
        .filter(TransferItem.id == body.item_id, TransferItem.user_id == user.id)
        .first()
    )
    if not item or not item.file_path:
        raise HTTPException(404, "文件库条目不存在")
    ext = Path(item.file_name or "").suffix.lower()
    if ext not in BOOK_EXTS:
        raise HTTPException(400, "仅支持 TXT / EPUB / PDF / MOBI / AZW3 / FB2 格式")
    src = (Path(settings.DATA_DIR) / item.file_path).resolve()
    if not src.is_file():
        raise HTTPException(404, "文件库源文件缺失")
    if src.stat().st_size > BOOK_MAX_SIZE:
        raise HTTPException(400, "书籍文件不能超过 200MB")

    try:
        if ext == ".epub":
            # 先按 zip central directory 预检解压后大小（防解压炸弹），再交给 ebooklib
            book_service.epub_guard(src)
            parsed = book_service.parse_epub(src)
        elif ext == ".pdf":
            parsed = book_service.parse_pdf(src, Path(item.file_name).stem)
        elif ext == ".fb2":
            parsed = book_service.parse_fb2(src)
        elif ext in (".mobi", ".azw3"):
            parsed = book_service.parse_mobi(src, Path(item.file_name).stem)
        else:
            parsed = book_service.parse_txt(src.read_bytes(), Path(item.file_name).stem)
    except Exception:
        # 解析失败：源文件仍在文件库，条目不动，用户可直接重试或删除
        raise HTTPException(400, "书籍解析失败，请确认文件完整未损坏")

    dest_dir = Path(settings.DATA_DIR) / data_dirs.BOOKS
    dest_dir.mkdir(parents=True, exist_ok=True)
    book = Book(user_id=user.id, format=ext.lstrip("."), size=src.stat().st_size)
    db.add(book)
    db.flush()  # 先拿 id 用于落盘命名

    dest = dest_dir / f"book_{book.id}_{user.id}{ext}"
    book_id = book.id  # rollback 后实例过期，届时再取 id 会为 None
    try:
        shutil.move(str(src), dest)
        book.file_path = f"books/{dest.name}"
        book.title = (parsed["title"] or Path(item.file_name).stem)[:256]
        book.author = (parsed["author"] or "")[:128]
        book.cover_path = book_service.save_cover(book.id, parsed["cover_bytes"] or b"")
        rows = [
            BookChapter(book_id=book.id, idx=i, title=c["title"][:256], content=c["html"],
                        char_count=len(c["html"]))
            for i, c in enumerate(parsed["chapters"])
        ]
        db.add_all(rows)
        book.chapter_count = len(rows)
        book.total_chars = sum(r.char_count for r in rows)
        db.delete(item)  # 文件已移走，文件库条目一并清除
        db.commit()
    except Exception:
        # 移动之后任何失败：把文件移回文件库原位，保住条目指向，不留死条目；
        # 本轮已落盘的封面一并回收（save_cover 以 book_{id}_ 前缀命名）
        db.rollback()
        if dest.is_file() and not src.is_file():
            try:
                shutil.move(str(dest), str(src))
            except OSError:
                pass
        try:
            for f in (Path(settings.DATA_DIR) / data_dirs.BOOK_COVERS).glob(f"book_{book_id}_*"):
                f.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(500, "书籍入库失败，请重试")
    db.refresh(book)
    return _out(db, user, book)


@router.get("")
def list_books(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """书架列表：在读的排最前（按进度更新时间倒序），未读的按入库时间倒序排在后面。
    书架页与总览「书架 · 继续阅读」卡共用本接口，两处自然同步。"""
    rows = (
        # 进度行随 join 一并取出（每书至多一条）：避免 _out 逐本再查一次进度（N+1）
        db.query(Book, BookProgress)
        .outerjoin(
            BookProgress,
            (BookProgress.book_id == Book.id) & (BookProgress.user_id == user.id),
        )
        .filter(Book.user_id == user.id, Book.is_deleted.is_(False))
        .order_by(
            # SQLite 布尔升序：IS NULL=1 排在后 → 有进度的书在前
            BookProgress.updated_at.is_(None),
            BookProgress.updated_at.desc(),
            Book.created_at.desc(),
            Book.id.desc(),
        )
        .all()
    )
    return [_book_dict(b, prog) for b, prog in rows]


@router.get("/{book_id}/toc")
def book_toc(book_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    book = _own_book(db, user, book_id)
    chapters = (
        db.query(BookChapter.idx, BookChapter.title, BookChapter.char_count)
        .filter(BookChapter.book_id == book.id)
        .order_by(BookChapter.idx)
        .all()
    )
    prog = _progress_of(db, user, book.id)
    return {
        "book": _out(db, user, book),
        "chapters": [{"idx": c.idx, "title": c.title, "char_count": c.char_count} for c in chapters],
        "progress": {"chapter_idx": prog.chapter_idx, "frac": prog.frac} if prog else None,
    }


@router.get("/{book_id}/content/{idx}")
def book_content(
    book_id: int,
    idx: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    book = _own_book(db, user, book_id)
    chapter = (
        db.query(BookChapter)
        .filter(BookChapter.book_id == book.id, BookChapter.idx == idx)
        .first()
    )
    if not chapter:
        raise HTTPException(404, "章节不存在")
    return {
        "idx": chapter.idx,
        "title": chapter.title,
        "content": chapter.content,
        "char_count": chapter.char_count,
        "has_prev": idx > 0,
        "has_next": idx < book.chapter_count - 1,
    }


class ProgressIn(BaseModel):
    chapter_idx: int = Field(ge=0)
    frac: float = Field(ge=0, le=1)


@router.put("/{book_id}/progress")
def save_progress(
    book_id: int,
    body: ProgressIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    book = _own_book(db, user, book_id)
    if body.chapter_idx >= max(1, book.chapter_count):
        raise HTTPException(400, "章节越界")
    prog = _progress_of(db, user, book.id)
    if prog is None:
        prog = BookProgress(user_id=user.id, book_id=book.id)
        db.add(prog)
    prog.chapter_idx = body.chapter_idx
    prog.frac = body.frac
    prog.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.delete("/{book_id}")
def delete_book(book_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.api.v1.recycle import recycle_enabled

    book = _own_book(db, user, book_id)
    if recycle_enabled():
        book.is_deleted = True
        book.deleted_at = datetime.now(timezone.utc)
    else:
        _purge_book(db, book)
    db.commit()
    return {"ok": True}


def _purge_book(db: Session, book: Book) -> None:
    """物理删除：书籍文件、封面、章节与进度一并清除。"""
    if book.file_path:
        p = data_dirs.resolve_rel(book.file_path)
        if p:
            p.unlink(missing_ok=True)
    cp = data_dirs.resolve_rel(book.cover_path)
    if cp:
        cp.unlink(missing_ok=True)
    db.query(BookChapter).filter(BookChapter.book_id == book.id).delete(synchronize_session=False)
    db.query(BookProgress).filter(BookProgress.book_id == book.id).delete(synchronize_session=False)
    db.delete(book)


@router.get("/{book_id}/file")
def book_file(book_id: int, user: User = Depends(get_media_user), db: Session = Depends(get_db)):
    """原文件读取：PDF 内嵌查看与「下载到本地」共用。

    与 book_asset 一致做属主校验：任何持有自己 media_key 的用户只能读自己的书，
    软删（回收站）中的书同样拒绝——否则跨用户/已删数据可被任意登录者下载。
    """
    book = _own_book(db, user, book_id)
    if not book.file_path:
        raise HTTPException(404, "书籍文件缺失")
    p = data_dirs.resolve_rel(book.file_path)
    if not p or not p.is_file():
        raise HTTPException(404, "书籍文件缺失")
    return FileResponse(p, media_type=BOOK_MIME.get(p.suffix.lower(), "application/octet-stream"))


@router.get("/{book_id}/cover")
def book_cover(book_id: int, user: User = Depends(get_media_user), db: Session = Depends(get_db)):
    book = _own_book(db, user, book_id)
    if not book.cover_path:
        raise HTTPException(404, "无封面")
    p = data_dirs.resolve_rel(book.cover_path)
    if not p or not p.is_file():
        raise HTTPException(404, "无封面")
    return FileResponse(p)


@router.get("/{book_id}/asset")
def book_asset(
    book_id: int,
    path: str,
    user: User = Depends(get_media_user),
    db: Session = Depends(get_db),
):
    """EPUB 内嵌资源（图片等），path 为书籍内部相对路径。"""
    book = _own_book(db, user, book_id)
    if book.format != "epub":
        raise HTTPException(404, "非 EPUB 图书")
    data = book_service.epub_asset(Path(settings.DATA_DIR) / book.file_path, path)
    if data is None:
        raise HTTPException(404, "资源不存在")
    from fastapi.responses import Response

    ext = Path(path).suffix.lower()
    mime = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    }.get(ext, "application/octet-stream")
    if mime == "image/svg+xml":
        raise HTTPException(404, "资源不存在")  # SVG 不内联输出（防脚本）
    return Response(content=data, media_type=mime)
