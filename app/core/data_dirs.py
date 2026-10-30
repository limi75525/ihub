"""data/ 目录布局 v2：全部子目录带 ihub_ 前缀（自标识，防与其他应用混放）。

布局（2026-10-25 起）：
  ihub_media/{books,music_covers,video_covers,playlist_covers}   音乐/影视/书架
  ihub_avatars/       头像库（分组/规则/来源/站点/picker 缓存）+ 用户头像 ihub_user_avatars_<uid>.*
  ihub_nav_logos/     导航 logo
  ihub_attachments/   邮件附件 <source_id>/<dedup>/
  ihub_transfer/      快传/文件库用户文件 <uid>/
  ihub_cache/         纯缓存与临时：seed_covers/、tmp/

v1（无前缀平铺）→ v2 由 migrate_layout() 在启动时一次性迁移：目录 move +
DB 相对路径批量 UPDATE + system_settings 标记 dir_layout_v2；任何一步失败
整体回滚并让启动失败（宁可起不来也不留半迁移状态）。data_file() 对旧前缀
做兼容翻译，作为迁移遗漏时的兜底读。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.core.config import settings
from app.core.fsutil import data_file as _data_file

logger = logging.getLogger(__name__)

MEDIA = "ihub_media"
BOOKS = f"{MEDIA}/books"
BOOK_COVERS = f"{MEDIA}/book_covers"
MUSIC_COVERS = f"{MEDIA}/music_covers"
VIDEO_COVERS = f"{MEDIA}/video_covers"
PLAYLIST_COVERS = f"{MEDIA}/playlist_covers"
AVATARS = "ihub_avatars"
NAV_LOGOS = "ihub_nav_logos"
ATTACHMENTS = "ihub_attachments"
BG = "ihub_bg"  # 登录背景图
TRANSFER = "ihub_transfer"
CACHE = "ihub_cache"
SEED_COVERS = f"{CACHE}/seed_covers"
TMP = f"{CACHE}/tmp"

FLAG_KEY = "dir_layout_v2"

# 旧相对路径前缀 → 新前缀。顺序敏感：长前缀（transfer/_tmp）必须在前。
_LEGACY_PREFIX_MAP: tuple[tuple[str, str], ...] = (
    ("transfer/_tmp/", TMP + "/"),
    ("transfer/", TRANSFER + "/"),
    ("books/", BOOKS + "/"),
    ("book_covers/", BOOK_COVERS + "/"),
    ("music_covers/", MUSIC_COVERS + "/"),
    ("video_covers/", VIDEO_COVERS + "/"),
    ("playlist_covers/", PLAYLIST_COVERS + "/"),
    ("nav_logos/", NAV_LOGOS + "/"),
    ("attachments/", ATTACHMENTS + "/"),
    ("bg/", BG + "/"),
    ("logos/", AVATARS + "/"),
    ("avatars/", AVATARS + "/"),
    ("seed_covers/", SEED_COVERS + "/"),
)

# 迁移时要批量改写相对路径的 (表, 列)。system_settings 的 site_logo_path 单独处理。
_PATH_COLUMNS: tuple[tuple[str, str], ...] = (
    ("books", "file_path"),
    ("books", "cover_path"),
    ("music_tracks", "cover_path"),
    ("music_playlists", "cover_path"),
    ("logo_groups", "logo_path"),
    ("logo_rules", "logo_path"),
    ("sources", "logo_path"),
    ("nav_links", "logo_path"),
    ("users", "avatar_path"),
)

_USER_AVATAR_RE = re.compile(r"^user_(\d+)_[0-9a-f]+\.(.+)$")


def translate_rel(rel: str) -> str:
    """旧版相对路径 → v2 相对路径；已是 v2 或未知前缀原样返回。"""
    rel = rel.replace("\\", "/")
    for old, new in _LEGACY_PREFIX_MAP:
        if rel.startswith(old):
            return new + rel[len(old):]
    return rel


def resolve_rel(rel: str | None) -> Path | None:
    """DB 相对路径 → DATA_DIR 内绝对路径（先做 v1→v2 翻译，含越界防护）。"""
    if not rel:
        return None
    return _data_file(settings.DATA_DIR, translate_rel(rel))


def _move_dir(src: Path, dst: Path, journal: list[tuple[Path, Path]]) -> None:
    """整目录改名（同卷 rename）；目标已存在则跳过（幂等）。"""
    if not src.is_dir():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    src.rename(dst)
    journal.append((dst, src))  # 回滚 = 反向


def _move_file(src: Path, dst: Path, journal: list[tuple[Path, Path]]) -> None:
    if not src.is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    src.rename(dst)
    journal.append((dst, src))


def migrate_layout() -> None:
    """v1 平铺布局 → v2 ihub_ 前缀布局。幂等；失败整体回滚并抛出让启动失败。"""
    from sqlalchemy import text

    from app.db.session import SessionLocal
    from app.models.system_setting import get_setting_db

    try:
        db = SessionLocal()
        try:
            if get_setting_db(db, FLAG_KEY, ""):
                return
        finally:
            db.close()

        root = Path(settings.DATA_DIR)
        journal: list[tuple[Path, Path]] = []
        try:
            # ---- 文件阶段：整目录改名（1:1）----
            _move_dir(root / "books", root / BOOKS, journal)
            _move_dir(root / "book_covers", root / BOOK_COVERS, journal)
            _move_dir(root / "music_covers", root / MUSIC_COVERS, journal)
            _move_dir(root / "video_covers", root / VIDEO_COVERS, journal)
            _move_dir(root / "playlist_covers", root / PLAYLIST_COVERS, journal)
            _move_dir(root / "nav_logos", root / NAV_LOGOS, journal)
            _move_dir(root / "attachments", root / ATTACHMENTS, journal)
            _move_dir(root / "bg", root / BG, journal)
            _move_dir(root / "seed_covers", root / SEED_COVERS, journal)
            _move_dir(root / "transfer" / "_tmp", root / TMP, journal)
            _move_dir(root / "transfer", root / TRANSFER, journal)

            # ---- 合并阶段：logos/ 与 avatars/ → ihub_avatars/ ----
            target = root / AVATARS
            target.mkdir(parents=True, exist_ok=True)
            for legacy in ("logos", "avatars"):
                src_dir = root / legacy
                if not src_dir.is_dir():
                    continue
                for f in list(src_dir.iterdir()):
                    if not f.is_file():
                        continue
                    m = _USER_AVATAR_RE.match(f.name)
                    dst = target / f.name
                    if m:  # 旧用户头像 user_<uid>_<hex>.<ext> → 固定名
                        uid, ext = m.group(1), m.group(2)
                        dst = target / f"ihub_user_avatars_{uid}.{ext}"
                    _move_file(f, dst, journal)
                try:
                    src_dir.rmdir()
                except OSError:
                    pass
        except Exception:
            # 文件阶段失败：按回滚日志逆向还原
            for dst, src in reversed(journal):
                try:
                    if dst.is_dir():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        dst.rename(src)
                    elif dst.is_file():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        dst.rename(src)
                except OSError:
                    logger.exception("目录迁移回滚失败：%s → %s", dst, src)
            raise

        # ---- DB 阶段：相对路径批量改写（单事务，标记同行提交）----
        from app.models.system_setting import SystemSetting

        db = SessionLocal()
        try:
            total = 0
            for table, col in _PATH_COLUMNS:
                for old, new in _LEGACY_PREFIX_MAP:
                    res = db.execute(
                        text(
                            f"UPDATE {table} SET {col} = :new || substr({col}, :len) "
                            f"WHERE {col} LIKE :old || '%'"
                        ),
                        {"new": new, "len": len(old) + 1, "old": old},
                    )
                    total += res.rowcount
            for old, new in (("logos/", AVATARS + "/"), ("avatars/", AVATARS + "/")):
                res = db.execute(
                    text(
                        "UPDATE system_settings SET value = :new || substr(value, :len) "
                        "WHERE key = 'site_logo_path' AND value LIKE :old || '%'"
                    ),
                    {"new": new, "len": len(old) + 1, "old": old},
                )
                total += res.rowcount
            res = db.execute(
                text(
                    "UPDATE system_settings SET value = 'ihub_bg/' || substr(value, :len) "
                    "WHERE key = 'login_bg_path' AND value LIKE 'bg/%'"
                ),
                {"len": len("bg/") + 1},
            )
            total += res.rowcount
            # 用户头像文件在文件阶段已改名（user_<uid>_<hex>.<ext> → ihub_user_avatars_<uid>.<ext>），
            # 前缀改写追不上文件名变化，这里按名字模式二次改写
            rows = db.execute(
                text("SELECT id, avatar_path FROM users WHERE avatar_path LIKE 'ihub_avatars/user_%'"),
            ).fetchall()
            for uid, rel in rows:
                m = re.match(r"^ihub_avatars/user_(\d+)_[0-9a-f]+\.(\w+)$", rel.replace("\\", "/"))
                if not m:
                    continue
                new_rel = f"{AVATARS}/ihub_user_avatars_{m.group(1)}.{m.group(2)}"
                db.execute(
                    text("UPDATE users SET avatar_path = :new WHERE id = :id"),
                    {"new": new_rel, "id": uid},
                )
                total += 1
            flag = db.get(SystemSetting, FLAG_KEY)
            if flag:
                flag.value = "1"
            else:
                db.add(SystemSetting(key=FLAG_KEY, value="1"))
            db.commit()
        except Exception:
            db.rollback()
            # DB 失败：把目录搬回去，保持 v1 一致状态
            for dst, src in reversed(journal):
                try:
                    if dst.is_dir():
                        dst.rename(src)
                    elif dst.is_file():
                        dst.rename(src)
                except OSError:
                    logger.exception("目录迁移回滚失败：%s → %s", dst, src)
            raise
        finally:
            db.close()

        logger.info("data 目录布局已迁移到 v2（ihub_ 前缀），改写路径 %s 处", total)
    except Exception:
        logger.exception("data 目录布局迁移失败")
        raise


def migrate_network_proxy() -> None:
    """影视旧 TMDB 代理字段 → 全局出站代理（一次性；旧键保留但代码不再读取）。"""
    from app.db.session import SessionLocal
    from app.models.system_setting import get_setting_db, set_setting

    db = SessionLocal()
    try:
        old = get_setting_db(db, "video_tmdb_proxy", "")
        cur = get_setting_db(db, "network_proxy", "")
        if old and not cur:
            set_setting("network_proxy", old)
            logger.info("已将影视 TMDB 代理迁移为全局出站代理")
    finally:
        db.close()
