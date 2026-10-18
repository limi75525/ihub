"""逻辑删除到期物理清理：软删行默认保留 30 天后真正删除（含磁盘附件/Logo/头像回收）。

调度：启动时执行一次 + scheduler 每日定时（见 scheduler.register_purge_job）。
删除顺序保证依赖与文件清理安全：messages → logo_rules → sources → devices → users。
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil

from sqlalchemy import func, text

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.book import Book
from app.models.device import Device
from app.models.logo_group import LogoGroup
from app.models.logo_rule import LogoRule
from app.models.message import Message
from app.models.music_playlist import MusicPlaylist, MusicPlaylistItem
from app.models.music_user_stat import MusicUserStat
from app.models.nav_link import NavLink
from app.models.source import Source
from app.models.transfer_item import TransferItem
from app.models.user import User
from app.models.video_progress import VideoProgress
from app.services.ingest_service import delete_attachments

PURGE_DAYS = 30


def _unlink_under_data(rel: str | None) -> None:
    """删除 DATA_DIR 下的库内登记文件；带前缀与穿越校验，空/越界路径一律不动。"""
    if not rel:
        return
    p = (Path(settings.DATA_DIR) / rel).resolve()
    try:
        p.relative_to(Path(settings.DATA_DIR).resolve())
    except ValueError:
        return
    p.unlink(missing_ok=True)


def _rmdir_under_data(rel: str) -> None:
    """删除 DATA_DIR 下的整目录（仅用于被删用户自己的 transfer 目录）。"""
    root = (Path(settings.DATA_DIR) / rel).resolve()
    try:
        root.relative_to(Path(settings.DATA_DIR).resolve())
    except ValueError:
        return
    if not root.is_dir():
        return
    # shutil 兜任意层级嵌套：手写双层 iterdir 在更深的子目录上会抛 OSError
    # 被 pass 吞掉，留下「已删用户」的残留文件（隐私清理承诺失效）
    shutil.rmtree(root, ignore_errors=True)


def _purge_user_assets(db, user_id: int) -> None:
    """物理清理被删用户的全部残留资源（行 + 磁盘文件）。

    原先只删头像文件：transfer 文件、书籍、导航 Logo、歌单封面、听书统计
    全部残留——被删用户的私有数据长期躺在磁盘上，属隐私残留与存储滥用。
    """
    # 1) 快传/文件库：整目录 + 行
    _rmdir_under_data(f"transfer/{user_id}")
    db.query(TransferItem).filter(TransferItem.user_id == user_id).delete(synchronize_session=False)
    # 2) 书籍：原文件 + 封面 + 章节/进度行
    book_ids = [b.id for b in db.query(Book.id).filter(Book.user_id == user_id).all()]
    for b in db.query(Book).filter(Book.user_id == user_id).all():
        _unlink_under_data(b.file_path)
        _unlink_under_data(b.cover_path)
    if book_ids:
        from app.models.book import BookChapter, BookProgress

        db.query(BookChapter).filter(BookChapter.book_id.in_(book_ids)).delete(synchronize_session=False)
        db.query(BookProgress).filter(BookProgress.book_id.in_(book_ids)).delete(synchronize_session=False)
    db.query(Book).filter(Book.user_id == user_id).delete(synchronize_session=False)
    # 3) 常用导航：上传 Logo 文件 + 行（在线 logo_url 无文件）
    for l in db.query(NavLink).filter(NavLink.user_id == user_id).all():
        if l.logo_path and l.logo_path.replace("\\", "/").startswith("nav_logos/"):
            _unlink_under_data(l.logo_path)
    db.query(NavLink).filter(NavLink.user_id == user_id).delete(synchronize_session=False)
    # 4) 音乐歌单：自定义封面 + 曲目项 + 行；听书记统计行
    for p in db.query(MusicPlaylist).filter(MusicPlaylist.user_id == user_id).all():
        if p.cover_path and p.cover_path.replace("\\", "/").startswith("playlist_covers/"):
            _unlink_under_data(p.cover_path)
        db.query(MusicPlaylistItem).filter(MusicPlaylistItem.playlist_id == p.id).delete(
            synchronize_session=False
        )
    db.query(MusicPlaylist).filter(MusicPlaylist.user_id == user_id).delete(synchronize_session=False)
    db.query(MusicUserStat).filter(MusicUserStat.user_id == user_id).delete(synchronize_session=False)
    # 5) 观影进度行（无磁盘文件）
    db.query(VideoProgress).filter(VideoProgress.user_id == user_id).delete(synchronize_session=False)
    # 5.5) 头像库：企业分组 Logo 文件 + 成员规则 Logo 文件 + 两表行
    from app.models.logo_group import LogoGroup

    for g in db.query(LogoGroup).filter(LogoGroup.user_id == user_id).all():
        if g.logo_path and g.logo_path.replace("\\", "/").startswith("logos/"):
            _unlink_under_data(g.logo_path)
    for r in db.query(LogoRule).filter(LogoRule.user_id == user_id).all():
        if r.logo_path and r.logo_path.replace("\\", "/").startswith("logos/"):
            _unlink_under_data(r.logo_path)
    db.query(LogoRule).filter(LogoRule.user_id == user_id).delete(synchronize_session=False)
    db.query(LogoGroup).filter(LogoGroup.user_id == user_id).delete(synchronize_session=False)


def purge_expired() -> dict:
    db = SessionLocal()
    stats = {"messages": 0, "logo_rules": 0, "sources": 0, "devices": 0, "books": 0, "users": 0}
    try:
        cut = datetime.now(timezone.utc) - timedelta(days=PURGE_DAYS)

        # 1) 消息：先回收附件目录，再删行
        msgs = (
            db.query(Message)
            .filter(Message.is_deleted.is_(True), Message.deleted_at < cut)
            .all()
        )
        for m in msgs:
            delete_attachments(m.attachments)
            db.delete(m)
            stats["messages"] += 1
        db.flush()

        # 2) 头像规则与分组（删自有 Logo 文件；引用文件库的图片归文件库所有，不动）
        #    分组到期 = 整个企业删除：分组行 + 其全部（软删）成员规则一并清除
        rules = (
            db.query(LogoRule)
            .filter(LogoRule.is_deleted.is_(True), LogoRule.deleted_at < cut)
            .all()
        )
        for r in rules:
            if r.logo_path and r.logo_path.replace("\\", "/").startswith("logos/"):
                _unlink_under_data(r.logo_path)
            db.delete(r)
        stats["logo_rules"] += len(rules)
        groups = (
            db.query(LogoGroup)
            .filter(LogoGroup.is_deleted.is_(True), LogoGroup.deleted_at < cut)
            .all()
        )
        for g in groups:
            if g.logo_path and g.logo_path.replace("\\", "/").startswith("logos/"):
                _unlink_under_data(g.logo_path)
            # 成员规则若因单独删除被漏掉（时间戳不同），随分组一并清除
            for r in db.query(LogoRule).filter(LogoRule.group_id == g.id).all():
                if r.logo_path and r.logo_path.replace("\\", "/").startswith("logos/"):
                    _unlink_under_data(r.logo_path)
                db.delete(r)
            db.delete(g)
        stats["logo_groups"] = len(groups)
        db.flush()

        # 3) 接入服务（删 Logo 文件；其消息已在第 1 步或级联软删中被清理）
        sources = (
            db.query(Source)
            .filter(Source.is_deleted.is_(True), Source.deleted_at < cut)
            .all()
        )
        for s in sources:
            if s.logo_path and s.logo_path.replace("\\", "/").startswith("logos/"):
                _unlink_under_data(s.logo_path)
            db.delete(s)
        stats["sources"] += len(sources)
        db.flush()

        # 4) 设备
        devices = (
            db.query(Device)
            .filter(Device.is_deleted.is_(True), Device.deleted_at < cut)
            .all()
        )
        for d in devices:
            db.delete(d)
            stats["devices"] += 1
        db.flush()

        # 4.5) 书籍（原文件 + 封面 + 章节/进度行）：漏掉这步软删书将永不物理清除，
        # data/books/ 与回收站列表只增不减（模型注释承诺 30 天清除）
        from app.models.book import BookChapter, BookProgress

        books = (
            db.query(Book)
            .filter(Book.is_deleted.is_(True), Book.deleted_at < cut)
            .all()
        )
        for b in books:
            _unlink_under_data(b.file_path)
            _unlink_under_data(b.cover_path)
            db.query(BookChapter).filter(BookChapter.book_id == b.id).delete(synchronize_session=False)
            db.query(BookProgress).filter(BookProgress.book_id == b.id).delete(synchronize_session=False)
            db.delete(b)
            stats["books"] += 1
        db.flush()

        # 5) 用户（删头像文件 + 全部残留资源；其来源/消息/规则已先清理）
        users = (
            db.query(User)
            .filter(User.is_deleted.is_(True), User.deleted_at < cut)
            .all()
        )
        for u in users:
            if u.avatar_path:
                _unlink_under_data(u.avatar_path)
            _purge_user_assets(db, u.id)
            db.delete(u)
            stats["users"] += 1

        # 6) 活跃用户清零时释放「首个用户占位」，允许实例重新引导管理员
        if (db.query(func.count(User.id)).filter(User.is_deleted.is_(False)).scalar() or 0) == 0:
            db.execute(text("DELETE FROM system_settings WHERE key = 'platform_initialized'"))

        db.commit()
    finally:
        db.close()
    return stats
