"""qBittorrent 全局网络流量采样（1.5s 一个点，进程内存环形历史）。

qB WebUI 没有推送接口，transfer/info 的 dl_info_speed/up_info_speed 本身就是
约 1.5s 刷新一次的快照。这里用单线程 + 连接级 qB 客户端采样，所有用户共享同一份
历史，避免每个浏览器标签页各自去请求 qB。
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

from app.db.session import SessionLocal
from app.models.seed_connection import SeedConnection
from app.services.seed_service import qb_client

logger = logging.getLogger(__name__)

INTERVAL = 1.5
MAX_SAMPLES = 240  # 6 分钟
DEFAULT_LIMIT = 160  # 4 分钟

_LOCK = threading.Lock()
_TRAFFIC: dict[int, deque[tuple[int, int, int]]] = {}
_STOP = threading.Event()
_THREAD: threading.Thread | None = None
_LAST_LOG: dict[int, float] = {}


def _record(conn_id: int, info: dict) -> None:
    now = int(time.time() * 1000)
    down = int(info.get("dl_info_speed") or 0)
    up = int(info.get("up_info_speed") or 0)
    with _LOCK:
        buf = _TRAFFIC.setdefault(conn_id, deque(maxlen=MAX_SAMPLES))
        buf.append((now, down, up))


def _sample_connection(conn: SeedConnection) -> None:
    client = qb_client(conn)
    if client.cooldown_remaining() > 0:
        return
    try:
        _record(conn.id, client.transfer_info())
        _LAST_LOG.pop(conn.id, None)
    except Exception as e:
        now = time.time()
        if now - _LAST_LOG.get(conn.id, 0) >= 60:
            _LAST_LOG[conn.id] = now
            logger.warning("网络流量采样失败 conn=%s: %s", conn.id, e)


def _first_qb(db) -> SeedConnection | None:
    return (
        db.query(SeedConnection)
        .filter(
            SeedConnection.kind == "qbittorrent",
            SeedConnection.enabled.is_(True),
        )
        .order_by(SeedConnection.id.asc())
        .first()
    )


def _sample_once() -> None:
    db = SessionLocal()
    try:
        conn = _first_qb(db)
        if not conn:
            return
        _sample_connection(conn)
    finally:
        db.close()


def sample_now(conn: SeedConnection) -> None:
    """接口兜底：缓冲区为空时同步采一个点。"""
    _sample_connection(conn)


def snapshot(conn_id: int, limit: int = DEFAULT_LIMIT) -> list[dict]:
    with _LOCK:
        buf = _TRAFFIC.get(conn_id)
        rows = list(buf)[-limit:] if buf else []
    return [{"t": t, "down": down, "up": up} for t, down, up in rows]


def _loop() -> None:
    while not _STOP.is_set():
        try:
            _sample_once()
        except Exception:
            logger.exception("网络流量采样线程本轮异常")
        _STOP.wait(INTERVAL)


def start_worker() -> None:
    global _THREAD
    with _LOCK:
        if _THREAD and _THREAD.is_alive():
            return
    _STOP.clear()
    _THREAD = threading.Thread(target=_loop, name="ihub-seed-traffic", daemon=True)
    _THREAD.start()


def stop_worker() -> None:
    _STOP.set()
    with _LOCK:
        thread = _THREAD
    if thread and thread.is_alive():
        thread.join(timeout=3)


def sync_worker() -> None:
    """有启用的 qB 连接就确保采样线程已启动。

    线程一旦启动就常驻到进程退出；没有连接时每 1.5s 只做一次轻量 DB 查询后跳过，
    避免「停用→立即启用」时 join 超时导致两个线程/没有线程的竞态。
    """
    db = SessionLocal()
    try:
        has_qb = _first_qb(db) is not None
    finally:
        db.close()
    if has_qb:
        start_worker()
