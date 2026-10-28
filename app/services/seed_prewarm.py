"""种子发现/推荐缓存预热（每天 03:00 本地时间）。

为什么需要：MP 自身的推荐/探索接口有服务端缓存（首次 0.5~1.5s，之后 30~40ms），
但 iHub 的进程内缓存只有 5 分钟、进程重启还会全部丢失，于是每天第一个访客
往往要等十几个板块依次穿透 MP。这里在低峰期按前端真实请求参数把数据预热进
`cached()`，并落一份磁盘快照：进程重启后启动时读回，第一个访客也能秒开。

只预热「有数据」的板块：上游超时/空结果的板块不写缓存（避免把空页固化一天，
也让下次访问仍有机会重试）。预热只调 MP API，不碰站点搜索。
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path

from sqlalchemy.orm import Session

from urllib.parse import unquote

from app.core import data_dirs
from app.core.config import settings
from app.models.seed_connection import SeedConnection
from app.services import seed_covers
from app.services.seed_service import cache_set, mp_client, normalize_mp_media

logger = logging.getLogger(__name__)

# 与端点缓存 TTL 一致（见 seeds.py 的 mp_discover/mp_recommend）
PREWARM_TTL = 24 * 3600
PAGE_SIZE = 20
SNAPSHOT_DIR = Path(settings.DATA_DIR) / data_dirs.CACHE / "seed_prewarm"

# 推荐板块：与前端 RECOMMEND_SECTIONS 对齐（跳过 bangumi_calendar：上游常年挂起、懒加载由前端自取）
RECOMMEND_SOURCES = [
    "recommend/tmdb_trending",
    "recommend/douban_showing",
    "anilist/trending",
    "anilist/popular-this-season",
    "recommend/music_weekly",
    "recommend/music_douban",
    "recommend/tmdb_movies",
    "recommend/tmdb_tvs",
    "recommend/douban_movie_hot",
    "recommend/douban_tv_hot",
    "recommend/douban_tv_animation",
    "recommend/douban_movies",
    "recommend/douban_tvs",
    "recommend/douban_movie_top250",
    "recommend/douban_tv_weekly_chinese",
    "recommend/douban_tv_weekly_global",
]

# 探索首屏：各来源默认类型、无筛选（与前端首次进入时一致）；bangumi 上游超时返回空，不预热
DISCOVER_SOURCES = [
    "tmdb_movies",
    "tmdb_tvs",
    "douban_movies",
    "douban_tvs",
    "douban_music",
    "anilist",
    "musicbrainz",
]

_RUN_LOCK = threading.Lock()


def recommend_key(source: str) -> str:
    return f"mp:recommend:{source}:all:1:{PAGE_SIZE}"


def discover_key(source: str) -> str:
    return f"mp:discover:{source}:1:{PAGE_SIZE}:{sorted({}.items())}"


def _first_mp_conn(db: Session) -> SeedConnection | None:
    return (
        db.query(SeedConnection)
        .filter(SeedConnection.kind == "moviepilot", SeedConnection.enabled.is_(True))
        .order_by(SeedConnection.sort_order, SeedConnection.id)
        .first()
    )


def _snapshot_path(conn_id: int, key: str) -> Path:
    digest = hashlib.sha256(f"{conn_id}:{key}".encode("utf-8")).hexdigest()
    return SNAPSHOT_DIR / f"{digest}.json"


def _save_snapshot(conn_id: int, key: str, items: list, at: float) -> None:
    try:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        target = _snapshot_path(conn_id, key)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"conn": conn_id, "key": key, "at": at, "items": items}, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(target)
    except OSError as e:
        logger.warning("种子预热快照写入失败 key=%s: %s", key, e)


def _store(conn_id: int, key: str, items: list) -> None:
    at = time.time()
    cache_set(conn_id, key, items, at=at)
    _save_snapshot(conn_id, key, items, at)


def _cover_urls(items: list[dict]) -> list[str]:
    """从归一化条目里取出封面代理地址（仅挑 /seeds/cover?url= 形式，与端点同口径）。"""
    marker = "/api/v1/seeds/cover?url="
    out: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        value = str(item.get("poster") or "")
        if marker in value:
            out.append(unquote(value.split(marker, 1)[1]))
    return out


def prewarm_conn(conn: SeedConnection) -> tuple[int, int]:
    """预热一个 MP 连接，返回 (成功数, 跳过数)。"""
    client = mp_client(conn)
    ok = skipped = 0
    covers: list[str] = []
    for source in RECOMMEND_SOURCES:
        try:
            rows = client.recommend_section(source, page=1, count=PAGE_SIZE)
            items = [normalize_mp_media(r) for r in rows if isinstance(r, dict)]
            if items:
                _store(conn.id, recommend_key(source), items)
                covers.extend(_cover_urls(items))
                ok += 1
            else:
                skipped += 1
        except Exception as e:  # noqa: BLE001 单个板块失败不影响其它板块
            skipped += 1
            logger.info("推荐板块预热跳过 %s: %s", source, str(e)[:120])
    for source in DISCOVER_SOURCES:
        try:
            rows = client.discover_explore(source, page=1, count=PAGE_SIZE, params={})
            items = [normalize_mp_media(r) for r in rows if isinstance(r, dict)]
            if items:
                _store(conn.id, discover_key(source), items)
                covers.extend(_cover_urls(items))
                ok += 1
            else:
                skipped += 1
        except Exception as e:  # noqa: BLE001
            skipped += 1
            logger.info("探索来源预热跳过 %s: %s", source, str(e)[:120])
    # 顺手预热海报磁盘缓存（只拉 TMDB/豆瓣图 CDN，不碰 MP API）：首访图片直接命中本地文件
    if covers:
        seed_covers.prewarm(covers, limit=600, workers=6)
    return ok, skipped


def run_prewarm() -> None:
    """调度入口：低峰期把发现页数据预热进缓存（串行，避免给 MP 造成并发）。"""
    from app.db.session import SessionLocal

    if not _RUN_LOCK.acquire(blocking=False):
        logger.info("种子预热已在运行，跳过本次")
        return
    t0 = time.time()
    try:
        db = SessionLocal()
        try:
            conn = _first_mp_conn(db)
        finally:
            db.close()
        if conn is None:
            return
        ok, skipped = prewarm_conn(conn)
        logger.info(
            "种子发现缓存预热完成：成功 %s 个板块，跳过 %s 个，用时 %.1fs",
            ok, skipped, time.time() - t0,
        )
        _cleanup_snapshots()
    except Exception:  # noqa: BLE001 预热失败不影响业务
        logger.exception("种子发现缓存预热失败")
    finally:
        _RUN_LOCK.release()


def hydrate_from_disk() -> None:
    """启动时把 24h 内的预热快照读回内存缓存（进程重启后首个访客也能秒开）。"""
    if not SNAPSHOT_DIR.is_dir():
        return
    now = time.time()
    loaded = 0
    for path in SNAPSHOT_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            at = float(data.get("at") or 0)
            conn_id = int(data.get("conn") or 0)
            key = str(data.get("key") or "")
            items = data.get("items")
            if not conn_id or not key or not isinstance(items, list) or not items:
                continue
            if now - at >= PREWARM_TTL:
                continue
            cache_set(conn_id, key, items, at=at)
            loaded += 1
        except (OSError, ValueError, TypeError):
            continue
    if loaded:
        logger.info("已从磁盘恢复 %s 个种子发现缓存快照", loaded)


def _cleanup_snapshots(max_age: float = 7 * 24 * 3600) -> None:
    if not SNAPSHOT_DIR.is_dir():
        return
    cut = time.time() - max_age
    for path in SNAPSHOT_DIR.glob("*.json"):
        try:
            if path.stat().st_mtime < cut:
                path.unlink(missing_ok=True)
        except OSError:
            continue
