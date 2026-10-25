"""种子转媒体状态机。

流程：
1. qB 改保存位置到 下载/电视|电影；
2. 清空标签/分类，写入 MOVIEPILOT + 转媒体；
3. worker 轮询 qB 的 转媒体 任务，查 MP 整理历史；
4. 按 download_hash，或 download_hash 为空时按源路径（src）匹配到
   status=true 的记录后，把 转媒体 改成 已转媒体。

不再依赖 qB 的 已整理 标签：真实 MP 整理成功后不一定追加该标签。

没有待处理任务时 worker 休眠；启动、转媒体动作、手动刷新会唤醒/扫描。
"""
from __future__ import annotations

import logging
import os
import threading
import time

from app.db.session import SessionLocal
from app.models.seed_connection import SeedConnection
from app.services.seed_common import SeedError, mp_transfer_matches, normalize_remote_path
from app.services.seed_service import invalidate_qb_list, mp_client, qb_client

logger = logging.getLogger(__name__)

PENDING_TAG = "转媒体"
DONE_TAG = "已转媒体"
MP_TAG = "MOVIEPILOT"

TV_PATH = os.environ.get("IHUB_SEED_TRANSFER_TV_PATH", "/media/下载/电视")
MOVIE_PATH = os.environ.get("IHUB_SEED_TRANSFER_MOVIE_PATH", "/media/下载/电影")
TARGETS = {"tv": TV_PATH, "movie": MOVIE_PATH}

POLL_SECONDS = 15
HISTORY_TTL = 30.0
HISTORY_PAGES = 5
HISTORY_COUNT = 200

_STOP = threading.Event()
_WAKE = threading.Event()
_THREAD: threading.Thread | None = None
_PENDING: set[str] = set()
_PENDING_LOCK = threading.Lock()
_HISTORY_CACHE: dict[int, tuple[float, list[dict]]] = {}
_HISTORY_LOCK = threading.Lock()


def _first_conn(db, kind: str) -> SeedConnection | None:
    return (
        db.query(SeedConnection)
        .filter(SeedConnection.kind == kind, SeedConnection.enabled.is_(True))
        .order_by(SeedConnection.sort_order.asc(), SeedConnection.id.asc())
        .first()
    )


def _tags(row: dict) -> set[str]:
    return {tag.strip() for tag in str(row.get("tags") or "").split(",") if tag.strip()}


def _is_brush(tags: set[str]) -> bool:
    return any(tag == "刷流" or tag.startswith("刷流-") for tag in tags)


def target_path(target: str) -> str:
    path = TARGETS.get(target)
    if not path:
        raise SeedError("未知的转媒体目标", 400)
    return path


def notify(hash_string: str) -> None:
    """转媒体动作成功后唤醒 worker，不必等下一轮扫描。"""
    if hash_string:
        with _PENDING_LOCK:
            _PENDING.add(hash_string.lower())
        _WAKE.set()


def _scan_pending() -> int:
    """只查 qB 的 转媒体 标签；不查 MP，不扫全库。"""
    with SessionLocal() as db:
        conn = _first_conn(db, "qbittorrent")
        if conn is None:
            with _PENDING_LOCK:
                _PENDING.clear()
            return 0
        try:
            rows = qb_client(conn).torrents(tag=PENDING_TAG)
        except Exception as e:  # noqa: BLE001 - 后台任务不能因上游抖动退出
            logger.warning("转媒体扫描 qB 失败：%s", e)
            return len(_PENDING)
    hashes = {str(row.get("hash") or "").lower() for row in rows if isinstance(row, dict)}
    with _PENDING_LOCK:
        _PENDING.clear()
        _PENDING.update(h for h in hashes if h)
        return len(_PENDING)


def scan_now() -> int:
    """手动刷新/启动时执行一次 qB 扫描；有任务才唤醒 worker。"""
    count = _scan_pending()
    if count:
        _WAKE.set()
    return count


def _history_rows(conn: SeedConnection) -> list[dict]:
    """读取 MP 整理历史（只保留匹配所需字段）；status=true 才算成功。

    download_hash 可能为空（刷流种子没有 MP 下载记录时真实发生过），
    因此同时保留 src 路径供 mp_transfer_matches 回退匹配。
    """
    now = time.time()
    with _HISTORY_LOCK:
        cached = _HISTORY_CACHE.get(conn.id)
        if cached and now - cached[0] < HISTORY_TTL:
            return cached[1]
    history: list[dict] = []
    try:
        client = mp_client(conn)
        for page in range(1, HISTORY_PAGES + 1):
            rows = client.transfer_history(page=page, count=HISTORY_COUNT)
            if not rows:
                break
            for row in rows:
                if not isinstance(row, dict):
                    continue
                src_item = row.get("src_fileitem")
                history.append({
                    "download_hash": str(row.get("download_hash") or "").strip().lower(),
                    "src": normalize_remote_path(
                        row.get("src")
                        or (src_item.get("path") if isinstance(src_item, dict) else "")
                    ),
                    "status": bool(row.get("status")),
                })
    except Exception as e:  # noqa: BLE001
        logger.warning("读取 MP 整理历史失败：%s", e)
        return []
    with _HISTORY_LOCK:
        _HISTORY_CACHE[conn.id] = (now, history)
    return history


