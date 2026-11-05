"""影视中心：NAS 本地视频库 / Jellyfin（Emby 大体兼容）媒体服务器。

设计（与音乐中心同构）：
- 配置存系统设置（video_* 键），密码类用 Fernet 加密存储；GET /config 不回传任何密钥
- NAS：扫描容器内挂载目录入 video_items 表（后台线程 + video_scan_state），
  文件名解析电影/剧集（SxxExx、1x02、第x集、EPxx、结尾数字），再叠加同目录 NFO 元数据
  （movie / tvshow / episodedetails，见 services/nfo.py）；不做刮削，
  海报与剧照展示时探测同目录图片（NFO 声明优先；分集回探剧集目录），无则前端渐变占位；
  扫描后按 NFO 里的 TMDB 编号在线补全缺失的海报/剧照（services/tmdb.py，默认启用，
  缓存于 data/video_covers/，失败静默——本地信息与播放不受影响）
- Jellyfin：后端代理（凭据不出服务端），<video> 用 media_key 拉流（static=true 原文件直出，
  Range 透传）；进度上报双写上游（尽力而为）
- 观影进度 video_progress 按用户+源+条目隔离；继续观看：NAS 读本地表，
  Jellyfin 读上游 /Items/Resume（IsResumable）
- 文件名解析 / NFO 叠加 / 在线补全 / 海报剧照探测等算法层在
  services/video_scan_meta.py（本文件只保留路由与请求处理）
- 出站 HTTP / Jellyfin 客户端 / NAS 扫描状态机均复用 app.services 下的共享实现
"""

import json as jsonlib
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_admin, get_current_user, get_media_user
from app.core.sqlutil import escape_like
from app.core.ttlcache import TTLCache
from app.db.helpers import get_or_create
from app.db.session import get_db
from app.db.settings_repo import set_setting
from app.models.user import User
from app.models.video_item import VideoItem
from app.models.video_progress import VideoProgress
from app.schemas.common import ConnectionTestIn, pick
from app.core.errors import UpstreamError
from app.services.jellyfin import VIDEO_JF
from app.services.settings_store import get_cfg, get_cfgs, get_credential, set_credential
from app.services.upstream_http import proxy_stream as _proxy_stream
from app.services import (
    video_scan_meta,
)
from app.services.video_scan_meta import (
    ART_DIR,
    _fanart_list,
    _lazy_fetch_art,
    _pick_art,
    _pick_logo,
    _run_scan,
    _SCAN,
)

router = APIRouter(prefix="/video", tags=["video"])

logger = logging.getLogger(__name__)

_MIME = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm",
    ".mkv": "video/x-matroska", ".mov": "video/quicktime", ".avi": "video/x-msvideo",
    ".wmv": "video/x-ms-wmv", ".mpg": "video/mpeg", ".mpeg": "video/mpeg",
    ".ts": "video/mp2t", ".flv": "video/x-flv", ".rmvb": "application/vnd.rn-realmedia-vbr",
    ".rm": "application/vnd.rn-realmedia",
}

_IMG_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".svg": "image/svg+xml"}


# ---------------- 配置存取 ----------------

def _config_out(db: Session) -> dict:
    v = get_cfgs(db, (
        "video_enabled", "video_source", "video_nas_path", "video_jf_url", "video_jf_user", "video_jf_pass",
        "video_tmdb_proxy", "video_tmdb_api_base", "video_tmdb_image_base",
    ))
    return {
        "enabled": v.get("video_enabled", "") == "true",
        "source": v.get("video_source", "none"),
        "nas_path": v.get("video_nas_path", ""),
        "nas_video_count": db.query(VideoItem.id).count() if v.get("video_nas_path", "") else 0,
        "jf_url": v.get("video_jf_url", ""),
        "jf_user": v.get("video_jf_user", ""),
        "jf_pass_set": bool(v.get("video_jf_pass", "")),
        # 在线补全（TMDB）：Key 回显给管理员（前端掩码显示、点击眼睛可看真实值）；
        # 代理与接口地址可回显
        "tmdb_key": get_credential(db, "video_tmdb_key"),
        "tmdb_key_set": bool(get_credential(db, "video_tmdb_key")),
        "tmdb_proxy": v.get("video_tmdb_proxy", ""),
        # 代理/接口/图片地址的下发取值走 video_scan_meta._tmdb_conf（在线补全共用一份配置）
        "tmdb_api_base": video_scan_meta._tmdb_conf(db)[2],
        "tmdb_image_base": video_scan_meta._tmdb_conf(db)[3],
    }


