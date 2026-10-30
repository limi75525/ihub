"""data/ 缓存与孤儿文件清理（每日调度 + 设置页手动触发）。

策略（与目录布局 v2 配套，见 core/data_dirs.py）：
  ihub_cache/seed_covers/    mtime 超 60 天 → 删（下次访问自动重建；30 天 TTL 是新鲜期，
                             过期文件还能给上游失败兜底，60 天才清是保守值）
  ihub_media/video_covers/   tmdb.prune_cache 按库引用清理 + .part 残留清理（复用现有实现）
  ihub_cache/tmp/            条目 mtime 超 24 小时 → 删（分片上传残留）
  ihub_avatars/ ihub_nav_logos/ ihub_media/playlist_covers/
                             孤儿检测：不在 DB 引用集合且 mtime 超 7 天 → 删
不碰：ihub_media/books、ihub_transfer（回收站/用户清理覆盖）、
     ihub_attachments（消息保留期清理覆盖）。
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from app.core import data_dirs
from app.core.config import settings
from app.services import tmdb

logger = logging.getLogger(__name__)

JANITOR_LOCK = threading.Lock()
LAST_RUN_KEY = "janitor_last_run"

SEED_COVER_TTL = 60 * 24 * 3600
TMP_TTL = 24 * 3600
ORPHAN_GRACE = 7 * 24 * 3600


def _dir_stats(path: Path) -> tuple[int, int]:
    files = 0
    total = 0
    if not path.is_dir():
        return 0, 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                files += 1
                total += p.stat().st_size
        except OSError:
            continue
    return files, total


def _delete_expired(dir_path: Path, ttl: int, now: float) -> tuple[int, int]:
    deleted, freed = 0, 0
    if not dir_path.is_dir():
        return 0, 0
    for p in dir_path.iterdir():
        try:
            if p.is_file() and now - p.stat().st_mtime > ttl:
                size = p.stat().st_size
                p.unlink()
                deleted += 1
                freed += size
        except OSError:
            continue
    return deleted, freed


def _clean_tmp(dir_path: Path, now: float) -> tuple[int, int]:
    """临时区：文件直接按 TTL 删；子目录（分片会话）整体按 TTL 删。"""
    deleted, freed = 0, 0
    if not dir_path.is_dir():
        return 0, 0
    for p in dir_path.iterdir():
        try:
            if now - p.stat().st_mtime <= TMP_TTL:
                continue
            if p.is_dir():
                size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                shutil.rmtree(p, ignore_errors=True)
            else:
                size = p.stat().st_size
                p.unlink()
            deleted += 1
            freed += size
        except OSError:
            continue
    return deleted, freed


def _clean_orphans(dir_path: Path, referenced: set[str], now: float) -> tuple[int, int]:
    """孤儿检测：目录内文件不在 DB 引用集合（存的是 v2 相对路径）且超过宽限期 → 删。"""
    deleted, freed = 0, 0
    if not dir_path.is_dir():
        return 0, 0
    try:
        prefix = dir_path.resolve().relative_to(Path(settings.DATA_DIR).resolve()).as_posix()
    except ValueError:
        return 0, 0
    for p in dir_path.iterdir():
        try:
            if not p.is_file():
                continue
            rel = f"{prefix}/{p.name}"
            if rel in referenced:
                continue
            if now - p.stat().st_mtime <= ORPHAN_GRACE:
                continue
            size = p.stat().st_size
            p.unlink()
            deleted += 1
            freed += size
        except OSError:
            continue
    return deleted, freed


def _referenced(db) -> dict[str, set[str]]:
    from sqlalchemy import text

    def q(sql: str) -> set[str]:
        rows = db.execute(text(sql)).fetchall()
        return {
            data_dirs.translate_rel(r[0].replace("\\", "/"))
            for r in rows
            if r[0]
        }

    avatars = q("SELECT logo_path FROM logo_groups WHERE logo_path IS NOT NULL AND logo_path != ''")
    avatars |= q("SELECT logo_path FROM logo_rules WHERE logo_path IS NOT NULL AND logo_path != ''")
    avatars |= q("SELECT logo_path FROM sources WHERE logo_path IS NOT NULL AND logo_path != ''")
    avatars |= q("SELECT avatar_path FROM users WHERE avatar_path IS NOT NULL AND avatar_path != ''")
    avatars |= q("SELECT value FROM system_settings WHERE key = 'site_logo_path' AND value != ''")
    nav = q("SELECT logo_path FROM nav_links WHERE logo_path IS NOT NULL AND logo_path != ''")
    pl = q("SELECT cover_path FROM music_playlists WHERE cover_path IS NOT NULL AND cover_path != ''")
    return {"ihub_avatars": avatars, "ihub_nav_logos": nav, "ihub_media/playlist_covers": pl}


def run_janitor() -> dict:
    """跑一轮清理，返回统计并写入 janitor_last_run；并发调用时返回 skipped。"""
    if not JANITOR_LOCK.acquire(blocking=False):
        return {"skipped": True}
    detail: dict[str, dict[str, int]] = {}
    try:
        return _run_janitor_locked(detail)
    except Exception as e:
        from app.services import notify_service

        notify_service.background_notify_admins(
            type="service_failed",
            title="每日清理任务失败",
            body=f"每日清理任务异常：{str(e)[:300]}",
            dedup_key=f"janitor:{int(time.time() // 86400)}",
        )
        raise
    finally:
        JANITOR_LOCK.release()


def _run_janitor_locked(detail: dict) -> dict:
    now = time.time()
    root = Path(settings.DATA_DIR)
    n, b = _delete_expired(root / data_dirs.SEED_COVERS, SEED_COVER_TTL, now)
    detail["seed_covers"] = {"files": n, "bytes": b}
    n, b = _clean_tmp(root / data_dirs.TMP, now)
    detail["tmp"] = {"files": n, "bytes": b}

    db = None
    from sqlalchemy import text

    from app.db.session import SessionLocal

    try:
        db = SessionLocal()
        # 影视 TMDB 缓存：按库引用清理
        rows = db.execute(
            text("SELECT tmdb_id, series_tmdb_id FROM video_items")
        ).fetchall()
        valid = {
            ("movie", r[0]) for r in rows if r[0]
        } | {
            ("tv", r[1]) for r in rows if r[1]
        }
        removed = tmdb.prune_cache(root / data_dirs.VIDEO_COVERS, valid)
        detail["video_covers"] = {"files": removed, "bytes": 0}
        # 孤儿检测
        refs = _referenced(db)
    finally:
        db.close()
    for rel_dir, referenced in refs.items():
        n, b = _clean_orphans(root / rel_dir, referenced, now)
        detail[rel_dir] = {"files": n, "bytes": b}

    # PT 站点离线巡检：全部离线时通知管理员（每天最多一次，dedup 兜底）
    try:
        from app.db.session import SessionLocal as _Sess
        from app.models.seed_connection import SeedConnection
        from app.services.seed_service import mp_client

        _db2 = _Sess()
        try:
            _conn = (
                _db2.query(SeedConnection)
                .filter(SeedConnection.kind == "moviepilot", SeedConnection.enabled.is_(True))
                .order_by(SeedConnection.id.asc())
                .first()
            )
            if _conn is not None:
                _stats = mp_client(_conn).site_statistics()
                _total = len(_stats)
                # 与 seeds._site_status 同口径：v3 的 statistic 没有 status 字段，
                # 改用「最近一次访问成功（lst_state==0）」判定；缺 lst_state 的老数据
                # 按 fail < success*10 粗判。之前按 status 判会永远 0/全离线误报。
                _ok = 0
                for s in _stats:
                    if not isinstance(s, dict):
                        continue
                    lst = s.get("lst_state")
                    if lst is not None:
                        if str(lst) == "0":
                            _ok += 1
                        continue
                    try:
                        ok_cnt = int(s.get("success") or 0)
                        bad_cnt = int(s.get("fail") or 0)
                    except (TypeError, ValueError):
                        continue
                    if ok_cnt > 0 and bad_cnt < ok_cnt * 10:
                        _ok += 1
                if _total > 0 and _ok == 0:
                    from app.services import notify_service

                    notify_service.notify_admins(
                        _db2,
                        type="site_offline",
                        title="PT 站点访问异常",
                        body=(
                            f"MoviePilot 的 {_total} 个站点最近一次访问全部失败，搜索与刷流可能不可用。"
                            "请检查站点 Cookie 有效性与网络可达性。"
                        ),
                        link="#/seeds?tab=sites",
                        dedup_key=f"site-offline:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                    )
        finally:
            _db2.close()
    except Exception:
        logger.exception("PT 站点离线巡检失败")

    files = sum(d["files"] for d in detail.values())
    freed = sum(d["bytes"] for d in detail.values())
    result = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": files,
        "bytes": freed,
        "detail": detail,
    }
    try:
        from app.models.system_setting import set_setting

        set_setting(LAST_RUN_KEY, json.dumps(result, ensure_ascii=False))
    except Exception:
        logger.exception("写入 janitor_last_run 失败")
    logger.info("定期清理完成：删除 %s 个文件，释放 %.1f MB", files, freed / 1048576)
    return result


def storage_overview() -> dict:
    """设置页「存储占用」数据：各目录大小 + 数据库体积 + 上次清理结果。"""
    root = Path(settings.DATA_DIR)

    def stat(rel: str) -> dict:
        files, total = _dir_stats(root / rel)
        return {"dir": rel, "files": files, "bytes": total}

    groups = [
        {"label": "书架书籍", "item": stat(data_dirs.BOOKS)},
        {"label": "书籍封面", "item": stat(data_dirs.BOOK_COVERS)},
        {"label": "音乐封面", "item": stat(data_dirs.MUSIC_COVERS)},
        {"label": "影视 TMDB 缓存", "item": stat(data_dirs.VIDEO_COVERS)},
        {"label": "歌单封面", "item": stat(data_dirs.PLAYLIST_COVERS)},
        {"label": "头像库与用户头像", "item": stat(data_dirs.AVATARS)},
        {"label": "导航 Logo", "item": stat(data_dirs.NAV_LOGOS)},
        {"label": "邮件附件", "item": stat(data_dirs.ATTACHMENTS)},
        {"label": "快传与文件库", "item": stat(data_dirs.TRANSFER)},
        {"label": "种子封面缓存", "item": stat(data_dirs.SEED_COVERS)},
        {"label": "上传临时区", "item": stat(data_dirs.TMP)},
    ]
    db_path = root / "ihub.db"
    db_bytes = db_path.stat().st_size if db_path.is_file() else 0
    last = None
    raw = ""
    try:
        from app.models.system_setting import get_setting

        raw = get_setting(LAST_RUN_KEY, "")
        last = json.loads(raw) if raw else None
    except Exception:
        last = None
    return {"items": groups, "db_bytes": db_bytes, "last_run": last}