def _poll_pending() -> None:
    with SessionLocal() as db:
        qb_conn = _first_conn(db, "qbittorrent")
        if qb_conn is None:
            return
        try:
            rows = qb_client(qb_conn).torrents(tag=PENDING_TAG)
        except Exception as e:  # noqa: BLE001
            logger.warning("转媒体轮询 qB 失败：%s", e)
            return
        row_map = {
            str(row.get("hash") or "").lower(): row
            for row in rows
            if isinstance(row, dict) and row.get("hash")
        }
        with _PENDING_LOCK:
            _PENDING.intersection_update(row_map)
        if not row_map:
            return
        mp_conn = _first_conn(db, "moviepilot")
        if mp_conn is None:
            logger.warning("有转媒体任务在等待 MP 整理，但未配置 MoviePilot 连接")
            return
        history = _history_rows(mp_conn)
        if not history:
            return
        qb = qb_client(qb_conn)
        for digest, row in row_map.items():
            matched_success = any(
                bool(entry.get("status"))
                and mp_transfer_matches(
                    entry,
                    digest=digest,
                    save_path=str(row.get("save_path") or ""),
                    name=str(row.get("name") or ""),
                    content_path=str(row.get("content_path") or ""),
                )
                for entry in history
            )
            if not matched_success:
                continue
            try:
                qb.remove_tags([digest], [PENDING_TAG])
                qb.add_tags([digest], [DONE_TAG])
            except Exception as e:  # noqa: BLE001
                logger.warning("转媒体完成标签更新失败 %s：%s", digest, e)
                continue
            with _PENDING_LOCK:
                _PENDING.discard(digest)
            # 标签使用情况变了：让筛选下拉与 qB 列表立即刷新，而不是等 30/5 秒缓存。
            invalidate_qb_list(qb_conn.id)
            logger.info("转媒体完成：%s", digest)


def _loop() -> None:
    try:
        scan_now()
    except Exception:  # noqa: BLE001
        logger.exception("转媒体 worker 启动扫描失败")
    while not _STOP.is_set():
        with _PENDING_LOCK:
            has_pending = bool(_PENDING)
        if not has_pending:
            _WAKE.wait(60)
            _WAKE.clear()
            continue
        try:
            _poll_pending()
        except Exception:  # noqa: BLE001
            logger.exception("转媒体 worker 检查失败")
        _WAKE.wait(POLL_SECONDS)
        _WAKE.clear()


def start_worker() -> None:
    global _THREAD
    if _THREAD and _THREAD.is_alive():
        return
    _STOP.clear()
    _THREAD = threading.Thread(target=_loop, name="ihub-seed-transfer", daemon=True)
    _THREAD.start()


def stop_worker() -> None:
    _STOP.set()
    _WAKE.set()
    if _THREAD and _THREAD.is_alive():
        _THREAD.join(timeout=2)


def convert(qb, torrent_hash: str, target: str) -> dict:
    """执行 qB 侧转媒体动作；MP 整理由后台 worker 继续跟踪。"""
    path = target_path(target)
    rows = qb.torrents(hashes=torrent_hash)
    if not rows:
        raise SeedError("种子不存在或已被删除", 404)
    row = rows[0]
    tags = _tags(row)
    if not _is_brush(tags):
        raise SeedError("只有刷流种子才能转媒体", 400)
    if DONE_TAG in tags:
        raise SeedError("该种子已经转过媒体", 400)
    try:
        progress = float(row.get("progress") or 0)
    except (TypeError, ValueError):
        progress = 0
    if progress < 0.999:
        raise SeedError("种子尚未下载完成，不能转媒体", 400)

    old_tags = sorted(tags)
    old_category = str(row.get("category") or "")
    qb.remove_tags([torrent_hash], old_tags)
    qb.set_category([torrent_hash], "")
    qb.add_tags([torrent_hash], [MP_TAG, PENDING_TAG])
    try:
        qb.set_location([torrent_hash], path)
    except Exception:
        # 改位置失败时尽量恢复原标签，避免任务停在“已移出刷流管理但没搬走”的状态。
        try:
            qb.remove_tags([torrent_hash], [MP_TAG, PENDING_TAG])
            qb.add_tags([torrent_hash], old_tags)
            qb.set_category([torrent_hash], old_category)
        except Exception as rollback_error:  # noqa: BLE001
            logger.warning("转媒体回滚标签失败 %s：%s", torrent_hash, rollback_error)
        raise
    notify(torrent_hash)
    return {"target": target, "path": path}
