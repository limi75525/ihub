"""种子模块 API：qBittorrent 下载器 + MoviePilot 媒体自动化。

权限：
- 所有登录用户按「设置 → 种子 → 普通用户可见范围」读取；
- 管理员始终可见全部栏目；
- 写操作仅管理员；删除种子需二次确认 + 管理员密码。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.crypto import encrypt_text
from app.core.deps import get_current_admin, get_current_user, get_media_user
from app.core.ratelimit import LockoutCounter, SlidingWindowLimiter
from app.core.security import verify_password
from app.db.session import get_db
from app.models.seed_connection import SeedConnection
from app.models.source import Source  # noqa: F401 确保模型注册
from app.models.user import User
from app.schemas.seed import (
    SeedActionIn,
    SeedAddIn,
    SeedBulkActionIn,
    SeedBulkDeleteIn,
    SeedConnectionIn,
    SeedConnectionPatch,
    SeedDeleteIn,
    SeedResourceActionIn,
    SeedTransferIn,
    SubscribeSeasonIn,
)
from app.services import seed_actions, seed_covers, seed_events, seed_traffic, seed_transfer
from app.services import tmdb
from app.services.moviepilot import RECOMMEND_PATHS, operation_context
from app.services.settings_store import get_cfg, get_cfgs, get_credential
from app.core.sqlutil import escape_like
from app.models.video_item import VideoItem
from app.services.seed_covers import proxy_url
from app.services.seed_common import SeedError, normalize_base_url
from app.services.seed_service import (
    ALL_TABS,
    allowed_tabs,
    cached,
    cache_drop,
    connection_out,
    connection_status,
    invalidate_connection,
    invalidate_qb_list,
    attach_download_media,
    merge_mp_sites,
    mp_client,
    normalize_brush,
    normalize_mp_media,
    normalize_mp_media_detail,
    normalize_mp_subscription,
    normalize_mp_torrent,
    normalize_qb_detail,
    normalize_qb_summary,
    normalize_qb_torrent,
    qb_client,
    require_tab,
    torrent_media_detail,
)

router = APIRouter(prefix="/seeds", tags=["seeds"])

logger = logging.getLogger(__name__)
audit = logging.getLogger("ihub.seed.control")

_SEARCH_LIMITER = SlidingWindowLimiter(
    window=60.0,
    max_hits=20,
    message="种子搜索过于频繁，请稍后再试",
)
_DELETE_FAILS = LockoutCounter(
    window=15 * 60,
    max_fails=5,
    lock_seconds=15 * 60,
    locked_message="管理员密码错误次数过多，请 {minutes} 分钟后重试",
)

MAX_TORRENT_FILE = 10 * 1024 * 1024


# ---- 公共 ----

def _first_conn(db: Session, kind: str, *, enabled_only: bool = True) -> SeedConnection:
    q = db.query(SeedConnection).filter(SeedConnection.kind == kind)
    if enabled_only:
        q = q.filter(SeedConnection.enabled.is_(True))
    conn = q.order_by(SeedConnection.sort_order.asc(), SeedConnection.id.asc()).first()
    if not conn:
        label = "qBittorrent" if kind == "qbittorrent" else "MoviePilot"
        exists_any = (
            db.query(SeedConnection.id)
            .filter(SeedConnection.kind == kind)
            .first()
            is not None
        )
        if exists_any:
            raise HTTPException(404, f"当前 {label} 未开启，请到 设置 → 种子 开启后使用")
        raise HTTPException(404, f"尚未配置 {label} 连接，请到 设置 → 种子 添加并开启")
    return conn


def _conn_by_id(db: Session, conn_id: int) -> SeedConnection:
    conn = db.get(SeedConnection, conn_id)
    if not conn:
        raise HTTPException(404, "连接不存在")
    return conn


def _validate_conn_fields(kind: str, auth_mode: str, secret: str) -> str:
    if kind == "qbittorrent":
        if auth_mode not in ("password", "none"):
            raise HTTPException(400, "qBittorrent 认证方式只支持 password / none")
        if auth_mode == "password" and not secret:
            raise HTTPException(400, "qBittorrent 用户名密码认证需要填写密码")
    elif kind == "moviepilot":
        if auth_mode not in ("api_token", "password"):
            raise HTTPException(400, "MoviePilot 认证方式只支持 api_token / password")
        if auth_mode == "api_token" and not secret:
            raise HTTPException(400, "MoviePilot 需要填写 API_TOKEN")
        if auth_mode == "password" and not secret:
            raise HTTPException(400, "MoviePilot 用户名密码认证需要填写密码")
    else:
        raise HTTPException(400, "未知的连接类型")
    return auth_mode


_HASH_RE = re.compile(r"^[A-Za-z0-9]{6,128}$")


def _clean_hashes(hashes: list[str]) -> list[str]:
    cleaned = list(dict.fromkeys(h.strip() for h in hashes if h and h.strip()))
    if not cleaned:
        raise HTTPException(400, "请至少选择一个种子")
    if len(cleaned) > 200:
        raise HTTPException(400, "一次最多操作 200 个种子")
    if any(not _HASH_RE.fullmatch(h) for h in cleaned):
        raise HTTPException(400, "种子哈希格式不正确")
    return cleaned


def _verify_admin_password(admin: User, password: str) -> None:
    key = f"seed-delete:{admin.id}"
    try:
        _DELETE_FAILS.check(key)
    except PermissionError as e:
        raise HTTPException(429, str(e))
    if not verify_password(password, admin.password_hash):
        _DELETE_FAILS.record_failure(key)
        raise HTTPException(403, "管理员密码错误")
    _DELETE_FAILS.clear(key)


def _sync_worker() -> None:
    try:
        seed_events.sync_worker()
    except Exception:
        logger.exception("同步种子事件线程失败")
    try:
        seed_traffic.sync_worker()
    except Exception:
        logger.exception("同步网络流量采样线程失败")
    try:
        seed_transfer.start_worker()
    except Exception:
        logger.exception("启动转媒体线程失败")


# ---- 连接 ----

@router.get("/connections")
def list_connections(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    rows = (
        db.query(SeedConnection)
        .order_by(SeedConnection.sort_order.asc(), SeedConnection.id.asc())
        .all()
    )
    return [connection_out(c, admin=True) for c in rows]


@router.post("/connections", status_code=201)
def create_connection(
    body: SeedConnectionIn,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    base_url = normalize_base_url(body.base_url)
    auth_mode = _validate_conn_fields(body.kind, body.auth_mode, body.secret)
    name = (body.name or "").strip() or ("qBittorrent" if body.kind == "qbittorrent" else "MoviePilot")
    conn = SeedConnection(
        kind=body.kind,
        name=name[:64],
        base_url=base_url,
        username=(body.username or "").strip()[:256],
        secret_cipher=encrypt_text(body.secret) if body.secret else "",
        auth_mode=auth_mode,
        verify_tls=bool(body.verify_tls),
        enabled=bool(body.enabled),
        created_by=admin.id,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    _sync_worker()
    return connection_out(conn, admin=True)


@router.patch("/connections/{conn_id}")
def update_connection(
    conn_id: int,
    body: SeedConnectionPatch,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    conn = _conn_by_id(db, conn_id)
    old_auth_mode = conn.auth_mode
    fields = body.model_fields_set
    if "base_url" in fields and body.base_url is not None:
        conn.base_url = normalize_base_url(body.base_url)
    if "name" in fields and body.name is not None:
        conn.name = body.name.strip()[:64] or conn.name
    if "username" in fields:
        conn.username = (body.username or "").strip()[:256]
    if body.clear_secret:
        conn.secret_cipher = ""
    elif body.secret:
        conn.secret_cipher = encrypt_text(body.secret)
    if "auth_mode" in fields and body.auth_mode is not None:
        _validate_conn_fields(conn.kind, body.auth_mode, "placeholder")
        conn.auth_mode = body.auth_mode
    if "verify_tls" in fields and body.verify_tls is not None:
        conn.verify_tls = bool(body.verify_tls)
    if "enabled" in fields and body.enabled is not None:
        conn.enabled = bool(body.enabled)
    if conn.auth_mode != old_auth_mode and not body.secret and not body.clear_secret:
        raise HTTPException(400, "切换认证方式需要重新填写密钥")
    _validate_conn_fields(
        conn.kind,
        conn.auth_mode,
        # 已存在密文即视为有密钥，不再要求本次请求重传
        "existing" if conn.secret_cipher else "",
    )
    conn.last_ok_at = None
    conn.last_error = ""
    db.commit()
    db.refresh(conn)
    # 只丢弃被修改连接的客户端：保存 MP 时不能把 qB 的已登录会话一起清掉，
    # 否则事件线程/页面重新登录会与旧会话互踢（qB 会短暂 403）。
    invalidate_connection(conn.id)
    _sync_worker()
    return connection_out(conn, admin=True)


@router.delete("/connections/{conn_id}")
def delete_connection(
    conn_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    conn = _conn_by_id(db, conn_id)
    db.delete(conn)
    db.commit()
    invalidate_connection(conn_id)
    _sync_worker()
    return {"ok": True}


@router.post("/connections/{conn_id}/test")
def test_connection(
    conn_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    conn = _conn_by_id(db, conn_id)
    try:
        if conn.kind == "qbittorrent":
            # 手动测试必须绕过失败冷却：即使后台轮询刚失败，也允许用户立即重新验证
            client = qb_client(conn, fresh=True)
            result = client.test()
            conn.server_version = str(result.get("version") or "")
            conn.capabilities_json = json.dumps(
                {"webapi_version": result.get("webapi_version") or ""},
                ensure_ascii=False,
            )
        else:
            client = mp_client(conn, fresh=True)
            result = client.test()
            conn.server_version = str(result.get("version") or "")
            conn.capabilities_json = json.dumps(result, ensure_ascii=False)
        conn.last_ok_at = datetime.now(timezone.utc)
        conn.last_error = ""
        db.commit()
        # 不要在这里清掉客户端缓存：测试连接建立的 SID 要留给 API/事件线程复用，
        # 否则重新登录会轮换 qB 会话，另一个客户端拿旧 SID 继续请求就会 403。
        # 连接已经验证可用，此时再启动事件线程，让它复用同一个客户端会话。
        seed_events.start_worker()
        seed_traffic.sync_worker()
        return {"ok": True, **result}
    except SeedError as e:
        conn.last_error = e.message[:500]
        db.commit()
        raise
    except Exception as e:
        conn.last_error = str(e)[:500]
        db.commit()
        raise HTTPException(502, f"连接测试失败：{e}")


@router.get("/cover")
def seed_cover(
    url: str = Query(..., min_length=10, max_length=4096),
    user: User = Depends(get_media_user),
    db: Session = Depends(get_db),
):
    """PT 封面代理：仅允许白名单 HTTPS 图片，落盘缓存后返回。

    种子各栏目（下载/订阅/发现/搜索）的图片都经这里中转，任一可见即可用。"""
    if user.role != "admin" and not allowed_tabs(user, db) & {
        "download", "discover", "search", "subscription",
    }:
        raise HTTPException(403, "当前账号没有查看该种子栏目的权限")
    try:
        path, media_type = seed_covers.get_cover(url)
    except SeedError as e:
        raise HTTPException(e.status_code, e.message)
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


# ---- 状态 ----
# 事件通知与可见范围已固化为默认行为（2026-10-25）：种子模块仅管理员可见；
# 通知矩阵见 seed_events._recipients（download_finish 全体用户，其余仅管理员）。


@router.get("/status")
def seed_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tabs = sorted(allowed_tabs(user, db), key=ALL_TABS.index)
    visible = bool(tabs) or user.role == "admin"
    if not visible:
        return {"visible": False, "tabs": [], "configured": False, "connections": []}
    conns = (
        db.query(SeedConnection)
        .filter(SeedConnection.enabled.is_(True))
        .order_by(SeedConnection.sort_order.asc(), SeedConnection.id.asc())
        .all()
    )
    return {
        "visible": True,
        "tabs": tabs,
        "configured": bool(conns),
        "connections": [connection_status(c) for c in conns],
    }


@router.get("/overview")
def seed_overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tabs = allowed_tabs(user, db)
    if user.role != "admin" and not tabs:
        raise HTTPException(403, "当前账号没有查看种子页的权限")
    qb_data = None
    mp_data = None
    errors: list[str] = []

    if "download" in tabs:
        try:
            conn = _first_conn(db, "qbittorrent")
            qb_data = cached(conn.id, "qb:summary", 2.0, lambda: _qb_summary(conn))
        except SeedError as e:
            errors.append(f"qBittorrent：{e.message}")
        except HTTPException:
            pass

    if "subscription" in tabs or "sites" in tabs or "brush" in tabs:
        try:
            conn = _first_conn(db, "moviepilot")
            mp_data = cached(conn.id, "mp:overview", 30.0, lambda: _mp_overview(conn, tabs, user))
        except SeedError as e:
            errors.append(f"MoviePilot：{e.message}")
        except HTTPException:
            pass

    # 概览成功读取时会先建立 qB/MP 客户端会话；此时再启动事件线程可复用它，
    # 避免服务启动或保存连接时事件线程抢先登录造成多会话互踢。
    if qb_data or mp_data:
        seed_events.start_worker()
    return {"qb": qb_data, "mp": mp_data, "errors": errors}


def _qb_summary(conn: SeedConnection, *, fresh: bool = False) -> dict:
    client = qb_client(conn, fresh=fresh)
    transfer = client.transfer_info()
    maindata = client.sync_maindata(0)
    return normalize_qb_summary(transfer, maindata)


def _mp_overview(conn: SeedConnection, tabs: set[str], user: User) -> dict:
    client = mp_client(conn)
    subscriptions = client.subscriptions(page=1, count=200) if "subscription" in tabs else []
    sites = client.sites() if "sites" in tabs else []
    stats = client.site_statistics() if "sites" in tabs else []
    # overview 只需要站点数量与在线数，不展示账号数据
    merged = merge_mp_sites(sites, stats, include_account=False) if sites else []
    brush = None
    if "brush" in tabs:
        try:
            brush = normalize_brush(client.brush_status())
        except SeedError as e:
            if e.status_code != 404:
                raise
    storage = None
    try:
        storage = client.storage()
    except SeedError:
        # MP 存储统计是可选的：低权限/旧版本没有该接口时退回 qB 估算口径
        storage = None
    return {
        "subscriptions": len(subscriptions or []),
        "sites_total": len(merged),
        "sites_online": sum(1 for s in merged if s.get("active")),
        "brush": brush,
        "storage": storage,
    }


# ---- qBittorrent ----

def _qb_conn(db: Session) -> SeedConnection:
    return _first_conn(db, "qbittorrent")


@router.get("/qb/summary")
def qb_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_tab(user, db, "download")
    conn = _qb_conn(db)
    return cached(conn.id, "qb:summary", 2.0, lambda: _qb_summary(conn))


@router.get("/qb/traffic")
def qb_traffic(
    limit: int = Query(seed_traffic.DEFAULT_LIMIT, ge=1, le=seed_traffic.MAX_SAMPLES),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_tab(user, db, "download")
    conn = _qb_conn(db)
    items = seed_traffic.snapshot(conn.id, limit)
    if not items:
        try:
            seed_traffic.sample_now(conn)
        except Exception:
            pass
        items = seed_traffic.snapshot(conn.id, limit)
    return {"items": items, "interval": seed_traffic.INTERVAL}


@router.get("/qb/torrents")
def qb_torrents(
    filter: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    q: str | None = None,
    sort: str = "added_on",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_tab(user, db, "download")
    conn = _qb_conn(db)

    def load(fresh: bool = False) -> list[dict]:
        client = qb_client(conn, fresh=fresh)
        qfilter = None if filter in (None, "", "all") else filter
        if qfilter == "error":
            # qB 原生筛选值是 errored；前端用更直观的 error
            qfilter = "errored"
        rows = client.torrents(
            filter=qfilter,
            category=category or None,
            tag=tag or None,
        )
        return [normalize_qb_torrent(r) for r in rows if isinstance(r, dict)]

    items = cached(
        conn.id,
        f"qb:list:{filter or ''}:{category or ''}:{tag or ''}",
        3.0,
        load,
    )
    if q:
        keyword = q.strip().lower()
        if keyword:
            items = [x for x in items if keyword in x["name"].lower()]
    # 正序 = "size" / 倒序 = "-size"；不传或未知字段时保持默认（添加时间倒序）
    descending = sort.startswith("-")
    key = sort.lstrip("-")
    numeric_keys = {
        "progress", "size", "total_size", "dlspeed", "upspeed", "ratio",
        "added_on", "completion_on", "eta", "num_seeds", "num_leechs",
        "time_active", "seeding_time",
    }
    string_keys = {"name", "category", "state", "tracker", "save_path"}
    if key in numeric_keys:
        items = sorted(items, key=lambda x: x.get(key) or 0, reverse=descending)
    elif key in string_keys:
        items = sorted(items, key=lambda x: x.get(key) or "", reverse=descending)
    else:
        items = sorted(items, key=lambda x: x.get("added_on") or 0, reverse=True)
    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]
    try:
        attach_download_media(_mp_conn(db), page_items)
    except HTTPException:
        # 没配 MP 时下载页仍按纯 qB 工作
        pass
    return {
        "items": page_items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/qb/torrents/{torrent_hash}")
def qb_torrent_detail(
    torrent_hash: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_tab(user, db, "download")
    conn = _qb_conn(db)

    def load(fresh: bool = False):
        client = qb_client(conn, fresh=fresh)
        out = normalize_qb_detail(
            client.torrent_properties(torrent_hash),
            client.torrent_files(torrent_hash),
            client.torrent_trackers(torrent_hash),
            client.torrent_peers(torrent_hash),
        )
        # 详情抽屉的媒体背景/封面来自 MP 历史；MP 不可用或没有记录时保持空。
        mp_conn = (
            db.query(SeedConnection)
            .filter(SeedConnection.kind == "moviepilot", SeedConnection.enabled.is_(True))
            .order_by(SeedConnection.sort_order.asc(), SeedConnection.id.asc())
            .first()
        )
        if mp_conn:
            props = out.get("properties") or {}
            try:
                tmdb_v = get_cfgs(
                    db,
                    ("video_tmdb_proxy", "video_tmdb_api_base", "video_tmdb_image_base"),
                )
                tmdb_conf = (
                    get_credential(db, "video_tmdb_key"),
                    tmdb_v.get("video_tmdb_proxy", ""),
                    tmdb_v.get("video_tmdb_api_base", "") or tmdb.API_DEFAULT,
                    tmdb_v.get("video_tmdb_image_base", "") or tmdb.IMAGE_DEFAULT,
                )
                media = torrent_media_detail(
                    mp_conn,
                    {
                        "hash": str(props.get("hash") or torrent_hash),
                        "name": str(props.get("name") or ""),
                        "save_path": str(props.get("save_path") or ""),
                    },
                    tmdb_conf,
                )
                if media:
                    out["media"] = media
            except Exception as e:  # noqa: BLE001
                logger.debug("种子详情媒体信息读取失败：%s", e)
        return out

    return cached(conn.id, f"qb:detail:{torrent_hash}", 5.0, load)


@router.get("/qb/categories")
def qb_categories(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_tab(user, db, "download")
    conn = _qb_conn(db)
    return cached(conn.id, "qb:categories", 30.0, lambda: qb_client(conn).categories())


@router.get("/qb/tags")
def qb_tags(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_tab(user, db, "download")
    conn = _qb_conn(db)

    def load():
        # qB 的 /torrents/tags 是全局标签定义，删除种子标签后定义仍会保留；
        # 筛选下拉只展示至少有一个任务在用的标签，避免出现数量为 0 的空标签。
        client = qb_client(conn)
        tags = client.tags()
        used: set[str] = set()
        for row in client.torrents():
            for tag in str(row.get("tags") or "").split(","):
                tag = tag.strip()
                if tag:
                    used.add(tag)
        return [tag for tag in tags if tag in used]

    return cached(conn.id, "qb:tags", 30.0, load)


@router.post("/qb/torrents/bulk/action")
def qb_bulk_action(
    body: SeedBulkActionIn,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    conn = _qb_conn(db)
    hashes = _clean_hashes(body.hashes)
    qb_client(conn).actions(hashes, body.action)
    invalidate_connection(conn.id)
    audit.info(
        "种子控制：user=%s op=bulk_%s count=%s result=ok",
        admin.username, body.action, len(hashes),
    )
    return {"ok": True, "count": len(hashes)}


@router.post("/qb/torrents/bulk/delete")
def qb_bulk_delete(
    body: SeedBulkDeleteIn,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if not body.confirm:
        raise HTTPException(400, "请先确认删除操作")
    _verify_admin_password(admin, body.password)
    conn = _qb_conn(db)
    hashes = _clean_hashes(body.hashes)
    qb_client(conn).delete_many(hashes, body.delete_files)
    invalidate_connection(conn.id)
    audit.info(
        "种子控制：user=%s op=bulk_delete count=%s delete_files=%s result=ok",
        admin.username, len(hashes), body.delete_files,
    )
    return {"ok": True, "count": len(hashes), "delete_files": body.delete_files}


@router.post("/qb/torrents/{torrent_hash}/action")
def qb_action(
    torrent_hash: str,
    body: SeedActionIn,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    conn = _qb_conn(db)
    qb_client(conn).action(torrent_hash, body.action)
    invalidate_connection(conn.id)
    audit.info("种子控制：user=%s op=%s hash=%s result=ok", admin.username, body.action, torrent_hash)
    return {"ok": True}


@router.post("/qb/torrents/{torrent_hash}/delete")
def qb_delete(
    torrent_hash: str,
    body: SeedDeleteIn,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if not body.confirm:
        raise HTTPException(400, "请先确认删除操作")
    _verify_admin_password(admin, body.password)
    conn = _qb_conn(db)
    qb_client(conn).delete(torrent_hash, body.delete_files)
    invalidate_connection(conn.id)
    audit.info(
        "种子控制：user=%s op=delete hash=%s delete_files=%s result=ok",
        admin.username, torrent_hash, body.delete_files,
    )
    return {"ok": True, "delete_files": body.delete_files}


@router.post("/transfer/scan")
def transfer_scan(admin: User = Depends(get_current_admin)):
    """手动刷新触发一次 qB 转媒体扫描；有任务才启动后台轮询。"""
    pending = seed_transfer.scan_now()
    audit.info("种子资源控制：user=%s op=transfer_scan pending=%s", admin.username, pending)
    return {"pending": pending}


@router.post("/qb/torrents/{torrent_hash}/convert")
def qb_convert(
    torrent_hash: str,
    body: SeedTransferIn,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """管理员把已完成种子转出刷流目录，交给 MP 整理。"""
    conn = _qb_conn(db)
    result = seed_transfer.convert(qb_client(conn), torrent_hash, body.target)
    invalidate_qb_list(conn.id)
    audit.info(
        "种子资源控制：user=%s op=transfer hash=%s target=%s path=%s result=ok",
        admin.username, torrent_hash, body.target, result.get("path"),
    )
    return {"ok": True, **result}


@router.post("/qb/torrents")
def qb_add(
    body: SeedAddIn,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    conn = _qb_conn(db)
    qb_client(conn).add_url(
        body.url,
        save_path=body.save_path,
        category=body.category,
        tags=body.tags,
        paused=body.paused,
    )
    invalidate_connection(conn.id)
    audit.info("种子控制：user=%s op=add_url result=ok", admin.username)
    return {"ok": True}


@router.post("/qb/torrents/upload")
async def qb_add_file(
    file: UploadFile = File(...),
    save_path: str = Form(""),
    category: str = Form(""),
    tags: str = Form(""),
    paused: bool = Form(False),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    conn = _qb_conn(db)
    content = await file.read(MAX_TORRENT_FILE + 1)
    if len(content) > MAX_TORRENT_FILE:
        raise HTTPException(400, "种子文件不能超过 10MB")
    if not content:
        raise HTTPException(400, "种子文件为空")
    await run_in_threadpool(
        qb_client(conn).add_file,
        file.filename or "upload.torrent",
        content,
        save_path=save_path,
        category=category,
        tags=tags,
        paused=paused,
    )
    invalidate_connection(conn.id)
    audit.info("种子控制：user=%s op=add_file result=ok", admin.username)
    return {"ok": True}


# ---- MoviePilot ----

def _mp_conn(db: Session) -> SeedConnection:
    return _first_conn(db, "moviepilot")


def _search_items(rows: list, user: User) -> list[dict]:
    """归一化搜索结果；管理员额外拿到服务端上下文引用（op_id）。"""
    items: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = normalize_mp_torrent(row)
        if user.role == "admin":
            item["op_id"] = seed_actions.stash(user.id, operation_context(row))
        items.append(item)
    return items


@router.post("/mp/download")
async def mp_download_resource(
    body: SeedResourceActionIn,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """管理员从 PT 搜索结果直接添加下载任务。"""
    context = seed_actions.get(admin.id, body.op_id)
    if not context:
        raise HTTPException(404, "搜索结果已过期，请重新搜索")
    conn = _mp_conn(db)
    try:
        data = await run_in_threadpool(mp_client(conn).download_context, context)
    except SeedError as e:
        audit.warning("种子资源控制：user=%s op=mp_download result=error", admin.username)
        raise e
    download_id = data.get("download_id") if isinstance(data, dict) else None
    audit.info(
        "种子资源控制：user=%s op=mp_download result=ok download_id=%s",
        admin.username,
        download_id or "-",
    )
    return {"ok": True, "download_id": download_id}


@router.post("/mp/subscribe")
async def mp_subscribe_resource(
    body: SeedResourceActionIn,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """管理员从 PT 搜索结果新增订阅。"""
    context = seed_actions.get(admin.id, body.op_id)
    if not context:
        raise HTTPException(404, "搜索结果已过期，请重新搜索")
    conn = _mp_conn(db)
    try:
        data = await run_in_threadpool(mp_client(conn).subscribe_context, context)
    except SeedError as e:
        audit.warning("种子资源控制：user=%s op=mp_subscribe result=error", admin.username)
        raise e
    subscribe_id = data.get("id") if isinstance(data, dict) else None
    audit.info(
        "种子资源控制：user=%s op=mp_subscribe result=ok subscribe_id=%s",
        admin.username,
        subscribe_id or "-",
    )
    return {"ok": True, "subscribe_id": subscribe_id}


@router.get("/mp/subscriptions")
def mp_subscriptions(
    type: Literal["all", "movie", "tv", "music"] = "all",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_tab(user, db, "subscription")
    conn = _mp_conn(db)

    def load() -> list[dict]:
        rows = mp_client(conn).subscriptions(page=page, count=page_size)
        return [normalize_mp_subscription(r) for r in rows if isinstance(r, dict)]

    items = cached(conn.id, f"mp:subs:{page}:{page_size}", 30.0, load)
    if type != "all":
        items = [x for x in items if x["type"] == type]
    return {"items": items, "page": page, "page_size": page_size}


@router.get("/mp/sites")
def mp_sites(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # 站点列表也被详情页的「选择站点搜索」弹窗使用，发现/搜索任一可见即可
    if user.role != "admin":
        tabs = allowed_tabs(user, db)
        if not tabs & {"sites", "discover", "search"}:
            raise HTTPException(403, "当前账号没有查看该种子栏目的权限")
    conn = _mp_conn(db)
    # 可见范围已固定管理员（2026-10-25）：普通用户在上面的 allowed_tabs 检查已被 403 拦下
    include_account = user.role == "admin"

    def load() -> list[dict]:
        client = mp_client(conn)
        return merge_mp_sites(
            client.sites(),
            client.site_statistics(),
            include_account=include_account,
        )

    return cached(
        conn.id,
        f"mp:sites:{'account' if include_account else 'basic'}",
        60.0,
        load,
    )


def _site_status(client) -> dict:
    """MP 站点状态统计（total/ok），失败返回全零——搜索/资源为空时给前端可行动的提示。"""
    info = {"total": 0, "ok": 0}
    try:
        stats = client.site_statistics()
        info["total"] = len(stats)
        info["ok"] = sum(
            1 for s in stats if isinstance(s, dict) and str(s.get("status")) == "1"
        )
    except Exception:
        pass
    return info


@router.get("/mp/search")
def mp_search(
    q: str = Query(..., min_length=1, max_length=200),
    type: Literal["movie", "tv", "music"] | None = None,
    sites: str | None = None,
    page: int = Query(1, ge=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_tab(user, db, "search")
    try:
        _SEARCH_LIMITER.hit(f"seed-search:{user.id}")
    except PermissionError as e:
        raise HTTPException(429, str(e))
    conn = _mp_conn(db)
    client = mp_client(conn)
    rows = client.search_title(q, mtype=type, sites=sites, page=page)
    # 搜索为空时给出可行动的原因：MP 站点全离线（Cookie 失效/网络不通）是常见根因
    sites_info = _site_status(client) if not rows else {"total": 0, "ok": 0}
    return {"items": _search_items(rows, user), "page": page, "sites": sites_info}


@router.get("/mp/episodes")
def mp_episodes(
    tmdb_id: str = Query(..., min_length=1, max_length=32),
    season: int = Query(..., ge=0, le=200),
    title: str = Query("", max_length=256),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """TMDB 某季集数列表（详情页季展开）+ 绿联库的已入库集号。

    集数优先走 MP v3 的 /api/v1/tmdb/{tmdbid}/{season}（与 MP 详情页同源，含中文数据）；
    MP 未连接/旧版无此接口/查询失败时回退 TMDB 直查（复用影视模块的 Key/代理/镜像配置）。
    exists_numbers = 本机影视库（video_items 扫描数据）中已存在的集号，
    前端据此显示季的「缺失/已入库」标签；影视未启用返回空。"""
    if user.role != "admin":
        tabs = allowed_tabs(user, db)
        if not tabs & {"discover", "search"}:
            raise HTTPException(403, "当前账号没有查看该种子栏目的权限")
    items: list[dict] = []
    image_base = get_cfg(db, "video_tmdb_image_base") or tmdb.IMAGE_DEFAULT
    try:
        conn = _mp_conn(db)
        for ep in mp_client(conn).episodes(tmdb_id, season) or []:
            if not isinstance(ep, dict):
                continue
            still = ep.get("still_path")
            items.append({
                "number": ep.get("episode_number"),
                "name": str(ep.get("name") or ""),
                "air_date": str(ep.get("air_date") or ""),
                "overview": str(ep.get("overview") or ""),
                "still": (
                    f"{image_base.rstrip('/')}/t/p/w300{still}"
                    if isinstance(still, str) and still.startswith("/")
                    else ""
                ),
            })
    except (HTTPException, SeedError):
        items = []
    if not items:
        api_key = get_credential(db, "video_tmdb_key")
        if api_key:
            api_base = get_cfg(db, "video_tmdb_api_base") or tmdb.API_DEFAULT
            proxy = get_cfg(db, "video_tmdb_proxy")
            items = tmdb.season_episodes(
                api_base, api_key, proxy, image_base, tmdb_id, season,
            )
    # 剧照统一走封面代理（TMDB 图直连慢），代理不了的域名回退原始地址
    for ep in items:
        still = ep.get("still")
        if still:
            ep["still"] = proxy_url(still) or still
    # 绿联/本地影视库的已入库集号：按剧名（中文原名兜底）匹配剧集条目
    exists_numbers: list[int] = []
    if title.strip() and get_cfg(db, "video_enabled") == "true":
        conds = [VideoItem.series.ilike(escape_like(title.strip()), escape="\\")]
        rows = (
            db.query(VideoItem.episode)
            .filter(VideoItem.kind == "episode", VideoItem.season == season, or_(*conds))
            .all()
        )
        exists_numbers = sorted({int(x[0] or 0) for x in rows if x[0]})
    return {"items": items, "exists_numbers": exists_numbers}


@router.get("/mp/season-exists")
def mp_season_exists(
    title: str = Query(..., min_length=1, max_length=256),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """本机影视库（video_items 扫描数据）各季已入库集数：{季号: 集数}。

    供详情页季行的「缺失/已入库」标签使用；matched=剧在库里有任何集数条目，
    前端仅在 matched 时显示标签（剧完全不在库里就不标，避免整页误标缺失）。"""
    if user.role != "admin":
        tabs = allowed_tabs(user, db)
        if not tabs & {"discover", "search"}:
            raise HTTPException(403, "当前账号没有查看该种子栏目的权限")
    exists: dict[str, int] = {}
    matched = False
    if get_cfg(db, "video_enabled") == "true":
        kw = escape_like(title.strip())
        rows = (
            db.query(VideoItem.season, VideoItem.episode)
            .filter(
                VideoItem.kind == "episode",
                or_(
                    VideoItem.series.ilike(kw, escape="\\"),
                    VideoItem.series.ilike(f"%{kw}%", escape="\\"),
                ),
            )
            .all()
        )
        by_season: dict[int, set[int]] = {}
        for season, episode in rows:
            by_season.setdefault(int(season or 0), set()).add(int(episode or 0))
        matched = bool(by_season)
        exists = {str(k): len(v) for k, v in by_season.items() if k > 0}
    return {"exists": exists, "matched": matched}


@router.get("/mp/subscribe-state")
def mp_subscribe_state(
    tmdb_id: str = Query(..., min_length=1, max_length=32),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """某 TMDB 剧集在 MP 里已订阅的季号列表（详情页季行爱心状态）。"""
    if user.role != "admin":
        tabs = allowed_tabs(user, db)
        if not tabs & {"discover", "search", "subscription"}:
            raise HTTPException(403, "当前账号没有查看该种子栏目的权限")
    conn = _mp_conn(db)

    def load() -> list:
        return mp_client(conn).subscriptions() or []

    # 详情页每次挂载都查订阅状态；订阅列表 2 分钟内复用，写订阅时 cache_drop 失效
    rows = cached(conn.id, "mp:subscribe-rows", 120.0, load)
    seasons = sorted({
        int(x.get("season") or 0)
        for x in rows
        if isinstance(x, dict)
        and str(x.get("media_id") or "") == str(tmdb_id)
        and (x.get("media_source") or "").lower() == "themoviedb"
        and int(x.get("season") or 0) > 0
    })
    return {"seasons": seasons}


@router.post("/mp/subscribe-season")
def mp_subscribe_season(
    body: SubscribeSeasonIn,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """季订阅/取消订阅（写 MP 真实订阅，与 MP 详情页爱心同效）。"""
    conn = _mp_conn(db)
    client = mp_client(conn)
    if body.action == "subscribe":
        payload = {
            "name": body.name,
            "year": body.year,
            "type": "tv",
            "media_source": "themoviedb",
            "media_id": body.tmdb_id,
            "season": body.season,
        }
        result = client.subscribe_create(payload)
        cache_drop(conn.id, "mp:subscribe-rows")
        audit.info(
            "季订阅：%s S%02d（MP media_id=%s）",
            body.name, body.season, body.tmdb_id,
        )
        return {"ok": True, "subscribed": True, "result": result}
    client.subscribe_delete_media(body.tmdb_id, body.season)
    cache_drop(conn.id, "mp:subscribe-rows")
    audit.info("取消季订阅：%s S%02d（MP media_id=%s）", body.name, body.season, body.tmdb_id)
    return {"ok": True, "subscribed": False}


@router.get("/mp/media-detail")
def mp_media_detail_endpoint(
    media_id: str = Query(..., min_length=1, max_length=64),
    media_source: str = Query(..., min_length=1, max_length=32),
    type_name: str = Query("", max_length=16),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """媒体详情（MP /media/{id}）：详情页的海报/背景/简介/演员/季等。

    详情可从发现/搜索进入，两个栏目任一可见即可；MP 的 type_name 用中文，
    前端传英文枚举时在这里转换。"""
    if user.role != "admin":
        tabs = allowed_tabs(user, db)
        if not tabs & {"discover", "search"}:
            raise HTTPException(403, "当前账号没有查看该种子栏目的权限")
    zh_type = {"movie": "电影", "tv": "电视剧", "music": "音乐"}.get(type_name, type_name)
    conn = _mp_conn(db)

    def load() -> dict:
        raw = mp_client(conn).media_detail(media_id, media_source, zh_type)
        return normalize_mp_media_detail(raw)

    # MP 电视剧首查会现拉 TMDB 的季/演职员（可达十几秒）；详情 10 分钟内直接复用
    key = f"mp:media-detail:{media_source}:{media_id}:{zh_type}"
    return {"detail": cached(conn.id, key, 600.0, load)}


@router.get("/mp/media")
def mp_media_search(
    q: str = Query(..., min_length=1, max_length=200),
    type: Literal["movie", "tv", "music"] | None = None,
    sources: str | None = None,
    page: int = Query(1, ge=1),
    count: int = Query(20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_tab(user, db, "search")
    try:
        _SEARCH_LIMITER.hit(f"seed-search:{user.id}")
    except PermissionError as e:
        raise HTTPException(429, str(e))
    conn = _mp_conn(db)
    source_list = [x.strip() for x in (sources or "").split(",") if x.strip()]
    rows = mp_client(conn).media_search(
        q, mtype=type, sources=source_list or None, page=page, count=count
    )
    items = [normalize_mp_media(r) for r in rows if isinstance(r, dict)]
    if type:
        items = [x for x in items if x.get("type") == type]
    seen = set()
    deduped = []
    for item in items:
        key = (item.get("media_source"), item.get("media_id"))
        if not item.get("media_id") or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return {"items": deduped, "page": page}


@router.get("/mp/torrents")
def mp_torrents(
    media_id: str = Query(..., min_length=1),
    media_source: str = Query(..., min_length=1),
    type: Literal["movie", "tv", "music"] | None = None,
    season: int | None = None,
    page: int = Query(1, ge=1),
    count: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_tab(user, db, "search")
    try:
        _SEARCH_LIMITER.hit(f"seed-search:{user.id}")
    except PermissionError as e:
        raise HTTPException(429, str(e))
    conn = _mp_conn(db)
    client = mp_client(conn)
    rows = client.search_torrents(
        media_id,
        media_source,
        mtype=type,
        season=season,
        page=page,
        count=count,
    )
    sites_info = _site_status(client) if not rows else {"total": 0, "ok": 0}
    return {"items": _search_items(rows, user), "page": page, "sites": sites_info}


DISCOVER_FILTER_KEYS = {
    "sort_by", "with_genres", "with_original_language", "with_keywords",
    "with_watch_providers", "vote_average", "vote_count", "release_date",
    "sort", "tags", "type", "cat", "year",
    "genre", "format", "season", "season_year", "status", "country",
    "mode", "entity", "range_name", "days", "past", "future", "with_cover",
    "douban_sort", "media_source",
}


@router.get("/mp/discover")
def mp_discover(
    request: Request,
    source: str = Query("tmdb_movies"),
    page: int = Query(1, ge=1),
    count: int = Query(20, ge=1, le=50),
    fresh: bool = Query(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_tab(user, db, "discover")
    conn = _mp_conn(db)
    params = {
        key: value
        for key, value in request.query_params.items()
        if key in DISCOVER_FILTER_KEYS
    }

    def load() -> list:
        rows = mp_client(conn).discover_explore(source, page=page, count=count, params=params)
        return [normalize_mp_media(r) for r in rows if isinstance(r, dict)]

    # 上游每次现查 MP→TMDB/豆瓣，较慢；5 分钟内复用，种子页手动刷新带 fresh 旁路
    key = f"mp:discover:{source}:{page}:{count}:{sorted(params.items())}"
    return {"items": cached(conn.id, key, 300.0, load, force=fresh), "page": page}


@router.get("/mp/recommend")
def mp_recommend(
    source: str = "tmdb_trending",
    media_type: Literal["all", "movie", "tv", "music"] = "all",
    page: int = Query(1, ge=1),
    count: int = Query(20, ge=1, le=50),
    fresh: bool = Query(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_tab(user, db, "discover")
    conn = _mp_conn(db)
    client = mp_client(conn)

    def load() -> list:
        if source in RECOMMEND_PATHS:
            rows = client.recommend_section(source, page=page, count=count)
        else:
            rows = client.recommend(
                source=source, media_type=media_type, page=page, count=count
            )
        return [normalize_mp_media(r) for r in rows if isinstance(r, dict)]

    # 推荐页 17 个板块并发拉取，缓存避免每次进页面都整页穿透上游
    key = f"mp:recommend:{source}:{media_type}:{page}:{count}"
    return {"items": cached(conn.id, key, 300.0, load, force=fresh), "page": page}


@router.get("/mp/brush")
def mp_brush(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_tab(user, db, "brush")
    conn = _mp_conn(db)
    try:
        status = cached(conn.id, "mp:brush", 15.0, lambda: mp_client(conn).brush_status())
        return normalize_brush(status)
    except SeedError as e:
        if e.status_code == 404:
            return {
                "available": False,
                "enabled": False,
                "summary": {},
                "tasks": [],
                "message": "MoviePilot 未安装站点刷流插件（BrushFlow）",
            }
        raise


@router.get("/mp/brush/tasks/{task_id}")
def mp_brush_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_tab(user, db, "brush")
    conn = _mp_conn(db)
    return cached(
        conn.id,
        f"mp:brush:task:{task_id}",
        15.0,
        lambda: mp_client(conn).brush_task(task_id),
    )
