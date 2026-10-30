"""种子模块服务层：连接客户端、缓存、可见范围与上游数据归一化。"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_text
from app.models.seed_connection import SeedConnection
from app.models.user import User
from app.services import tmdb
from app.services.moviepilot import MpClient
from app.services.seed_covers import proxy_url
from app.services.qbittorrent import QbClient
from app.services.seed_common import (
    SeedError,
    mp_transfer_matches,
    normalize_remote_path,
)

ALL_TABS = ["download", "subscription", "search", "discover", "sites", "brush"]

logger = logging.getLogger(__name__)

# 缓存：单 worker + 短 TTL；只缓存成功结果，错误让前端看到真实状态
_CACHE: dict[tuple[int, str], tuple[float, Any]] = {}
_CACHE_LOCK = threading.Lock()
_CLIENTS: dict[int, tuple[str, Any]] = {}
_CLIENTS_LOCK = threading.Lock()

# qB 任务 hash -> MP 下载历史里的媒体摘要；只在种子下载页使用。
# 首次进入下载页拉一次；24 小时内轮询直接用缓存，过期或手动刷新（fresh）才重拉。
_DOWNLOAD_META_TTL = 24 * 3600
_DOWNLOAD_META_PAGES = 3
_DOWNLOAD_META_COUNT = 200
_DOWNLOAD_META: dict[int, tuple[float, dict[str, dict]]] = {}
_DOWNLOAD_META_LOCK = threading.Lock()
# MP 整理历史里的封面：刷流种子没有下载历史，转媒体成功后从这里补封面（同样 24h）。
_TRANSFER_META_TTL = 24 * 3600
_TRANSFER_META_PAGES = 2
_TRANSFER_META_COUNT = 200
_TRANSFER_META: dict[int, tuple[float, list[dict]]] = {}
_TRANSFER_META_LOCK = threading.Lock()
# 详情抽屉的媒体元数据（标题/封面/宽幅背景），按种子 hash 缓存；静态信息，长缓存。
_DETAIL_MEDIA_TTL = 24 * 3600
_DETAIL_MEDIA: dict[tuple[int, str], tuple[float, dict]] = {}
_DETAIL_MEDIA_LOCK = threading.Lock()
_HISTORY_SCAN_PAGES = 5
_HISTORY_SCAN_COUNT = 200
_TRANSFER_TAGS = {"转媒体", "已转媒体", "已整理"}


def _client_key(conn: SeedConnection, secret: str) -> str:
    return "|".join(
        [
            conn.kind,
            conn.base_url,
            conn.username or "",
            conn.auth_mode or "",
            "1" if conn.verify_tls else "0",
            secret,
        ]
    )


def _secret(conn: SeedConnection) -> str:
    if not conn.secret_cipher:
        return ""
    value = decrypt_text(conn.secret_cipher)
    if value is None:
        raise HTTPException(500, "连接密钥无法解密，请重新保存该连接")
    return value


def qb_client(conn: SeedConnection, *, fresh: bool = False) -> QbClient:
    """连接级单例：API、测试连接、事件线程必须共用同一个 qB 会话。

    qB 的 SID 会随新登录轮换；并发创建多个客户端会互相踢下线，
    表现为「登录成功但随后所有接口 403」。创建也要持锁，避免竞态。
    fresh=True 供手动“测试连接”强制换一个新客户端，绕过失败冷却；
    测试成功后新客户端留在缓存里，事件线程继续复用它。
    """
    secret = _secret(conn)
    key = _client_key(conn, secret)
    with _CLIENTS_LOCK:
        cached = _CLIENTS.get(conn.id)
        if not fresh and cached and cached[0] == key:
            return cached[1]
        client = QbClient(
            conn.base_url,
            username=conn.username or "",
            password=secret,
            auth_mode=conn.auth_mode or "password",
            verify_tls=bool(conn.verify_tls),
        )
        _CLIENTS[conn.id] = (key, client)
        return client


def mp_client(conn: SeedConnection, *, fresh: bool = False) -> MpClient:
    """MP 连接级单例（与 qB 同一套防并发创建逻辑）。"""
    secret = _secret(conn)
    key = _client_key(conn, secret)
    with _CLIENTS_LOCK:
        cached = _CLIENTS.get(conn.id)
        if not fresh and cached and cached[0] == key:
            return cached[1]
        auth_mode = conn.auth_mode or "api_token"
        client = MpClient(
            conn.base_url,
            api_token=secret if auth_mode == "api_token" else "",
            username=conn.username or "",
            password=secret if auth_mode == "password" else "",
            auth_mode=auth_mode,
            verify_tls=bool(conn.verify_tls),
        )
        _CLIENTS[conn.id] = (key, client)
        return client


def attach_download_media(conn: SeedConnection, items: list[dict], *, refresh: bool = False) -> None:
    """给 qB 任务补 MP 下载历史里的媒体摘要（海报/媒体名/年份/站点）。

    历史只覆盖经过 MP 下载链的任务；刷流、辅种等直接写下载器的任务没有记录，
    前端会回退到首字渐变占位。任何 MP 异常都不能影响 qB 列表本身。

    **24 小时缓存**：首次进入下载页/每日过期后拉一次，5 秒轮询直接用缓存、不再打 MP；
    手动刷新（refresh=True）立即重拉。新任务的封面可能要到下次刷新才出现。
    """
    hashes = {
        str(item.get("hash") or "").lower()
        for item in items
        if isinstance(item, dict) and item.get("hash")
    }
    if not hashes:
        return
    now = time.time()
    with _DOWNLOAD_META_LOCK:
        cached = _DOWNLOAD_META.get(conn.id)
    if not refresh and cached is not None and now - cached[0] < _DOWNLOAD_META_TTL:
        mapping = cached[1]
    else:
        previous = cached[1] if cached else {}
        mapping = None

    if mapping is None:
        fresh: dict[str, dict] = {}
        try:
            logger.info("种子下载页：拉取 MP 下载历史（%s 页）补全封面", _DOWNLOAD_META_PAGES)
            client = mp_client(conn)
            for page in range(1, _DOWNLOAD_META_PAGES + 1):
                rows = client.download_history(page=page, count=_DOWNLOAD_META_COUNT)
                if not rows:
                    break
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    digest = str(row.get("download_hash") or "").lower()
                    if not digest or digest in fresh:
                        continue
                    poster = str(row.get("poster") or "").strip()
                    if not poster.startswith(("http://", "https://")):
                        poster = ""
                    summary = {
                        "media_title": str(row.get("title") or "").strip(),
                        "media_year": str(row.get("year") or "").strip(),
                        "media_site": str(row.get("torrent_site") or "").strip(),
                        "media_poster": poster,
                    }
                    proxied = proxy_url(poster) if poster else None
                    if proxied:
                        summary["media_poster"] = proxied
                        summary["media_poster_fallback"] = poster
                    if any(summary.values()):
                        fresh[digest] = summary
        except Exception as e:  # noqa: BLE001 - 封面是增强信息，不能拖垮 qB 列表
            logger.debug("读取 MoviePilot 下载历史失败：%s", e)
            fresh = previous
        with _DOWNLOAD_META_LOCK:
            _DOWNLOAD_META[conn.id] = (now, fresh)
        mapping = fresh

    for item in items:
        if not isinstance(item, dict):
            continue
        summary = mapping.get(str(item.get("hash") or "").lower())
        if summary:
            item.update(summary)

    # 刷流种子没有 MP 下载历史；转媒体完成后从 MP 整理历史补封面。
    transfer_items = [
        item
        for item in items
        if isinstance(item, dict)
        and not item.get("media_poster")
        and any(tag in _TRANSFER_TAGS for tag in item.get("tags") or [])
    ]
    if not transfer_items:
        return
    now = time.time()
    with _TRANSFER_META_LOCK:
        cached = _TRANSFER_META.get(conn.id)
    if not refresh and cached is not None and now - cached[0] < _TRANSFER_META_TTL:
        transfer_entries = cached[1]
    else:
        transfer_entries = None
    if transfer_entries is None:
        previous = cached[1] if cached else []
        fresh_entries: list[dict] = []
        seen: set[tuple[str, str]] = set()
        try:
            logger.info("种子下载页：拉取 MP 整理历史（%s 页）补全转媒体封面", _TRANSFER_META_PAGES)
            client = mp_client(conn)
            for page in range(1, _TRANSFER_META_PAGES + 1):
                rows = client.transfer_history(page=page, count=_TRANSFER_META_COUNT)
                if not rows:
                    break
                for row in rows:
                    if not isinstance(row, dict) or not bool(row.get("status")):
                        continue
                    src_item = row.get("src_fileitem")
                    digest = str(row.get("download_hash") or "").strip().lower()
                    src = normalize_remote_path(
                        row.get("src")
                        or (src_item.get("path") if isinstance(src_item, dict) else "")
                    )
                    marker = (digest, src)
                    if (not digest and not src) or marker in seen:
                        continue
                    seen.add(marker)
                    poster = str(row.get("image") or "").strip()
                    if not poster.startswith(("http://", "https://")):
                        poster = ""
                    summary = {
                        "media_title": str(row.get("title") or "").strip(),
                        "media_year": str(row.get("year") or "").strip(),
                        "media_poster": poster,
                    }
                    proxied = proxy_url(poster) if poster else None
                    if proxied:
                        summary["media_poster"] = proxied
                        summary["media_poster_fallback"] = poster
                    if any(summary.values()):
                        fresh_entries.append({
                            "download_hash": digest,
                            "src": src,
                            "summary": summary,
                        })
        except Exception as e:  # noqa: BLE001 - 封面是增强信息，不能拖垮 qB 列表
            logger.debug("读取 MoviePilot 整理历史失败：%s", e)
            fresh_entries = previous
        with _TRANSFER_META_LOCK:
            _TRANSFER_META[conn.id] = (now, fresh_entries)
        transfer_entries = fresh_entries
    for item in transfer_items:
        for entry in transfer_entries:
            if mp_transfer_matches(
                entry,
                digest=str(item.get("hash") or ""),
                save_path=str(item.get("save_path") or ""),
                name=str(item.get("name") or ""),
                content_path=str(item.get("content_path") or ""),
            ):
                item.update(entry["summary"])
                break


def invalidate_qb_list(conn_id: int) -> None:
    """清 qB 列表/标签筛选缓存与详情媒体缓存，保留已登录客户端。"""
    with _CACHE_LOCK:
        for key in [
            k
            for k in _CACHE
            if k[0] == conn_id and (k[1].startswith("qb:list:") or k[1] == "qb:tags")
        ]:
            _CACHE.pop(key, None)
    with _DETAIL_MEDIA_LOCK:
        for key in [k for k in _DETAIL_MEDIA if k[0] == conn_id]:
            _DETAIL_MEDIA.pop(key, None)


def invalidate_connection(conn_id: int) -> None:
    with _CLIENTS_LOCK:
        _CLIENTS.pop(conn_id, None)
    with _CACHE_LOCK:
        for key in [k for k in _CACHE if k[0] == conn_id]:
            _CACHE.pop(key, None)
    with _DOWNLOAD_META_LOCK:
        _DOWNLOAD_META.pop(conn_id, None)
    with _TRANSFER_META_LOCK:
        _TRANSFER_META.pop(conn_id, None)
    with _DETAIL_MEDIA_LOCK:
        for key in [k for k in _DETAIL_MEDIA if k[0] == conn_id]:
            _DETAIL_MEDIA.pop(key, None)


def clear_all_cache() -> None:
    with _CLIENTS_LOCK:
        _CLIENTS.clear()
    with _CACHE_LOCK:
        _CACHE.clear()
    with _DOWNLOAD_META_LOCK:
        _DOWNLOAD_META.clear()
    with _TRANSFER_META_LOCK:
        _TRANSFER_META.clear()
    with _DETAIL_MEDIA_LOCK:
        _DETAIL_MEDIA.clear()


# media-detail 这类按媒体 id 展开的 key 无界，满员时按写入时间淘汰最旧的四分之一
_CACHE_MAX_ENTRIES = 800
# 同 key 单飞锁：缓存过期瞬间多个页面/多个请求同时打进来时，只放一个请求上游，
# 其余等在锁上拿刚写入的结果（MoviePilot 在 NAS 上并发一多就拒绝连接，不能让它吃并发陡峰）。
_CACHE_LOCKS: dict[tuple[int, str], threading.RLock] = {}
_CACHE_LOCKS_GUARD = threading.Lock()


def _cache_key_lock(cache_key: tuple[int, str]) -> threading.RLock:
    with _CACHE_LOCKS_GUARD:
        lock = _CACHE_LOCKS.get(cache_key)
        if lock is None:
            lock = threading.RLock()
            _CACHE_LOCKS[cache_key] = lock
        return lock


def cached(conn_id: int, key: str, ttl: float, loader, *, force: bool = False) -> Any:
    """连接级内存缓存；force=True 跳过读取但仍回写（种子页手动刷新的旁路）。

    同一 key 的并发未命中会串行化：第一个请求回源，其余等它写缓存后直接复用，
    避免「缓存刚过期时 N 个请求一起穿透上游」。force=True 仍会回源，但同样排队。
    """
    cache_key = (conn_id, key)
    if not force:
        with _CACHE_LOCK:
            hit = _CACHE.get(cache_key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
    with _cache_key_lock(cache_key):
        if not force:
            # 等锁期间可能已经被别的线程刷新过，二次确认避免重复回源
            with _CACHE_LOCK:
                hit = _CACHE.get(cache_key)
                if hit and time.time() - hit[0] < ttl:
                    return hit[1]
        value = loader()
        with _CACHE_LOCK:
            if len(_CACHE) >= _CACHE_MAX_ENTRIES:
                oldest = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[: _CACHE_MAX_ENTRIES // 4]
                for stale_key, _ in oldest:
                    _CACHE.pop(stale_key, None)
            _CACHE[cache_key] = (time.time(), value)
        return value


def cache_drop(conn_id: int, key: str) -> None:
    """主动失效一条连接级缓存：写操作成功后调用，让下一次读取重查上游。"""
    with _CACHE_LOCK:
        _CACHE.pop((conn_id, key), None)


def cache_set(conn_id: int, key: str, value: Any, *, at: float | None = None) -> None:
    """直接写入一条连接级缓存（预热/快照回填用；at 可指定数据产生时间）。"""
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX_ENTRIES:
            oldest = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[: _CACHE_MAX_ENTRIES // 4]
            for stale_key, _ in oldest:
                _CACHE.pop(stale_key, None)
        _CACHE[(conn_id, key)] = (time.time() if at is None else at, value)


# ---- 可见范围 ----

def allowed_tabs(user: User, db: Session) -> set[str]:
    """2026-10-25 用户拍板：种子模块固定管理员可见、普通用户不可见（可见范围设置项已移除）。"""
    if user.role == "admin":
        return set(ALL_TABS)
    return set()


def require_tab(user: User, db: Session, tab: str) -> None:
    if user.role == "admin":
        return
    if tab not in allowed_tabs(user, db):
        raise HTTPException(403, "当前账号没有查看该种子栏目的权限")


def connection_out(conn: SeedConnection, *, admin: bool = False) -> dict:
    out = {
        "id": conn.id,
        "kind": conn.kind,
        "name": conn.name,
        "enabled": bool(conn.enabled),
        "ok": bool(conn.last_ok_at) and not conn.last_error,
        "version": conn.server_version or "",
        "last_ok_at": conn.last_ok_at.isoformat() if conn.last_ok_at else None,
        "last_error": conn.last_error or "",
        "secret_set": bool(conn.secret_cipher),
    }
    if admin:
        out.update(
            {
                "base_url": conn.base_url,
                "username": conn.username or "",
                "auth_mode": conn.auth_mode or "",
                "verify_tls": bool(conn.verify_tls),
                "poll_interval": conn.poll_interval or 0,
            }
        )
    return out


def connection_status(conn: SeedConnection) -> dict:
    return {
        "kind": conn.kind,
        "name": conn.name,
        "enabled": bool(conn.enabled),
        "ok": bool(conn.last_ok_at) and not conn.last_error,
        "version": conn.server_version or "",
        "last_error": conn.last_error or "",
    }


# ---- QB 归一化 ----

_QB_STATE_LABELS = {
    "downloading": "下载中",
    "stalledDL": "等待下载",
    "metaDL": "获取元数据",
    "forcedDL": "强制下载",
    "queuedDL": "排队中",
    "allocating": "分配空间",
    "checkingDL": "校验中",
    "uploading": "做种中",
    # qB WebUI 把「做种但暂无连接」也归为做种中，不单独显示「等待做种」
    "stalledUP": "做种中",
    "forcedUP": "强制做种",
    "queuedUP": "排队做种",
    "checkingUP": "校验中",
    "pausedDL": "已暂停",
    "pausedUP": "已暂停",
    "stoppedDL": "已暂停",
    "stoppedUP": "已暂停",
    "checkingResumeData": "校验恢复数据",
    "moving": "移动中",
    "error": "错误",
    "missingFiles": "文件缺失",
    "unknown": "未知",
}
_QB_DOWNLOADING = {
    "downloading", "stalledDL", "metaDL", "forcedDL", "queuedDL",
    "allocating", "checkingDL", "checkingResumeData",
}
_QB_SEEDING = {
    "uploading", "stalledUP", "forcedUP", "queuedUP", "checkingUP",
}
_QB_PAUSED = {"pausedDL", "pausedUP", "stoppedDL", "stoppedUP"}
_QB_BAD = {"error", "missingFiles", "unknown", "moving"}


def qb_state_label(state: str) -> str:
    return _QB_STATE_LABELS.get(state, state or "未知")


def _safe_tracker_url(url: str | None) -> str:
    """qB 的 tracker 地址可能带 PT passkey；只回 scheme+host+path，丢弃 query。"""
    raw = (url or "").strip()
    if not raw:
        return ""
    # qB 的 DHT/PeX/LSD 伪 tracker 不是 URL，但需要在 Tracker 表里原样显示
    if re.fullmatch(r"\*\* \[[A-Za-z0-9 _-]{1,24}\] \*\*", raw):
        return raw
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


_SECRET_QUERY_KEYS = {"passkey", "torrent_pass", "torrent_passkey", "authkey", "auth_key"}


def _safe_public_url(url: str | None) -> str:
    """MP/PT 页面地址：保留普通查询参数，但把 passkey 类参数值替换为 ***。"""
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    try:
        query = parse_qsl(parsed.query, keep_blank_values=True)
    except ValueError:
        query = []
    safe_query = urlencode(
        [(k, "***" if k.lower() in _SECRET_QUERY_KEYS else v) for k, v in query],
        doseq=True,
    )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, safe_query, parsed.fragment))


def normalize_qb_torrent(t: dict) -> dict:
    state = str(t.get("state") or "")
    size = int(t.get("size") or 0)
    total_size = int(t.get("total_size") or size)
    progress = float(t.get("progress") or 0)
    tags_raw = str(t.get("tags") or "")
    return {
        "hash": str(t.get("hash") or ""),
        "name": str(t.get("name") or ""),
        "state": state,
        "state_label": qb_state_label(state),
        "progress": max(0.0, min(1.0, progress)),
        "size": size,
        "total_size": total_size,
        "downloaded": int(total_size * progress) if total_size else int(t.get("downloaded") or 0),
        "amount_left": int(t.get("amount_left") or 0),
        "dlspeed": int(t.get("dlspeed") or 0),
        "upspeed": int(t.get("upspeed") or 0),
        "eta": int(t.get("eta") or 0) if int(t.get("eta") or 0) < 8640000 else 0,
        "ratio": float(t.get("ratio") or 0),
        "category": str(t.get("category") or ""),
        "tags": [x.strip() for x in tags_raw.split(",") if x.strip()],
        "added_on": int(t.get("added_on") or 0),
        "completion_on": int(t.get("completion_on") or 0),
        "save_path": str(t.get("save_path") or ""),
        "content_path": str(t.get("content_path") or ""),
        "tracker": _safe_tracker_url(t.get("tracker")),
        "num_seeds": int(t.get("num_seeds") or 0),
        "num_leechs": int(t.get("num_leechs") or 0),
        "time_active": int(t.get("time_active") or 0),
        "seeding_time": int(t.get("seeding_time") or 0),
    }


def normalize_qb_summary(transfer: dict, maindata: dict) -> dict:
    server = maindata.get("server_state") or {}
    torrents = maindata.get("torrents") or {}
    counts = {
        "downloading": 0, "seeding": 0, "completed": 0,
        "paused": 0, "error": 0, "total": 0,
    }
    if isinstance(torrents, dict):
        counts["total"] = len(torrents)
        for row in torrents.values():
            state = str((row or {}).get("state") or "")
            try:
                progress = float((row or {}).get("progress") or 0)
                amount_left = int((row or {}).get("amount_left") or 0)
            except (TypeError, ValueError):
                progress, amount_left = 0, 1
            is_completed = (
                progress >= 1
                and amount_left <= 0
                and state not in _QB_DOWNLOADING
                and state not in _QB_BAD
            )
            if is_completed:
                counts["completed"] += 1
            if state in _QB_DOWNLOADING:
                counts["downloading"] += 1
            elif state in _QB_SEEDING:
                counts["seeding"] += 1
            elif state in _QB_PAUSED:
                counts["paused"] += 1
            elif state in _QB_BAD:
                counts["error"] += 1
    # qB 只提供磁盘剩余空间，没有总容量；用「种子已落盘大小 + 剩余空间」估算可用池总量。
    used_space = 0
    if isinstance(torrents, dict):
        for row in torrents.values():
            if not isinstance(row, dict):
                continue
            try:
                size = int(row.get("total_size") or row.get("size") or 0)
                left = int(row.get("amount_left") or 0)
            except (TypeError, ValueError):
                continue
            used_space += max(0, size - left)
    free_space = int(server.get("free_space_on_disk") or 0)
    return {
        "download_speed": int(transfer.get("dl_info_speed") or server.get("dl_info_speed") or 0),
        "upload_speed": int(transfer.get("up_info_speed") or server.get("up_info_speed") or 0),
        "downloaded": int(transfer.get("dl_info_data") or server.get("dl_info_data") or 0),
        "uploaded": int(transfer.get("up_info_data") or server.get("up_info_data") or 0),
        "free_space": free_space,
        "used_space": used_space,
        "total_space": used_space + free_space,
        "connection_status": str(server.get("connection_status") or ""),
        **counts,
    }


def normalize_qb_detail(properties: dict, files: list, trackers: list, peers: dict) -> dict:
    files_out = []
    for f in files:
        if not isinstance(f, dict):
            continue
        files_out.append(
            {
                "name": str(f.get("name") or ""),
                "size": int(f.get("size") or 0),
                "progress": float(f.get("progress") or 0),
                "priority": int(f.get("priority") or 0),
                "is_seed": bool(f.get("is_seed")),
            }
        )
    trackers_out = []
    for t in trackers:
        if not isinstance(t, dict):
            continue
        trackers_out.append(
            {
                "url": _safe_tracker_url(t.get("url")),
                "tier": int(t.get("tier") if t.get("tier") is not None else 0),
                "status": int(t.get("status") or 0),
                "message": str(t.get("msg") or ""),
                "peers": int(t.get("num_peers") or 0),
                "seeds": int(t.get("num_seeds") or 0),
                "leeches": int(t.get("num_leeches") or 0),
                "downloaded": int(t.get("num_downloaded") or 0),
            }
        )
    return {
        "properties": {
            k: properties.get(k)
            for k in (
                "hash", "name", "save_path", "creation_date", "piece_size",
                "pieces_num", "pieces_have",
                "total_size", "total_wasted", "total_downloaded", "total_uploaded",
                "up_speed", "dl_speed",
                "time_elapsed", "seeding_time", "eta", "share_ratio",
                "addition_date", "completion_date", "comment", "created_by",
            )
            if k in properties
        },
        "files": files_out,
        "trackers": trackers_out,
        "peers": peers if isinstance(peers, dict) else {},
    }


# ---- MP 归一化 ----

_MP_TYPE_MAP = {
    "movie": "movie", "电影": "movie",
    "tv": "tv", "电视剧": "tv", "剧集": "tv",
    "music": "music", "音乐": "music",
}


def mp_type(value: Any) -> str:
    return _MP_TYPE_MAP.get(str(value or "").strip(), str(value or "").strip() or "unknown")


def normalize_mp_subscription(item: dict) -> dict:
    mtype = mp_type(item.get("type") or item.get("mtype"))
    total_episode = int(item.get("total_episode") or 0)
    lack_episode = int(item.get("lack_episode") or 0)
    completed_episode = item.get("completed_episode")
    if completed_episode is None and total_episode:
        completed_episode = max(total_episode - lack_episode, 0)
    state = str(item.get("state") or "")
    state_label = {"N": "新建", "R": "订阅中", "P": "待定", "S": "已暂停"}.get(state, state or "未知")
    poster = str(item.get("poster") or item.get("image") or "").strip()
    return {
        "id": item.get("id"),
        "type": mtype,
        "name": str(item.get("name") or item.get("title") or ""),
        "year": str(item.get("year") or ""),
        "season": item.get("season"),
        "poster": (proxy_url(poster) or poster) if poster else "",
        "state": state,
        "state_label": state_label,
        "total_episode": total_episode,
        "lack_episode": lack_episode,
        "completed_episode": completed_episode,
        "total_tracks": int(item.get("total_tracks") or 0),
        "completed_tracks": item.get("completed_tracks"),
        "music_type": item.get("music_type") or "",
        "last_update": item.get("last_update") or "",
        "username": item.get("username") or "",
        "sites": item.get("sites") or [],
    }


def _first(item: dict, *keys, default=""):
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return default


def normalize_mp_site(site: dict, stats: dict | None = None, *, include_account: bool = True) -> dict:
    stats = stats or {}
    out = {
        "id": site.get("id"),
        "name": str(_first(site, "name", "site_name", default="")),
        "domain": str(_first(site, "domain", "site_domain", default="")),
        "url": _safe_public_url(_first(site, "url", "site_url", default="")),
        "active": bool(site.get("is_active", site.get("active", True))),
        "priority": site.get("pri"),
        "public": bool(site.get("public")),
        "downloader": site.get("downloader") or "",
    }
    if include_account:
        out.update(
            {
                "uploaded": int(_first(stats, "upload", "uploaded", "uploaded_bytes", default=0) or 0),
                "downloaded": int(_first(stats, "download", "downloaded", "downloaded_bytes", default=0) or 0),
                "ratio": float(_first(stats, "ratio", "share_ratio", default=0) or 0),
                "user_level": str(_first(stats, "user_level", "level", "user_level_name", default="")),
                "bonus": _first(stats, "bonus", "seedbonus", "bonus_point", default=0),
                "seeding": int(_first(stats, "seeding", "seeding_count", default=0) or 0),
                "leeching": int(_first(stats, "leeching", "leeching_count", default=0) or 0),
                "last_update": str(_first(stats, "last_update", "updated_at", "date", default="")),
            }
        )
    return out


def merge_mp_sites(sites: list, stats: list, *, include_account: bool = True) -> list:
    by_key: dict[str, dict] = {}
    for row in stats or []:
        if not isinstance(row, dict):
            continue
        for key in ("site_id", "id", "site", "name", "site_name", "domain", "site_url"):
            value = row.get(key)
            if value not in (None, ""):
                by_key.setdefault(str(value), row)
    out = []
    for site in sites or []:
        if not isinstance(site, dict):
            continue
        stat = None
        for key in ("id", "site_id", "name", "site_name", "domain", "url", "site_url"):
            value = site.get(key)
            if value not in (None, "") and str(value) in by_key:
                stat = by_key[str(value)]
                break
        out.append(normalize_mp_site(site, stat, include_account=include_account))
    return out


_TMDB_IMG_RE = re.compile(r"^(https?://image\.tmdb\.org/t/p/)([^/]+)/(.+)$")


def tmdb_sized(url: str, size: str) -> str:
    """把 TMDB 图片 URL 的尺寸段换成指定档位（original → w342/w780/w1280）。

    MP 下发的 TMDB 海报/背景全是 original 原图（单张可达 1MB+），发现页几十张
    卡片首屏经代理逐张下载原图是「海报加载不出来」的主因；列表场景用小尺寸，
    非_TMDB 地址原样返回。
    """
    m = _TMDB_IMG_RE.match(str(url or "").strip())
    if not m or m.group(2) == size:
        return url
    return f"{m.group(1)}{size}/{m.group(3)}"


def normalize_mp_media(item: dict) -> dict:
    if not isinstance(item, dict):
        return {}
    title = _first(item, "title", "name", "original_title", default="")
    year = _first(item, "year", "release_year", default="")
    mtype = mp_type(_first(item, "type", "media_type", "mtype", default=""))
    # TMDB/Douban 卡片可能把图片放在 images/posters 结构里，取一个可用的 URL
    poster = _first(item, "poster", "poster_path", "poster_url", "image", "cover", default="")
    if not poster and isinstance(item.get("images"), dict):
        poster = _first(item["images"], "poster", "cover", default="")
    poster = str(poster or "").strip()
    # 海报统一走封面代理（磁盘缓存 + 豆瓣 Referer，浏览器不再直连境外图床）；
    # TMDB original 原图降到 w342（卡片实际显示宽度 ≤300px），白名单外的地址代理不了，原样下发由浏览器直连
    poster = tmdb_sized(poster, "w342")
    proxied = proxy_url(poster) if poster else None
    return {
        "media_id": str(_first(item, "media_id", "id", "tmdb_id", "douban_id", default="")),
        "media_source": str(_first(item, "media_source", "source", default="")),
        "title": str(title),
        "year": str(year),
        "type": mtype,
        "poster": proxied or poster,
        "poster_fallback": poster if proxied else "",
        "overview": str(_first(item, "overview", "description", "plot", default=""))[:2000],
        "artist": str(_first(item, "artist", "artist_name", default="")),
        "vote": float(_first(item, "vote", "vote_average", "rating", default=0) or 0),
        "season": item.get("season"),
        "episode_count": item.get("episode_count") or item.get("total_episode"),
    }


def _str_list(value) -> list[str]:
    """MP 的 genres/companies/countries 可能是字符串、逗号串或 dict 列表，统一成字符串列表。"""
    if isinstance(value, str):
        return [x.strip() for x in re.split(r"[,，、/]", value) if x.strip()]
    out: list[str] = []
    for x in value or []:
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
        elif isinstance(x, dict):
            name = _first(x, "name", "title", "value", default="")
            if name:
                out.append(str(name))
    return out


def _person_profile(value: str) -> str:
    """人物头像 URL：TMDB 相对路径补全为完整 URL 后走封面代理，白名单外原样。"""
    path = str(value or "").strip()
    url = f"https://image.tmdb.org/t/p/w185{path}" if path.startswith("/") else path
    if not url:
        return ""
    return proxy_url(url) or url


def _credit_rows(value, *, default_role: str = "", limit: int = 60) -> list[dict]:
    """主创/演员条目统一为 {name, role, profile}；role 取 MP 的 job/department/type。"""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for x in value or []:
        if not isinstance(x, dict):
            continue
        name = str(_first(x, "name", "original_name", "actor", default="") or "").strip()
        if not name:
            continue
        role = str(
            _first(x, "job", "type", "character", "role", "character_name",
                   "known_for_department", "department", default="") or ""
        ).strip() or default_role
        key = (name, role)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "name": name,
            "role": role,
            "profile": _person_profile(_first(x, "profile_path", "profile", "avatar", "image", default="")),
        })
        if len(out) >= limit:
            break
    return out


def _digital_release(item: dict) -> str:
    """数字发行日期：MP 的 digital_release_date 常为空，从 release_dates 里
    TMDB type=4（数字发行）取最早日期。"""
    direct = str(item.get("digital_release_date") or "").strip()
    if direct:
        return direct[:10]
    dates = []
    for entry in item.get("release_dates") or []:
        if not isinstance(entry, dict) or entry.get("type") != 4:
            continue
        value = str(entry.get("date") or "").strip()
        if value:
            dates.append(value[:10])
    return min(dates) if dates else ""


def normalize_mp_media_detail(item: dict) -> dict:
    """MP 媒体详情归一化：字段全部按可用性输出，缺失的字段由前端降级隐藏。

    MP 各版本/各来源（tmdb/douban/bangumi/anilist）返回结构不一，
    演员可能在 actors/cast/credits.cast，季在 seasons；这里统一收敛。
    """
    if not isinstance(item, dict):
        return {}
    base = normalize_mp_media(item)
    mtype = base.get("type") or mp_type(_first(item, "type", "media_type", default=""))

    raw_cast = item.get("actors") or item.get("cast")
    if not raw_cast and isinstance(item.get("credits"), dict):
        raw_cast = item["credits"].get("cast")
    cast = _credit_rows(raw_cast, limit=80) or None

    seasons: list[dict] | None = None
    raw_seasons = item.get("seasons")
    if not isinstance(raw_seasons, list) or not raw_seasons:
        # 这版 MP 的 seasons 常为空对象，真正的季列表在 season_info 里
        raw_seasons = item.get("season_info")
    if isinstance(raw_seasons, list):
        rows = []
        for s in raw_seasons:
            if not isinstance(s, dict):
                continue
            rows.append({
                "name": str(_first(s, "name", "season_name", "title", default="") or ""),
                "season": s.get("season_number", s.get("season")),
                "episode_count": s.get("episode_count", s.get("total_episode")),
                "air_date": str(_first(s, "air_date", "release_date", default="") or ""),
                "overview": str(_first(s, "overview", "description", default="") or ""),
            })
        seasons = rows or None

    # 详情背景图同样走封面代理（w1280 直连 TMDB 国内基本加载不动）；original 原图降档。
    # backdrop_fallback = 原始直连地址：代理 502 时前端重试直连，借用浏览器侧代理/缓存
    backdrop_raw = str(_first(item, "backdrop", "backdrop_path", "fanart", default="") or "").strip()
    backdrop_raw = tmdb_sized(backdrop_raw, "w1280") if backdrop_raw else ""
    proxied_backdrop = proxy_url(backdrop_raw) if backdrop_raw else None
    backdrop = proxied_backdrop or backdrop_raw
    backdrop_fallback = backdrop_raw if proxied_backdrop else ""

    return {
        **base,
        "backdrop": backdrop,
        "backdrop_fallback": backdrop_fallback,
        "original_title": str(_first(item, "original_title", "original_name", default="") or ""),
        "en_title": str(_first(item, "en_title", default="") or ""),
        "runtime": item.get("runtime") or item.get("duration") or None,
        "release_date": str(_first(item, "release_date", "air_date", "first_air_date", default="") or ""),
        "status": str(_first(item, "status", "state", default="") or ""),
        "original_language": str(_first(item, "original_language", "original_lang", default="") or ""),
        "genres": _str_list(item.get("genres")),
        "production_countries": _str_list(item.get("production_countries")),
        "production_companies": _str_list(item.get("production_companies")),
        "tmdb_id": str(_first(item, "tmdb_id", "media_id", default="") or ""),
        "imdb_id": str(item.get("imdb_id") or ""),
        "tvdb_id": str(item.get("tvdb_id") or ""),
        "douban_id": str(item.get("douban_id") or ""),
        "bangumi_id": str(item.get("bangumi_id") or ""),
        "douban_link": str(_first(item, "douban_link", "douban_url", default="") or ""),
        "digital_release": _digital_release(item),
        # 主创（导演/编剧/制作人等）逐人列出，role 为 MP 的 job/department；
        # 电视剧的 created_by（主创）并入末尾
        "credits": (
            _credit_rows(item.get("directors"))
            + _credit_rows(item.get("writers"))
            + _credit_rows(item.get("producers"))
            + _credit_rows(item.get("created_by"), default_role="主创", limit=20)
        ) or None,
        "cast": cast,
        "seasons": seasons,
        "type": mtype,
    }


def _int_or_zero(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


_SEASON_RE = re.compile(r"第\s*(\d+)\s*季")
_SEASON_RANGE_RE = re.compile(r"[Ss](\d{1,2})\s*[-~至]\s*[Ss]?(\d{1,2})")
_CN_SEASON_RANGE_RE = re.compile(r"(\d{1,2})\s*[-~至]\s*(\d{1,2})\s*季")
_SEASON_S_RE = re.compile(r"[Ss](\d{1,2})(?!\d)")
_SEASON_EP_RE = re.compile(r"[Ss](\d{1,2})\s*[Ee](\d{1,4})")
_EP_RANGE_RE = re.compile(r"[Ee][Pp]?(\d{1,4})\s*[-~至]\s*[Ee]?[Pp]?(\d{1,4})")
_EP_SINGLE_RE = re.compile(r"[Ee][Pp]?(\d{1,4})(?!\d)")
_ALL_EP_RE = re.compile(r"全\s*(\d{1,4})\s*集")
_CN_EP_RANGE_RE = re.compile(r"第\s*(\d{1,4})\s*[-~至]\s*(\d{1,4})\s*集")
_CN_EP_SINGLE_RE = re.compile(r"第\s*(\d{1,4})\s*集")


def season_label(meta: dict, title: str = "", subtitle: str = "") -> str:
    """人读的季集标签：第1季 / 全5季 / 第1-5季 / 全20集 / 第1季 · 全20集 / 第2集。

    先看标题与副标题（发布名里的 S01-05、1-5季、全20集 最可靠），再回退 MP 的 meta
    字段——MP 会把 `S01-05` 误解析成 S01E05（begin_episode=5），不能盲信。电影返回空串。
    """
    text = f"{title} {subtitle}"
    season_txt = ""
    ep_no: int | None = None

    rng = _SEASON_RANGE_RE.search(text) or _CN_SEASON_RANGE_RE.search(text)
    se = _SEASON_EP_RE.search(text)
    sm = _SEASON_RE.search(text) or _SEASON_S_RE.search(text)
    season_no = int(se.group(1)) if se else int(sm.group(1)) if sm else 0
    # 第 1 季无需强调季号（单季剧/第一季合集只显示集数）；第 2 季起必须保留季信息
    first_season_only = not rng and season_no == 1
    if rng and not se:
        a, b = int(rng.group(1)), int(rng.group(2))
        season_txt = f"第{a}-{b}季" if b > a else f"第{a}季"
    elif se:
        season_txt = f"第{int(se.group(1))}季"
        ep_no = int(se.group(2))
    elif sm:
        season_txt = f"第{int(sm.group(1))}季"

    ep_txt = ""
    all_ep = _ALL_EP_RE.search(text)
    cn_ep_rng = _CN_EP_RANGE_RE.search(text)
    cn_ep_single = _CN_EP_SINGLE_RE.search(text)
    ep_rng = _EP_RANGE_RE.search(text)
    ep_single = _EP_SINGLE_RE.search(text)
    if all_ep:
        ep_txt = f"全{int(all_ep.group(1))}集"
    elif ep_no:
        ep_txt = f"第{ep_no}集"
    elif cn_ep_rng:
        ep_txt = f"第{int(cn_ep_rng.group(1))}-{int(cn_ep_rng.group(2))}集"
    elif cn_ep_single:
        ep_txt = f"第{int(cn_ep_single.group(1))}集"
    elif ep_rng and "s" not in ep_rng.group(0).lower():
        ep_txt = f"第{int(ep_rng.group(1))}-{int(ep_rng.group(2))}集"
    elif ep_single and not season_txt:
        ep_txt = f"第{int(ep_single.group(1))}集"

    if season_txt or ep_txt:
        if first_season_only:
            # 第 1 季只显示集数（第30-31集 / 全20集），不重复「第1季」
            return ep_txt or season_txt
        return " · ".join(x for x in (season_txt, ep_txt) if x)

    # 标题里没有季集信息：回退 MP 解析字段
    begin_s = _int_or_zero(meta.get("begin_season"))
    end_s = _int_or_zero(meta.get("end_season"))
    total_s = _int_or_zero(meta.get("total_season"))
    begin_ep = _int_or_zero(meta.get("begin_episode"))
    end_ep = _int_or_zero(meta.get("end_episode"))
    total_ep = _int_or_zero(meta.get("total_episode"))

    parts: list[str] = []
    if begin_s and end_s and end_s > begin_s:
        parts.append(f"第{begin_s}-{end_s}季")
    elif total_s > 1 and begin_s:
        parts.append(f"全{total_s}季")
    elif begin_s and total_s != 1:
        # total_season==1 的单季剧不标「第1季」（用户视角只关心集数）
        parts.append(f"第{begin_s}季")
    if begin_ep and end_ep and end_ep > begin_ep:
        parts.append(f"第{begin_ep}-{end_ep}集")
    elif begin_ep and end_ep:
        parts.append(f"第{begin_ep}集")
    elif total_ep and not begin_ep:
        parts.append(f"全{total_ep}集")
    return " · ".join(parts)


def normalize_mp_torrent(item: dict) -> dict:
    """兼容 MP v3 嵌套结构（meta_info/torrent_info）与旧版扁平结构。

    enclosure/site_cookie/site_ua 可能含 PT passkey，绝不返回。
    """
    if not isinstance(item, dict):
        return {}
    torrent = item.get("torrent_info") if isinstance(item.get("torrent_info"), dict) else {}
    meta = item.get("meta_info") if isinstance(item.get("meta_info"), dict) else {}

    def pick(*keys, default=""):
        for source in (torrent, item):
            for key in keys:
                value = source.get(key)
                if value not in (None, ""):
                    return value
        return default

    size = pick("size", default=0)
    try:
        size = int(float(size))
    except (TypeError, ValueError):
        size = 0
    subtitle = str(meta.get("subtitle") or "")
    media = item.get("media_info") if isinstance(item.get("media_info"), dict) else {}
    description = str(pick("description") or subtitle)
    # 中文名优先：站点副标题的「|」前半段通常就是「中文名 第N季 全X集」
    # 中文名：媒体标题最干净（爱情公寓）；缺失时才用站点副标题前缀
    cn_title = str(media.get("title") or "").strip()
    if not cn_title and subtitle:
        cn_title = subtitle.split("|", 1)[0].strip()
    if not cn_title:
        cn_title = str(meta.get("cn_name") or "")
    return {
        "title": str(pick("title") or meta.get("title") or ""),
        "cn_title": cn_title,
        "season_label": season_label(meta, str(pick("title") or meta.get("title") or ""), subtitle or description),
        # 确认下载弹窗用：媒体身份（来源/ID/类型）
        "media_source": str(media.get("media_source") or ""),
        "media_id": str(media.get("media_id") or ""),
        "media_type_cn": str(media.get("type") or meta.get("type") or ""),
        "site_name": str(pick("site_name")),
        "site_id": pick("site", default=None),
        "size": size,
        "seeders": int(pick("seeders", default=0) or 0),
        "leechers": int(pick("peers", "leechers", default=0) or 0),
        "grabs": int(pick("grabs", default=0) or 0),
        "volume_factor": str(pick("volume_factor")),
        "pubdate": str(pick("pubdate")),
        "page_url": _safe_public_url(str(pick("page_url"))),
        "description": str(pick("description") or subtitle)[:1000],
        "category": str(pick("category") or meta.get("type") or ""),
        "hit_and_run": bool(pick("hit_and_run", default=False)),
        "free_date": str(pick("freedate")),
        "free_date_diff": str(pick("freedate_diff")),
        "labels": pick("labels", default=[]) if isinstance(pick("labels", default=[]), list) else [],
        "subtitle": subtitle[:500],
        "downloadable": bool(pick("enclosure", default="")),
        "year": str(meta.get("year") or ""),
        "media_type": str(meta.get("type") or ""),
        "resolution": str(meta.get("resource_pix") or ""),
        "resource_type": str(meta.get("resource_type") or ""),
        "resource_effect": str(meta.get("resource_effect") or ""),
        "video_encode": str(meta.get("video_encode") or ""),
        "audio_encode": str(meta.get("audio_encode") or ""),
        "web_source": str(meta.get("web_source") or ""),
        "season_episode": str(meta.get("season_episode") or ""),
    }


def normalize_brush(status: dict) -> dict:
    if not isinstance(status, dict):
        return {"available": False, "summary": {}, "tasks": []}
    summary = status.get("summary") or {}
    tasks = status.get("tasks") or []
    out_tasks = []
    for task in tasks if isinstance(tasks, list) else []:
        if not isinstance(task, dict):
            continue
        out_tasks.append(
            {
                "id": str(task.get("id") or ""),
                "name": str(task.get("name") or ""),
                "enabled": bool(task.get("enabled")),
                "site_id": task.get("site_id"),
                "site_name": str(task.get("site_name") or ""),
                "downloader": str(task.get("downloader") or ""),
                "state": str(task.get("state") or ""),
                "last_error": str(task.get("last_error") or ""),
                "next_run_at": str(task.get("next_run_at") or ""),
                "last_run": task.get("last_run"),
                "statistic": task.get("statistic") or {},
                "seeding_size": task.get("seeding_size") or 0,
                "site_ratio": task.get("site_ratio") or {},
            }
        )
    return {
        "available": True,
        "enabled": bool(status.get("enabled")),
        "summary": {
            "task_count": int(summary.get("task_count") or 0),
            "enabled_count": int(summary.get("enabled_count") or 0),
            "running_count": int(summary.get("running_count") or 0),
            "active_count": int(summary.get("active_count") or 0),
            "uploaded": summary.get("uploaded") or 0,
            "downloaded": summary.get("downloaded") or 0,
            "seeding_size": summary.get("seeding_size") or 0,
        },
        "tasks": out_tasks,
    }




def _http_image(value) -> str:
    raw = str(value or "").strip()
    return raw if raw.startswith(("http://", "https://")) else ""


def _tmdb_sized(url: str, size: str) -> str:
    """把 TMDB 的 original 图片换成适合展示的尺寸，避免详情页下载原图。"""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if (parts.hostname or "").lower() != "image.tmdb.org":
        return url
    marker = "/t/p/"
    if marker not in parts.path:
        return url
    tail = parts.path.split(marker, 1)[1]
    if "/" not in tail:
        return url
    _, filename = tail.split("/", 1)
    if not filename:
        return url
    return urlunsplit(
        (parts.scheme, parts.netloc, f"{marker}{size}/{filename}", parts.query, parts.fragment)
    )


def _find_mp_media_row(client, digest: str, save_path: str, name: str) -> dict:
    """在 MP 整理/下载历史里找种子对应的媒体记录。

    整理历史优先（已转媒体的种子没有下载历史 hash）；整理记录 hash 可能为空，
    用 src 路径回退；下载历史按 download_hash 匹配。
    """
    for history, is_transfer in (
        (client.transfer_history, True),
        (client.download_history, False),
    ):
        for page in range(1, _HISTORY_SCAN_PAGES + 1):
            try:
                rows = history(page=page, count=_HISTORY_SCAN_COUNT)
            except SeedError:
                break
            if not rows:
                break
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if is_transfer:
                    if mp_transfer_matches(
                        row,
                        digest=digest,
                        save_path=save_path,
                        name=name,
                    ):
                        return row
                else:
                    row_hash = str(row.get("download_hash") or "").strip().lower()
                    if digest and row_hash == digest:
                        return row
            if len(rows) < _HISTORY_SCAN_COUNT:
                break
    return {}


def _extra_backdrops(media: dict) -> list[str]:
    """从 MP 的 tmdb_info/images 里补更多宽幅剧照（有则轮播，无则只有主背景）。"""
    out: list[str] = []
    for holder in (media, media.get("tmdb_info")):
        if not isinstance(holder, dict):
            continue
        images = holder.get("images")
        if not isinstance(images, dict):
            continue
        for entry in images.get("backdrops") or []:
            path = entry.get("file_path") if isinstance(entry, dict) else None
            if isinstance(path, str) and path.startswith("/"):
                url = "https://image.tmdb.org/t/p/w1280" + path
                if url not in out:
                    out.append(url)
    return out


def torrent_media_detail(
    conn: SeedConnection,
    item: dict,
    tmdb_conf: tuple[str, str, str, str] | None = None,
) -> dict:
    """详情抽屉的 MP 媒体信息（海报/宽幅背景/标题），失败返回空对象。

    tmdb_conf = (key, proxy, api_base, image_base)，可选；配置了影视 TMDB Key 时
    会额外取多张宽幅剧照供轮播，没有 Key 时只使用 MP 返回的单张背景。
    """
    digest = str(item.get("hash") or "").strip().lower()
    save_path = str(item.get("save_path") or "")
    name = str(item.get("name") or "")
    key = (conn.id, digest or f"{save_path}|{name}")
    now = time.time()
    with _DETAIL_MEDIA_LOCK:
        cached_value = _DETAIL_MEDIA.get(key)
        if cached_value and now - cached_value[0] < _DETAIL_MEDIA_TTL:
            return cached_value[1]
    result: dict = {}
    try:
        client = mp_client(conn)
        row = _find_mp_media_row(client, digest, save_path, name)
        if not row:
            with _DETAIL_MEDIA_LOCK:
                _DETAIL_MEDIA[key] = (now, result)
            return result
        media_id = str(row.get("media_id") or "").strip()
        media_source = str(row.get("media_source") or "").strip()
        type_name = str(row.get("type") or "").strip()
        title = str(row.get("title") or "").strip()
        year = str(row.get("year") or "").strip()
        poster = _tmdb_sized(
            _http_image(row.get("poster")) or _http_image(row.get("image")),
            "w500",
        )
        backdrop = ""
        overview = ""
        extras: list[str] = []
        if media_id and media_source and type_name:
            try:
                media = client.media_detail(media_id, media_source, type_name)
            except SeedError:
                media = {}
            if media:
                title = str(media.get("title") or title).strip()
                year = str(media.get("year") or year).strip()
                poster = _tmdb_sized(_http_image(media.get("poster_path")), "w500") or poster
                backdrop = _tmdb_sized(_http_image(media.get("backdrop_path")), "w1280")
                overview = str(media.get("overview") or "").strip()
                extras = _extra_backdrops(media)
            if media_source == "themoviedb" and str(media_id).isdigit() and tmdb_conf and tmdb_conf[0]:
                kind = "movie" if type_name == "电影" else ("tv" if type_name in ("电视剧", "剧集") else "")
                if kind:
                    extras = [
                        *tmdb.backdrop_urls(
                            kind,
                            media_id,
                            tmdb_conf[0],
                            tmdb_conf[1],
                            tmdb_conf[2] or tmdb.API_DEFAULT,
                            tmdb_conf[3] or tmdb.IMAGE_DEFAULT,
                        ),
                        *extras,
                    ]
        urls: list[str] = []
        for url in [backdrop, *extras]:
            if url and url not in urls:
                urls.append(url)
        proxied: list[str] = []
        fallbacks: list[str] = []
        for url in urls:
            proxied_url = proxy_url(url)
            proxied.append(proxied_url or url)
            fallbacks.append(url)
        poster_src = (proxy_url(poster) or poster) if poster else ""
        result = {
            "title": title,
            "year": year,
            "overview": overview,
            "poster": poster_src,
            "poster_fallback": poster,
            "backdrops": proxied,
            "backdrops_fallback": fallbacks,
        }
    except Exception as e:  # noqa: BLE001 - 详情增强失败不能拖垮 qB 详情
        logger.debug("读取种子媒体详情失败：%s", e)
        result = {}
    with _DETAIL_MEDIA_LOCK:
        _DETAIL_MEDIA[key] = (now, result)
    return result


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