class VideoConfigIn(BaseModel):
    enabled: bool = False
    source: str = "none"
    nas_path: str | None = None
    jf_url: str | None = None
    jf_user: str | None = None
    jf_pass: str | None = None  # None=不改；空串=清除
    tmdb_key: str | None = None  # 同上；留空（None）保持已存 Key
    tmdb_proxy: str | None = None  # 空串=清除
    tmdb_api_base: str | None = None  # 高级项：接口地址覆盖（默认官方域名）
    tmdb_image_base: str | None = None


@router.get("/config")
def get_video_config(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # 非管理员只下发开关三态：nas_path（服务器目录）、上游地址/账号（内网拓扑）不对普通用户暴露
    if user.role != "admin":
        return {
            "enabled": get_cfg(db, "video_enabled") == "true",
            "source": get_cfg(db, "video_source", "none"),
        }
    return _config_out(db)


@router.put("/config")
def set_video_config(body: VideoConfigIn, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    if body.source not in ("none", "nas", "jellyfin"):
        raise HTTPException(400, "未知的影视源类型")
    set_setting("video_enabled", "true" if body.enabled else "false")
    set_setting("video_source", body.source)
    if body.nas_path is not None:
        set_setting("video_nas_path", body.nas_path.strip()[:1024])
    if body.jf_url is not None:
        set_setting("video_jf_url", body.jf_url.strip()[:1024])
    if body.jf_user is not None:
        set_setting("video_jf_user", body.jf_user.strip()[:256])
    if body.jf_pass is not None:
        set_credential("video_jf_pass", body.jf_pass.strip())
    if body.jf_url is not None or body.jf_user is not None or body.jf_pass is not None:
        VIDEO_JF.clear_tokens()  # 凭据变更后旧 accessToken（改密即被上游吊销）必须重认证
    if body.tmdb_key is not None:
        set_credential("video_tmdb_key", body.tmdb_key.strip())
    if body.tmdb_proxy is not None:
        set_setting("video_tmdb_proxy", body.tmdb_proxy.strip()[:256])
    for field, key in (("tmdb_api_base", "video_tmdb_api_base"), ("tmdb_image_base", "video_tmdb_image_base")):
        value = getattr(body, field)
        if value is None:
            continue
        value = value.strip()[:256]
        if value and not value.startswith(("http://", "https://")):
            raise HTTPException(400, "TMDB 接口地址需以 http(s):// 开头")
        set_setting(key, value)
    return {"ok": True, "config": _config_out(db)}


def _nas_root(db: Session) -> Path:
    root = get_cfg(db, "video_nas_path")
    if not root:
        raise HTTPException(400, "尚未设置视频目录")
    path = Path(root)
    if not path.is_dir():
        raise HTTPException(400, f"视频目录不存在或不可访问：{root}")
    return path


@router.post("/scan")
def scan_library(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    root = _nas_root(db).resolve()
    started, state = _SCAN.begin()
    if not started:
        return {"ok": True, "started": False, "state": state}
    threading.Thread(target=_run_scan, args=(str(root),), daemon=True).start()
    return {"ok": True, "started": True}


@router.get("/scan/status")
def scan_status(admin: User = Depends(get_current_admin)):
    return _SCAN.read()


# ---------------- NAS 浏览 / 流式 / 海报与剧照 ----------------

def _split_names(raw: str) -> list[str]:
    return [x for x in (raw or "").split(",") if x][:8]


def _item_out(it: VideoItem) -> dict:
    return {
        "id": it.id, "kind": it.kind, "title": it.title, "series": it.series,
        "season": it.season, "episode": it.episode, "ep_title": it.ep_title,
        "year": it.year,
        "duration": (it.runtime_min or 0) * 60,
        "has_cover": False,
        "rating": round(it.rating or 0.0, 1),
        "genres": _split_names(it.genres),
        "overview": (it.plot or "")[:200],
    }


def _item_path(db: Session, item_id: int) -> tuple[Path, VideoItem, Path]:
    """(视频文件路径, 行, 媒体根)；只校验行存在与路径仍在根内（不要求文件存在）。"""
    root = _nas_root(db).resolve()
    it = db.get(VideoItem, item_id)
    if it is None:
        raise HTTPException(404, "视频不存在")
    path = (root / it.path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise HTTPException(404, "视频不存在")
    return path, it, root


@router.get("/nas/movies")
def nas_movies(
    q: str = "", page: int = 1, page_size: int = 60,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    page, page_size = max(1, page), max(1, min(page_size, 120))
    query = db.query(VideoItem).filter(VideoItem.kind == "movie")
    if q.strip():
        kw = f"%{escape_like(q.strip()[:100])}%"
        query = query.filter(VideoItem.title.ilike(kw, escape="\\"))
    total = query.with_entities(func.count(VideoItem.id)).scalar() or 0
    rows = (
        query.order_by(VideoItem.title, VideoItem.id)
        .offset((page - 1) * page_size).limit(page_size)
        .with_entities(VideoItem)
        .all()
    )
    return {"total": total, "page": page, "page_size": page_size, "items": [_item_out(r) for r in rows]}


@router.get("/nas/series")
def nas_series(q: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(VideoItem).filter(VideoItem.kind == "episode")
    if q.strip():
        kw = f"%{escape_like(q.strip()[:100])}%"
        query = query.filter(VideoItem.series.ilike(kw, escape="\\"))
    rows = (
        query.with_entities(
            VideoItem.series,
            func.count(VideoItem.id),
            func.min(VideoItem.year),
            func.max(VideoItem.series_rating),
            func.max(VideoItem.series_plot),
            func.max(VideoItem.series_genres),
            # 封面/点开用最新一行的 id（剧集行本体用于图片探测与跳转）
            func.max(VideoItem.id),
        )
        .group_by(VideoItem.series)
        .order_by(VideoItem.series)
        .all()
    )
    season_rows = (
        db.query(VideoItem.series, VideoItem.season)
        .filter(VideoItem.kind == "episode")
        .distinct()
        .all()
    )
    seasons_map: dict[str, list[int]] = {}
    for series, season in season_rows:
        bucket = seasons_map.setdefault(series, [])
        if season not in bucket:
            bucket.append(season)
    items = []
    for series, cnt, year, srating, splot, sgenres, cover_id in rows:
        items.append({
            "series": series, "episode_count": cnt, "year": year or 0,
            "seasons": sorted(seasons_map.get(series, [])),
            "rating": round(float(srating or 0), 1),
            "plot": splot or "",
            "genres": _split_names(sgenres or ""),
            "cover_id": cover_id,
        })
    return {"total": len(items), "items": items}


@router.get("/nas/episodes")
def nas_episodes(series: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not series.strip():
        raise HTTPException(400, "缺少剧集名")
    rows = (
        db.query(VideoItem)
        .filter(VideoItem.kind == "episode", VideoItem.series == series.strip()[:512])
        # season=0（未识别出季）按第 1 季排序，避免 E03 这种裸集号排在 S01 前面
        .order_by(func.coalesce(func.nullif(VideoItem.season, 0), 1), VideoItem.episode, VideoItem.id)
        .with_entities(VideoItem)
        .all()
    )
    progs: dict[str, VideoProgress] = {}
    keys = [str(r.id) for r in rows]
    if keys:
        for p in (
            db.query(VideoProgress)
            .filter(
                VideoProgress.user_id == user.id,
                VideoProgress.source == "nas",
                VideoProgress.item_key.in_(keys),
            )
            .with_entities(VideoProgress)
            .all()
        ):
            progs[p.item_key] = p
    items = []
    resume: dict | None = None
    newest = None
    for r in rows:
        out = _item_out(r)
        p = progs.get(str(r.id))
        if p is not None and p.position > 0:
            # 带进度：时长换成真实播放时长，percent 供前端续播（与继续观看同口径）
            out["position"] = int(p.position)
            if p.duration:
                out["duration"] = int(p.duration)
            out["percent"] = int(p.position * 100 / p.duration) if p.duration else 0
            stamp = p.updated_at or datetime.min
            if newest is None or stamp > newest:
                newest = stamp
                resume = {"id": r.id, "season": r.season, "episode": r.episode}
        items.append(out)
    return {"total": len(items), "items": items, "resume": resume}


def _video_file(db: Session, item_id: int) -> tuple[Path, VideoItem]:
    path, it, _ = _item_path(db, item_id)
    if not path.is_file():
        raise HTTPException(404, "视频文件缺失")
    return path, it


@router.get("/nas/stream/{item_id}")
def nas_stream(item_id: int, user: User = Depends(get_media_user), db: Session = Depends(get_db)):
    # FileResponse（starlette≥0.36）原生按 Range 切片响应，拖进度条即用
    path, it = _video_file(db, item_id)
    return FileResponse(path, media_type=_MIME.get(f".{it.ext.lower()}", "video/mp4"))


def _art_response(path: Path) -> FileResponse:
    mime = _IMG_MIME.get(path.suffix.lower(), "image/jpeg")
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "private, max-age=86400"})


@router.get("/nas/poster/{item_id}")
def nas_poster(item_id: int, user: User = Depends(get_media_user), db: Session = Depends(get_db)):
    """海报：NFO 声明优先，其次同目录 <视频名>-poster.jpg / poster.jpg / folder.jpg 等，
    分集回探剧集目录，最后用在线补全缓存；无则 404，前端回退渐变占位。"""
    path, it, root = _item_path(db, item_id)
    art = _pick_art(path, root, it)
    if art is None:
        raise HTTPException(404, "无海报")
    return _art_response(art)


@router.get("/nas/fanart/{item_id}")
def nas_fanart(item_id: int, i: int = 0, user: User = Depends(get_media_user), db: Session = Depends(get_db)):
    """剧照（宽幅背景图）：fanart / backdrop / background 等命名，规则同海报。
    `?i=` 取第 i 张（详情页多图轮播按索引请求；0 = 第一张，越界 404，前端回退渐变占位）。"""
    path, it, root = _item_path(db, item_id)
    fanarts = _fanart_list(path, root, it)
    if i < 0 or i >= len(fanarts):
        raise HTTPException(404, "无剧照")
    return _art_response(fanarts[i])


@router.get("/nas/logo/{item_id}")
def nas_logo(item_id: int, user: User = Depends(get_media_user), db: Session = Depends(get_db)):
    """标题 Logo（艺术字，多为透明底 PNG）：logo / clearlogo 命名，分集回探剧集目录，
    最后用在线补全缓存；无则 404，前端回退文字标题。"""
    path, it, root = _item_path(db, item_id)
    art = _pick_logo(path, root, it)
    if art is None:
        raise HTTPException(404, "无 Logo")
    return _art_response(art)


def _actors_out(raw: str) -> list[list[str]]:
    try:
        data = jsonlib.loads(raw) if raw else []
    except ValueError:
        return []
    return [row for row in data if isinstance(row, list) and row and row[0]][:24]


@router.get("/nas/detail/{item_id}")
def nas_detail(item_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """详情视图数据：NFO 元数据 + 海报/剧照可用性（前端免发注定 404 的图片请求）。"""
    path, it, root = _item_path(db, item_id)
    out = _item_out(it)
    fanarts = _fanart_list(path, root, it)
    out.update({
        "original_title": it.original_title,
        "plot": it.plot,
        "runtime_min": it.runtime_min,
        "directors": _split_names(it.directors),
        "actors": _actors_out(it.actors),
        "series_plot": it.series_plot,
        "series_rating": round(it.series_rating or 0.0, 1),
        "series_genres": _split_names(it.series_genres),
        "has_poster": _pick_art(path, root, it) is not None,
        "has_fanart": bool(fanarts),
        "fanart_count": len(fanarts),
        "has_logo": _pick_logo(path, root, it) is not None,
    })
    if not out["has_poster"] or not out["has_logo"] or len(fanarts) < 2:
        _lazy_fetch_art(path, root, it)  # 本地缺图（或剧照可再补扩展图）：异步补一次，下次打开即显示
    return out


# ---------------- Jellyfin（Emby 大体兼容） ----------------
# 认证 / 401 重认证 / Items 查询 / 流式打开 / 进度上报全部走共享客户端 VIDEO_JF

_COUNT_CACHE = TTLCache(60.0)  # 库计数 60s 缓存（总览统计防抖）


def _vf_out(it: dict, kind: str) -> dict:
    ticks = it.get("RunTimeTicks") or 0
    img_tags = it.get("ImageTags") or {}
    ud = it.get("UserData") or {}
    pos_ticks = ud.get("PlaybackPositionTicks") or 0
    return {
        "id": it.get("Id"),
        "kind": "episode" if it.get("Type") == "Episode" else kind,
        "title": it.get("SeriesName", "") if it.get("Type") == "Episode" else it.get("Name", ""),
        "series": it.get("SeriesName", ""),
        "season": int(it.get("ParentIndexNumber") or 0),
        "episode": int(it.get("IndexNumber") or 0),
        "ep_title": it.get("Name", "") if it.get("Type") == "Episode" else "",
        "year": int(it.get("ProductionYear") or 0),
        "duration": int(ticks / 10_000_000) if ticks else 0,
        "has_cover": bool(img_tags.get("Primary")),
        "has_fanart": bool(it.get("BackdropImageTags")),
        "fanart_count": len(it.get("BackdropImageTags") or []),
        "has_logo": bool(img_tags.get("Logo")),
        "rating": round(float(it.get("CommunityRating") or 0), 1),
        "genres": [str(g) for g in (it.get("Genres") or [])][:8],
        "position": int(pos_ticks / 10_000_000) if pos_ticks else 0,
        "percent": int(pos_ticks * 100 / ticks) if (pos_ticks and ticks) else 0,
        "overview": (it.get("Overview") or "")[:500],
    }


_VF_LIST_FIELDS = "ProductionYear,Overview,CommunityRating,Genres"


@router.post("/jellyfin/test")
def vf_test(body: ConnectionTestIn, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    url = pick(body.url, get_cfg(db, "video_jf_url")).rstrip("/")
    user = pick(body.user, get_cfg(db, "video_jf_user"))
    pwd = pick(body.password, get_credential(db, "video_jf_pass"))
    if not (url and user and pwd):
        return {"ok": False, "error": "Jellyfin 影视源尚未配置完整"}
    try:
        VIDEO_JF.auth(url, user, pwd)
        return {"ok": True, "server": url}
    except UpstreamError as e:
        return {"ok": False, "error": e.detail}


@router.get("/jf/movies")
def vf_movies(
    q: str = "", page: int = 1, page_size: int = 60,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    page, page_size = max(1, page), max(1, min(page_size, 120))
    extra = {
        "IncludeItemTypes": "Movie", "SortBy": "SortName", "SortOrder": "Ascending",
        "Limit": str(page_size), "StartIndex": str((page - 1) * page_size),
        "Fields": _VF_LIST_FIELDS,
    }
    if q.strip():
        extra["SearchTerm"] = q.strip()[:100]
    data = VIDEO_JF.items(db, extra)
    return {
        "total": int(data.get("TotalRecordCount") or 0),
        "page": page, "page_size": page_size,
        "items": [_vf_out(it, "movie") for it in data.get("Items") or []],
    }


@router.get("/jf/series")
def vf_series(q: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    extra = {
        "IncludeItemTypes": "Series", "SortBy": "SortName", "SortOrder": "Ascending",
        "Limit": "500", "Fields": _VF_LIST_FIELDS,
    }
    if q.strip():
        extra["SearchTerm"] = q.strip()[:100]
    data = VIDEO_JF.items(db, extra)
    # 上游返回非预期形状（错误页/数组）时按 502 回报，不 500
    if not isinstance(data, dict):
        raise HTTPException(502, "Jellyfin 返回了非预期的数据格式")
    items = []
    for it in data.get("Items") or []:
        out = _vf_out(it, "series")
        out["episode_count"] = int(it.get("ChildCount") or 0)
        items.append(out)
    return {"total": len(items), "items": items}


@router.get("/jf/episodes/{series_id}")
def vf_episodes(series_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    status, data = VIDEO_JF.get(db, f"/Shows/{quote(series_id, safe='')}/Episodes?{VIDEO_JF.query({'Fields': _VF_LIST_FIELDS})}")
    if not isinstance(data, dict):
        raise HTTPException(502, "Jellyfin 返回了非预期的数据格式")
    items = [_vf_out(it, "episode") for it in data.get("Items") or []]
    # 上次看到哪集：上游 NextUp（Jellyfin 原生「继续观看」语义）；失败一律静默
    resume = None
    try:
        _, _, uid = VIDEO_JF.token(db)
        _, nxt = VIDEO_JF.get(
            db,
            f"/Shows/NextUp?{VIDEO_JF.query({'UserId': uid, 'SeriesId': series_id, 'Limit': '1'})}",
        )
        nxt_rows = (nxt or {}).get("Items") or []
        if nxt_rows:
            r0 = nxt_rows[0]
            resume = {
                "id": r0.get("Id"),
                "season": int(r0.get("ParentIndexNumber") or 0),
                "episode": int(r0.get("IndexNumber") or 0),
            }
    except UpstreamError:
        resume = None
    return {"total": len(items), "items": items, "resume": resume}


@router.get("/jf/detail/{item_id}")
def vf_detail(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """详情视图数据：上游单条目（简介/类型/演职员/评分）。"""
    data = VIDEO_JF.items(db, {
        "Ids": item_id,
        "Fields": "Overview,Genres,People,CommunityRating,ProductionYear,OriginalTitle",
    })
    if not isinstance(data, dict):
        raise HTTPException(502, "Jellyfin 返回了非预期的数据格式")
    rows = data.get("Items") or []
    if not rows:
        raise HTTPException(404, "条目不存在")
    it = rows[0]
    out = _vf_out(it, "movie")
    directors: list[str] = []
    actors: list[list[str]] = []
    for person in it.get("People") or []:
        name = person.get("Name") or ""
        if not name:
            continue
        if person.get("Type") == "Director":
            if name not in directors:
                directors.append(name)
        elif person.get("Type") == "Actor" and len(actors) < 24:
            pid = person.get("Id") or ""
            thumb = f"/api/v1/video/jf/image/{pid}" if pid and person.get("PrimaryImageTag") else ""
            actors.append([name, person.get("Role") or "", thumb])
    out.update({
        "plot": (it.get("Overview") or "")[:1200],
        "original_title": (it.get("OriginalTitle") or "")[:512],
        "runtime_min": int((it.get("RunTimeTicks") or 0) / 600_000_000) if it.get("RunTimeTicks") else 0,
        "directors": directors[:8],
        "actors": actors,
        "fanart_count": len(it.get("BackdropImageTags") or []),
    })
    return out


@router.get("/jf/stream/{item_id}")
def vf_stream(item_id: str, request: Request, user: User = Depends(get_media_user), db: Session = Depends(get_db)):
    # static=true 原文件直出（与音乐中心同理：不触发上游转码，Range 拖动全程可用）；
    # 令牌被吊销（401）由共享客户端清缓存重认证一次后重开（流式版）
    upstream = VIDEO_JF.open_stream(
        db, f"/Videos/{quote(item_id, safe='')}?static=true", request.headers.get("range")
    )
    return _proxy_stream(upstream, fallback_type="video/mp4")


@router.get("/jf/image/{item_id}")
def vf_image(item_id: str, user: User = Depends(get_media_user), db: Session = Depends(get_db)):
    status, body = VIDEO_JF.get(db, f"/Items/{quote(item_id, safe='')}/Images/Primary?maxWidth=400&quality=85", raw=True)
    if status != 200 or not body:
        raise HTTPException(404, "无封面")
    return Response(content=body, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/jf/backdrop/{item_id}")
def vf_backdrop(item_id: str, i: int = 0, user: User = Depends(get_media_user), db: Session = Depends(get_db)):
    """剧照：`?i=` 取上游第 i 张（详情页多图轮播；越界由上游 404 一并转 404）。"""
    if i < 0 or i > 19:
        raise HTTPException(404, "无剧照")
    status, body = VIDEO_JF.get(db, f"/Items/{quote(item_id, safe='')}/Images/Backdrop/{i}?maxWidth=1600&quality=85", raw=True)
    if status != 200 or not body:
        raise HTTPException(404, "无剧照")
    return Response(content=body, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/jf/logo/{item_id}")
def vf_logo(item_id: str, user: User = Depends(get_media_user), db: Session = Depends(get_db)):
    status, body = VIDEO_JF.get(db, f"/Items/{quote(item_id, safe='')}/Images/Logo?maxWidth=800&quality=90", raw=True)
    if status != 200 or not body:
        raise HTTPException(404, "无 Logo")
    return Response(content=body, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


# ---------------- 首页：继续观看 / 最近添加 ----------------

def _active_source(db: Session) -> str:
    if get_cfg(db, "video_enabled") != "true":
        return "none"
    return get_cfg(db, "video_source", "none")


RESUME_MIN = 30  # 少于 30 秒视为没看
RESUME_MAX_RATIO = 0.95  # 看过 95% 视为看完


@router.get("/resume")
def video_resume(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    source = _active_source(db)
    if source == "nas":
        progs = (
            db.query(VideoProgress)
            .filter(
                VideoProgress.user_id == user.id,
                VideoProgress.source == "nas",
                VideoProgress.position >= RESUME_MIN,
            )
            .order_by(VideoProgress.updated_at.desc())
            .limit(24)
            .with_entities(VideoProgress)
            .all()
        )
        ids = [int(p.item_key) for p in progs if p.item_key.isdigit()]
        item_map = {}
        if ids:
            for it in db.query(VideoItem).filter(VideoItem.id.in_(ids)).with_entities(VideoItem).all():
                item_map[it.id] = it
        items = []
        for prog in progs:
            if not prog.item_key.isdigit():
                continue
            it = item_map.get(int(prog.item_key))
            if it is None:
                continue
            if prog.duration and prog.position / prog.duration >= RESUME_MAX_RATIO:
                continue
            out = _item_out(it)
            out["position"] = int(prog.position)
            out["duration"] = int(prog.duration)
            out["percent"] = int(prog.position * 100 / prog.duration) if prog.duration else 0
            items.append(out)
        return {"source": source, "items": items[:12]}
    if source == "jellyfin":
        data = VIDEO_JF.items(db, {
            "Limit": "12", "IncludeItemTypes": "Movie,Episode", "Filters": "IsResumable",
            "Fields": _VF_LIST_FIELDS,
        })
        items = []
        for it in data.get("Items") or []:
            out = _vf_out(it, "movie")
            pos = out.pop("position", 0)
            out["position"] = pos
            out["percent"] = int(pos * 100 / out["duration"]) if out["duration"] else 0
            items.append(out)
        return {"source": source, "items": items}
    return {"source": "none", "items": []}


def _nas_recent_items(db: Session, limit: int) -> list[dict]:
    """最近添加：电影逐条；剧集按剧名聚合为一条（新集入库时该剧整体上浮），混排后取前 limit。

    剧集条目用最新一集的 id 作封面/代表（id 为数字，可直接走海报与在线补全链路）。
    """
    movies = (
        db.query(VideoItem)
        .filter(VideoItem.kind == "movie")
        .order_by(VideoItem.created_at.desc(), VideoItem.id.desc())
        .limit(limit)
        .with_entities(VideoItem)
        .all()
    )
    series_rows = (
        db.query(
            VideoItem.series,
            func.count(VideoItem.id),
            func.max(VideoItem.created_at),
            func.max(VideoItem.id),
            func.max(VideoItem.series_rating),
            func.max(VideoItem.series_genres),
            func.min(VideoItem.year),
            func.max(VideoItem.series_plot),
        )
        .filter(VideoItem.kind == "episode")
        .group_by(VideoItem.series)
        .order_by(func.max(VideoItem.created_at).desc())
        .limit(limit)
        .all()
    )
    merged: list[tuple[datetime, dict]] = [
        (m.created_at, _item_out(m)) for m in movies
    ]
    for series, cnt, added, cover_id, srating, sgenres, year, splot in series_rows:
        merged.append((
            added,
            {
                "id": cover_id, "kind": "series", "title": series, "series": series,
                "season": 0, "episode": 0, "ep_title": "",
                "year": year or 0, "duration": 0, "has_cover": False,
                "rating": round(float(srating or 0), 1),
                "genres": _split_names(sgenres or ""),
                "plot": splot or "",  # 与 /nas/series 同口径：详情页「最近添加」入口也显示剧集简介
                "overview": f"共 {cnt} 集",
                "episode_count": cnt,
            },
        ))
    merged.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in merged[:limit]]


@router.get("/recent")
def video_recent(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    source = _active_source(db)
    limit = 12
    if source == "nas":
        return {"source": source, "items": _nas_recent_items(db, limit)}
    if source == "jellyfin":
        # 剧集用 Series 类型：一部剧只出现一次（Episode 会逐集刷屏）
        data = VIDEO_JF.items(db, {
            "IncludeItemTypes": "Movie,Series", "SortBy": "DateCreated",
            "SortOrder": "Descending", "Limit": str(limit),
            "Fields": _VF_LIST_FIELDS,
        })
        items = []
        for it in data.get("Items") or []:
            out = _vf_out(it, "series" if it.get("Type") == "Series" else "movie")
            if it.get("Type") == "Series" and it.get("ChildCount"):
                out["episode_count"] = int(it.get("ChildCount") or 0)
            items.append(out)
        return {"source": source, "items": items}
    return {"source": "none", "items": []}


# ---------------- 观影进度 ----------------

class VideoProgressIn(BaseModel):
    source: str
    key: str
    position: float = 0
    duration: float = 0


def _get_or_create_progress(db: Session, user_id: int, source: str, key: str) -> VideoProgress:
    """播放心跳(10s)与 stop 并发首发同一新条目时由 get_or_create 兜住唯一约束冲突。"""
    return get_or_create(db, VideoProgress, user_id=user_id, source=source, item_key=key)


@router.post("/progress")
def report_progress(body: VideoProgressIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.source not in ("nas", "jellyfin") or not body.key.strip():
        raise HTTPException(400, "参数不完整")
    key = body.key.strip()[:512]
    row = _get_or_create_progress(db, user.id, body.source, key)
    row.position = max(0.0, min(float(body.position), 100_000_000.0))
    if body.duration:
        row.duration = max(0.0, min(float(body.duration), 1_000_000.0))
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    if body.source == "jellyfin":
        VIDEO_JF.post_progress(db, key, row.position, stopped=False)
    return {"ok": True}


@router.post("/progress/stop")
def report_stopped(body: VideoProgressIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """停止播放：本地进度照记；Jellyfin 源额外告知上游（会话收尾，恢复列表口径一致）。"""
    if body.source not in ("nas", "jellyfin") or not body.key.strip():
        raise HTTPException(400, "参数不完整")
    key = body.key.strip()[:512]
    row = _get_or_create_progress(db, user.id, body.source, key)
    row.position = max(0.0, min(float(body.position), 100_000_000.0))
    if body.duration:
        row.duration = max(0.0, min(float(body.duration), 1_000_000.0))
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    if body.source == "jellyfin":
        VIDEO_JF.post_progress(db, key, row.position, stopped=True)
    return {"ok": True}


# ---------------- 总览统计辅助 ----------------

def library_video_count(db: Session) -> int:
    """总览用户卡「影视」计数：nas=表计数；jellyfin=TotalRecordCount（60s 缓存防抖）。失败计 0。"""
    source = _active_source(db)
    if source == "nas":
        try:
            return db.query(VideoItem.id).count()
        except Exception:
            return 0
    if source == "jellyfin":
        cached = _COUNT_CACHE.get("jf")
        if cached is not None:
            return cached
        try:
            data = VIDEO_JF.items(db, {"IncludeItemTypes": "Movie,Episode", "Limit": "0"})
            n = int(data.get("TotalRecordCount") or 0)
            _COUNT_CACHE.put("jf", n)
            return n
        except Exception:
            return 0
    return 0
