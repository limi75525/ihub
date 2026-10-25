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
- 出站 HTTP / Jellyfin 客户端 / NAS 扫描状态机均复用 app.services 下的共享实现
"""

import json as jsonlib
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_admin, get_current_user, get_media_user
from app.core.sqlutil import escape_like
from app.core.ttlcache import TTLCache
from app.db.helpers import get_or_create
from app.db.session import SessionLocal, get_db
from app.models.system_setting import set_setting
from app.models.user import User
from app.models.video_item import VideoItem
from app.models.video_progress import VideoProgress
from app.schemas.common import ConnectionTestIn, pick
from app.services import media_scan, nfo, tmdb
from app.services.jellyfin import VIDEO_JF
from app.services.settings_store import get_cfg, get_cfgs, get_credential, set_credential
from app.services.upstream_http import proxy_stream as _proxy_stream
from app.core import data_dirs

router = APIRouter(prefix="/video", tags=["video"])

logger = logging.getLogger(__name__)

VIDEO_EXTS = {".mp4", ".m4v", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".mpg", ".mpeg", ".ts", ".flv", ".rmvb", ".rm"}
SCAN_STATE_KEY = "video_scan_state"
SCANNER_VERSION = 2  # 2：NFO 元数据 + TMDB 编号（升级后首扫全量重解析补齐新字段）
ART_DIR = settings.DATA_DIR / data_dirs.VIDEO_COVERS  # 在线补全的海报/剧照缓存（不回写媒体目录）
ARTWORK_DELAY = 0.25  # 相邻两部影片补全之间的间隔（对上游温柔一点）

# 海报/剧照探测：自身目录先试「文件名主干」变体，再试通用名；分集向剧集目录回探若干层
_PIC_EXTS = (".jpg", ".jpeg", ".png", ".webp")
_GENERIC_POSTER = ("poster", "folder", "cover", "default", "movie", "tvshow", "show")
_GENERIC_FANART = ("fanart", "backdrop", "background", "thumb")
_MAX_ANCESTORS = 3

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
        "tmdb_api_base": v.get("video_tmdb_api_base", ""),
        "tmdb_image_base": v.get("video_tmdb_image_base", ""),
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


def _tmdb_conf(db: Session) -> tuple[str, str, str, str]:
    """(api_key, proxy, api_base, image_base)——Key 缺失时在线补全整体跳过。"""
    v = get_cfgs(db, ("video_tmdb_api_base", "video_tmdb_image_base"))
    # 代理不再取 video_tmdb_proxy（已废弃）：tmdb.py 按请求 URL 自动匹配全局出站代理
    return (
        get_credential(db, "video_tmdb_key"),
        "",
        v.get("video_tmdb_api_base", "") or tmdb.API_DEFAULT,
        v.get("video_tmdb_image_base", "") or tmdb.IMAGE_DEFAULT,
    )


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


# ---------------- 文件名解析（无刮削） ----------------

_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
_JUNK_RE = re.compile(
    r"(?i)(1080[pi]|720p|2160p|480p|4k|uhd|bluray|blu-ray|bdrip|web-?dl|webrip|hdtv|hdrip|"
    r"dvdrip|remux|hdr(10)?|dolby|vision|x264|x265|h\.?264|h\.?265|hevc|avc|aac|flac|dts|"
    r"ac3|eac3|10bit|8bit|60fps|简繁|简体|繁体|中字|国语|粤语|双语|高清|完整版|无水印|正片)"
)
_BRACKET_RE = re.compile(r"[【\[][^】\]]*[】\]]")
_SEASON_DIR_RE = re.compile(r"(?i)^(season\s*\d+|s\d{1,2}|第\s*\d+\s*[季部])$")
# 匹配优先级从高到低：SxxExx > 1x02 > 第x集 > EPxx > Exx > 「标题 - 数字」（动画组命名）。
# 末位兜底必须带连字符：District 9 / Apollo 13 这类数字结尾的电影不能被误判成剧集
_EP_PATTERNS = [
    (re.compile(r"[Ss](\d{1,2})\s?[Ee](\d{1,3})"), "se"),
    (re.compile(r"(?<!\d)(\d{1,2})x(\d{1,3})(?!\d)"), "se"),
    (re.compile(r"第\s*(\d{1,4})\s*[集话話]"), "e"),
    (re.compile(r"(?:^|[^a-zA-Z0-9])[Ee][Pp]\.?(\d{1,3})(?:[^a-zA-Z0-9]|$)"), "e"),
    (re.compile(r"(?:^|[^a-zA-Z0-9])[Ee](\d{1,3})(?:[^a-zA-Z0-9]|$)"), "e"),
    (re.compile(r"-\s*(\d{1,3})\s*$"), "e"),
]


def _clean_title(s: str) -> str:
    s = _BRACKET_RE.sub(" ", s)
    s = _JUNK_RE.sub(" ", s)
    s = _YEAR_RE.sub(" ", s)
    s = re.sub(r"[()（）]", " ", s)
    s = s.replace(".", " ").replace("_", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip(" -~·.:：,，")


def _series_fallback(rel: str) -> str:
    """父目录名回退剧名/片名；跳过 Season1 / S01 / 第1季 这类季目录。"""
    for name in reversed(Path(rel).parent.parts):
        if name and not _SEASON_DIR_RE.match(name.strip()):
            cleaned = _clean_title(name)
            if cleaned:
                return cleaned
    return ""


def _parse_video_name(rel: str) -> dict:
    """从相对路径解析 kind/title/series/season/episode/year（无刮削，纯文件名启发式）。

    剧集：匹配到集号 → kind=episode，标记前段为剧名；剧名为空时回退目录名（跳过季目录）。
    电影：其余全部按 movie，title=清理后的文件名；清理后为空回退目录名。
    """
    stem = Path(rel).stem
    year_m = _YEAR_RE.search(stem)
    year = int(year_m.group(1)) if year_m else 0
    # 先清理再匹配集号：否则尾部 [1080p] 等方括号标签会挡住「标题 - 数字」兜底
    cleaned = _clean_title(stem)
    season = episode = 0
    matched = None
    for rx, mode in _EP_PATTERNS:
        m = rx.search(cleaned)
        if not m:
            continue
        matched = m
        if mode == "se":
            season, episode = int(m.group(1)), int(m.group(2))
        else:
            episode = int(m.group(1))
        break
    if matched:  # 剧集
        head = cleaned[: matched.start()].strip(" -~·.:：,，")
        tail = cleaned[matched.end():].strip(" -~·.:：,，")
        series = head or _series_fallback(rel) or "未知剧集"
        return {
            "kind": "episode", "title": series, "series": series,
            "season": season, "episode": episode, "ep_title": tail[:512],
            "year": year,
        }
    title = cleaned or _series_fallback(rel) or stem
    return {
        "kind": "movie", "title": title[:512], "series": "",
        "season": 0, "episode": 0, "ep_title": "", "year": year,
    }


# ---------------- NFO 元数据（services/nfo.py 解析，叠加在文件名启发式之上） ----------------

def _season_nfo(own: Path) -> Path | None:
    """季目录里的季级 NFO：`season.nfo` / `<季目录名>.nfo` / `seasonNN.nfo`（Emby/Jellyfin 常见命名）。

    只做候选发现——文件语义由根元素决定（parse_file 按 `<season>`/`<movie>` 等分派），
    因此对电影目录同名的 `<目录名>.nfo` 也安全（会按 `<movie>` 解析）。
    """
    try:
        entries = {p.name.lower(): p for p in own.iterdir() if p.is_file() and p.suffix.lower() == ".nfo"}
    except OSError:
        return None
    for name in ("season.nfo", f"{own.name}.nfo".lower()):
        if name in entries:
            return entries[name]
    for name in sorted(entries):
        if re.match(r"^season\s*\d+\.nfo$", name):
            return entries[name]
    return None


def _nfo_paths(video: Path, root: Path) -> list[Path]:
    """候选 NFO（有序、去重）：同名 .nfo → movie.nfo → 向上找 tvshow.nfo → 季级 nfo（兜底）。"""
    cands: list[Path] = []
    for cand in (video.parent / f"{video.stem}.nfo", video.parent / "movie.nfo"):
        try:
            if cand.is_file():
                cands.append(cand)
                break
        except OSError:
            continue
    cur = video.parent
    while True:
        show = cur / "tvshow.nfo"
        try:
            if show.is_file():
                cands.append(show)
                break
        except OSError:
            pass
        if cur == root:
            break
        parent = cur.parent
        try:
            parent.relative_to(root)
        except ValueError:
            break
        cur = parent
    season = _season_nfo(video.parent)
    if season is not None and season not in cands:
        cands.append(season)
    return cands


def _nfo_sig_pairs(video: Path, root: Path) -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for cand in _nfo_paths(video, root):
        sig = nfo.nfo_sig(cand)
        if sig:
            out.append((cand, sig))
    return out


def _fmt_sig(pairs: list[tuple[Path, str]]) -> str:
    # 签名含路径文件名与 mtime/size：NFO 新增、删除、被刮削器重写都会变化
    return "|".join(f"{cand.name}:{sig}" for cand, sig in pairs)[:256]


def _nfo_meta(video: Path, root: Path) -> tuple[dict, str]:
    """合并候选 NFO 的元数据（前一个文件的非空字段优先）并返回增量签名。"""
    pairs = _nfo_sig_pairs(video, root)
    meta: dict = {}
    for cand, _ in pairs:
        for key, value in nfo.parse_file(cand).items():
            if value and not meta.get(key):
                meta[key] = value
    return meta, _fmt_sig(pairs)


# ---------------- NAS 扫描（后台线程，共享引擎 app.services.media_scan） ----------------

_SCAN = media_scan.ScanStateStore(SCAN_STATE_KEY)


def _nas_root(db: Session) -> Path:
    root = get_cfg(db, "video_nas_path")
    if not root:
        raise HTTPException(400, "尚未设置视频目录")
    path = Path(root)
    if not path.is_dir():
        raise HTTPException(400, f"视频目录不存在或不可访问：{root}")
    return path


def _parse_video_file(path: Path, rel: str, st, root: Path) -> dict:
    meta = _parse_video_name(rel)
    nfo_meta, sig = _nfo_meta(path, root)
    meta["meta_sig"] = sig
    if meta["kind"] == "movie":
        if nfo_meta.get("title"):
            meta["title"] = nfo_meta["title"]
        if nfo_meta.get("year"):
            meta["year"] = nfo_meta["year"]
        for key in (
            "original_title", "plot", "genres", "directors", "actors",
            "poster_ref", "fanart_ref", "tmdb_id",
        ):
            meta[key] = nfo_meta.get(key) or ""
        meta["series_tmdb_id"] = ""
        meta["runtime_min"] = nfo_meta.get("runtime_min") or 0
        meta["rating"] = nfo_meta.get("rating") or 0.0
    else:
        if nfo_meta.get("ep_title"):
            meta["ep_title"] = nfo_meta["ep_title"]
        meta["plot"] = nfo_meta.get("plot") or ""
        meta["tmdb_id"] = ""
        meta["runtime_min"] = nfo_meta.get("runtime_min") or 0
        meta["rating"] = nfo_meta.get("rating") or 0.0
        meta["series_plot"] = nfo_meta.get("series_plot") or ""
        meta["series_rating"] = nfo_meta.get("series_rating") or 0.0
        meta["series_genres"] = nfo_meta.get("series_genres") or ""
        meta["series_tmdb_id"] = nfo_meta.get("series_tmdb_id") or ""
    meta.update(path=rel, ext=path.suffix.lower().lstrip("."), size=st.st_size, mtime=int(st.st_mtime))
    return meta


def _apply_video_meta(row: VideoItem, meta: dict) -> None:
    for k, v in meta.items():
        setattr(row, k, v)


def _run_scan(root_str: str) -> None:
    root = Path(root_str).resolve()
    rescan_all = _SCAN.read().get("scanner_version") != SCANNER_VERSION
    files = media_scan.walk_media_files(
        root, VIDEO_EXTS, skip_name=lambda fn: fn.startswith(".") or "sample" in fn.lower()
    )
    media_scan.run_media_scan(
        store=_SCAN,
        model=VideoItem,
        root=root,
        files=files,
        parse=lambda path, rel, st: _parse_video_file(path, rel, st, root),
        apply_meta=_apply_video_meta,
        force_parse=rescan_all,
        # 增量键 = 视频 mtime:size + NFO 签名：视频没动、刮削器重写 NFO 时同样触发重新解析
        signature=lambda path, st: f"{int(st.st_mtime)}:{st.st_size}|{_fmt_sig(_nfo_sig_pairs(path, root))}",
        row_signature=lambda row: f"{row.mtime}:{row.size}|{row.meta_sig or ''}",
        done_extra={"scanner_version": SCANNER_VERSION},
    )
    try:
        _enrich_online_art(root)
    except Exception as e:
        # 补全阶段的意外异常不能把状态卡在 running（否则下一次扫描会被「已在运行」拒绝）
        logger.exception("影视在线补全阶段异常")
        _SCAN.write(running=False, phase="done", finished_at=int(time.time()))
        from app.services import notify_service

        notify_service.background_notify_admins(
            type="service_failed",
            title="影视在线补全失败",
            body=f"影视 TMDB 在线补全阶段异常：{str(e)[:300]}",
            dedup_key=f"video-artwork:{int(time.time() // 86400)}",
        )
        return
    from app.services import notify_service

    notify_service.background_notify_admins(
        type="scan_done",
        title="影视库扫描完成",
        body="影视库扫描与在线补全已完成，新增或更新的条目已在影视中心可见。",
        link="#/video",
        dedup_key=f"scan-video:{int(time.time() // 60)}",
    )


# ---------------- 在线补全（TMDB 海报/剧照：默认启用、失败静默、缓存于 data/video_covers） ----------------

_LAZY_LOCK = threading.Lock()
_LAZY_FETCHING: set[tuple[str, str]] = set()


def _art_key(it: VideoItem) -> tuple[str, str]:
    """条目的补全键：电影用自身 TMDB 编号；分集用 tvshow.nfo 的剧集编号（海报全剧共用）。"""
    if it.kind == "movie":
        return "movie", it.tmdb_id or ""
    return "tv", it.series_tmdb_id or ""


def _art_wants(path: Path, root: Path, it: VideoItem, kind: str, tmdb_id: str) -> tuple[bool, bool, bool]:
    """还缺且本地没有的三类图（海报/剧照/Logo）——本地永远优先，已有本地图就不下载同类。
    剧照特殊：本地无图时补一次（主图 + 最多 FANART_MAX 张扩展图），`bd-tried-*` 标记落盘后不再重试；
    网络失败不落标记（下轮会再试），上游确实没有剧照则落标记（避免每轮扫描反复请求）。"""
    want_poster = tmdb.cache_path(ART_DIR, kind, tmdb_id, "poster") is None and _pick_art(path, root, it, fanart=False) is None
    want_backdrop = not _local_fanarts(path, root, it) and not tmdb.backdrop_tried(ART_DIR, kind, tmdb_id)
    want_logo = tmdb.cache_path(ART_DIR, kind, tmdb_id, "logo") is None and _pick_logo(path, root, it) is None
    return want_poster, want_backdrop, want_logo


def _art_plan(root: Path, items: list[VideoItem]) -> list[tuple[str, str, tuple[bool, bool, bool]]]:
    """扫描后要补全的目标：去重，逐类给出还缺的图（三类都齐的整条跳过）。"""
    plan: list[tuple[str, str, tuple[bool, bool, bool]]] = []
    seen: set[tuple[str, str]] = set()
    for it in items:
        kind, tmdb_id = _art_key(it)
        if not tmdb_id:
            continue
        key = (kind, tmdb_id)
        if key in seen:
            continue
        seen.add(key)
        path = root / it.path
        try:
            path.resolve().relative_to(root)
        except (OSError, ValueError):
            continue
        wants = _art_wants(path, root, it, kind, tmdb_id)
        if not any(wants):
            continue
        plan.append((kind, tmdb_id, wants))
    return plan


def _needs_online_art(path: Path, root: Path, it: VideoItem) -> bool:
    """条目是否还有本地拿不到的图（决定「无编号条目」值不值得做标题匹配）。"""
    return (
        _pick_art(path, root, it, fanart=False) is None
        or not _local_fanarts(path, root, it)
        or _pick_logo(path, root, it) is None
    )


_SEASON_TITLE_RE = re.compile(
    r"^\s*(第\s*[0-9一二三四五六七八九十百千]+\s*[季部]|season\s*\d+|s\d{1,2}|specials?)\s*$", re.IGNORECASE
)


def _series_match_hints(path: Path, root: Path, it: VideoItem) -> tuple[list[str], int]:
    """标题自动匹配的候选（按优先级）：tvshow.nfo 标题/原名 → 季级 nfo 标题（过滤「第 N 季」这类
    通用标题）→ 目录名解析出的剧名；年份取季 nfo/行内值。"""
    meta, _ = _nfo_meta(path, root)
    titles: list[str] = []
    for key in ("series_title", "series_original_title", "season_title"):
        value = (meta.get(key) or "").strip()
        if value and value not in titles and not _SEASON_TITLE_RE.match(value):
            titles.append(value)
    if it.series and it.series not in titles:
        titles.append(it.series)
    try:
        year = int(meta.get("series_year") or 0)
    except (TypeError, ValueError):
        year = 0
    return titles[:3], year or (it.year or 0)


def _resolve_item_id(db: Session, it: VideoItem, path: Path, root: Path) -> str | None:
    """NFO 无编号时的兜底：按标题+年份自动匹配 TMDB 编号（宁缺毋滥，歧义宁可放弃）。
    标题候选优先取 NFO（tvshow/季级 nfo 标题），无则目录名剧名；成功落库（不写回 NFO）；
    分集同剧一次匹配全体落库，避免逐集重查；失败静默返回 None。"""
    if it.kind == "movie":
        titles = [t for t in (it.title, it.original_title) if t]
        year = it.year or 0
    else:
        titles, year = _series_match_hints(path, root, it)
    if not titles:
        return None
    api_key, proxy, api_base, _ = _tmdb_conf(db)
    if not api_key:
        return None
    tmdb_id = tmdb.resolve_id(api_base, it.kind, titles, year, api_key, proxy)
    if not tmdb_id:
        return None
    if it.kind == "movie":
        it.tmdb_id = tmdb_id
    else:
        it.series_tmdb_id = tmdb_id
        if it.series:
            for row in (
                db.query(VideoItem)
                .filter(VideoItem.kind != "movie", VideoItem.series == it.series)
                .all()
            ):
                if not row.series_tmdb_id:
                    row.series_tmdb_id = tmdb_id
    db.commit()
    return tmdb_id


def _enrich_online_art(root: Path) -> None:
    """扫描后的在线补全阶段：清理失效缓存 → 无编号条目标题匹配 → 逐条补缺失的海报/剧照。"""
    db = SessionLocal()
    try:
        items = db.query(VideoItem).with_entities(VideoItem).all()
        api_key, proxy, api_base, image_base = _tmdb_conf(db)
        _SCAN.write(running=True, phase="artwork", art_total=0, art_done=0, art_failed=0)
        if api_key:
            # 无编号兜底：标题+年份匹配 TMDB 编号（只补图用；本地三件套齐全的条目跳过，不做无谓搜索）
            tried: set[tuple[str, str]] = set()
            for it in items:
                kind, tmdb_id = _art_key(it)
                if tmdb_id:
                    continue
                path = root / it.path
                try:
                    path.resolve().relative_to(root)
                except (OSError, ValueError):
                    continue
                if not _needs_online_art(path, root, it):
                    continue
                title = it.title if it.kind == "movie" else (it.series or it.title)
                key = (kind, title)
                if key in tried:
                    continue
                tried.add(key)
                _resolve_item_id(db, it, path, root)
                time.sleep(ARTWORK_DELAY)
    finally:
        db.close()
    valid: set[tuple[str, str]] = set()
    for it in items:
        kind, tmdb_id = _art_key(it)
        if tmdb_id:
            valid.add((kind, tmdb_id))
    tmdb.prune_cache(ART_DIR, valid)
    plan = _art_plan(root, items) if api_key else []
    _SCAN.write(running=True, phase="artwork", art_total=len(plan), art_done=0, art_failed=0)
    failed = 0
    for i, (kind, tmdb_id, wants) in enumerate(plan):
        result = tmdb.fetch_art(
            ART_DIR, kind, tmdb_id, api_key, proxy, api_base, image_base,
            want_poster=wants[0], want_backdrop=wants[1], want_logo=wants[2],
        )
        if not any(r for r, w in zip(result, wants) if w):
            failed += 1  # 上游对某些条目可能没有某类图（如剧集无剧照），只要有一类成功就不算失败
        _SCAN.write(art_done=i + 1, art_failed=failed)
        time.sleep(ARTWORK_DELAY)
    _SCAN.write(running=False, phase="done", art_failed=failed, finished_at=int(time.time()))


def _lazy_fetch_art(path: Path, root: Path, it: VideoItem) -> None:
    """详情页发现缺图时的单条异步补全（同键去重；扫描进行中交给扫描阶段处理）。
    NFO 无编号的条目先在后台做标题匹配（成功落库），再补图。"""
    kind, tmdb_id = _art_key(it)
    if _SCAN.read().get("running"):
        return
    if tmdb_id:
        wants = _art_wants(path, root, it, kind, tmdb_id)
        if not any(wants):
            return
    elif not _needs_online_art(path, root, it):
        return
    key = (kind, tmdb_id or f"#resolve-{it.id}")
    with _LAZY_LOCK:
        if key in _LAZY_FETCHING:
            return
        _LAZY_FETCHING.add(key)

    def run() -> None:
        db = SessionLocal()
        try:
            row = db.get(VideoItem, it.id)
            if row is None:
                return
            api_key, proxy, api_base, image_base = _tmdb_conf(db)
            if not api_key:
                return
            k, tid = _art_key(row)
            if not tid:
                tid = _resolve_item_id(db, row, path, root)  # 标题匹配（内部 commit；失败返回 None）
                k = _art_key(row)[0]
            if not tid:
                return
            wants = _art_wants(path, root, row, k, tid)
            if any(wants):
                tmdb.fetch_art(
                    ART_DIR, k, tid, api_key, proxy, api_base, image_base,
                    want_poster=wants[0], want_backdrop=wants[1], want_logo=wants[2],
                )
        finally:
            db.close()
            with _LAZY_LOCK:
                _LAZY_FETCHING.discard(key)

    threading.Thread(target=run, daemon=True).start()


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


def _dir_images(directory: Path) -> dict[str, Path]:
    """目录内图片：小写文件名 → 路径（列目录一次，多候选匹配零额外 IO）。"""
    out: dict[str, Path] = {}
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    if entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.lower() in _PIC_EXTS:
                        out.setdefault(entry.name.lower(), Path(entry.name))
                except OSError:
                    continue
    except OSError:
        return {}
    return out


def _local_fanarts(item_path: Path, root: Path, it: VideoItem) -> list[Path]:
    """本地剧照命中（按优先级全收，最多 FANART_MAX 张）：NFO 引用 → 自身目录文件名主干 →
    通用名（fanart/backdrop/…）→（分集）剧集目录回探。所有命中要求解析后仍在媒体根内。"""
    stem = Path(it.path).stem
    own = item_path.parent
    own_stems = [f"{stem}-fanart", f"{stem}-backdrop"]
    if it.kind == "episode":
        own_stems += [f"{own.name}-fanart", f"{own.name}-backdrop", own.name]
    bases: list[tuple[Path, tuple[str, ...]]] = [(own, (*own_stems, *_GENERIC_FANART))]
    if it.kind == "episode":
        cur = own
        for _ in range(_MAX_ANCESTORS):
            if cur == root:
                break
            parent = cur.parent
            try:
                parent.relative_to(root)
            except ValueError:
                break
            cur = parent
            bases.append((cur, (f"{cur.name}-fanart", f"{cur.name}-backdrop", cur.name, *_GENERIC_FANART)))

    out: list[Path] = []
    seen: set[str] = set()

    def add(cand: Path) -> None:
        try:
            cand = cand.resolve()
            cand.relative_to(root)
            if not cand.is_file():
                return
        except (OSError, ValueError):
            return
        key = str(cand).lower()
        if key in seen:
            return
        seen.add(key)
        out.append(cand)

    if it.fanart_ref:
        add(own / it.fanart_ref)
    for directory, stems in bases:
        images = _dir_images(directory)
        if not images:
            continue
        for name in stems:
            for ext in _PIC_EXTS:
                hit = images.get((name + ext).lower())
                if hit is not None:
                    add(directory / hit)
        if len(out) >= tmdb.FANART_MAX:
            break
    return out[:tmdb.FANART_MAX]


def _fanart_list(item_path: Path, root: Path, it: VideoItem) -> list[Path]:
    """详情页 hero 轮播的剧照列表：本地命中在前（按优先级），其后接在线缓存（主图 + 扩展图）。"""
    out = list(_local_fanarts(item_path, root, it))
    seen = {str(p).lower() for p in out}
    cache_kind, tmdb_id = _art_key(it)
    if tmdb_id:
        for p in tmdb.cached_arts(ART_DIR, cache_kind, tmdb_id, "backdrop"):
            key = str(p).lower()
            if key not in seen:
                seen.add(key)
                out.append(p)
    return out[:tmdb.FANART_MAX]


def _pick_art(item_path: Path, root: Path, it: VideoItem, fanart: bool) -> Path | None:
    """海报/剧照探测：NFO 声明引用 → 自身目录文件名主干 → 通用名 →（分集）剧集目录回探 →
    在线补全缓存（data/video_covers）。剧照取轮播列表第一张（完整列表见 `_fanart_list`）。

    所有本地命中都要求解析后仍在媒体根内（目录里放符号链接不能把根外文件带出去）。
    """
    if fanart:
        fanarts = _fanart_list(item_path, root, it)
        return fanarts[0] if fanarts else None
    kind = it.kind
    stem = Path(it.path).stem
    ref = it.fanart_ref if fanart else it.poster_ref
    if fanart:
        stem_names = (f"{stem}-fanart", f"{stem}-backdrop")
        generic = _GENERIC_FANART
    else:
        stem_names = (f"{stem}-poster", stem)
        generic = _GENERIC_POSTER

    if ref:
        try:
            cand = (item_path.parent / ref).resolve()
            cand.relative_to(root)
            if cand.is_file():
                return cand
        except (OSError, ValueError):
            pass

    own = item_path.parent
    own_stems = list(stem_names)
    if kind == "episode":
        # 分集自身目录可能直接就是剧集目录：<剧名>-poster.jpg / <剧名>.jpg 也要覆盖
        if fanart:
            own_stems += [f"{own.name}-fanart", f"{own.name}-backdrop", own.name]
        else:
            own_stems += [f"{own.name}-poster", own.name]
    bases: list[tuple[Path, tuple[str, ...]]] = [(own, (*own_stems, *generic))]
    if kind == "episode":
        cur = own
        for _ in range(_MAX_ANCESTORS):
            if cur == root:
                break
            parent = cur.parent
            try:
                parent.relative_to(root)
            except ValueError:
                break
            cur = parent
            if fanart:
                anc_stems = (f"{cur.name}-fanart", f"{cur.name}-backdrop", cur.name, *generic)
            else:
                anc_stems = (f"{cur.name}-poster", cur.name, *generic)
            bases.append((cur, anc_stems))

    for directory, stems in bases:
        images = _dir_images(directory)
        if not images:
            continue
        for name in stems:
            for ext in _PIC_EXTS:
                hit = images.get((name + ext).lower())
                if hit is None:
                    continue
                cand = directory / hit
                try:
                    cand.resolve().relative_to(root)
                except (OSError, ValueError):
                    continue
                return cand
    # 本地无图：用在线补全的缓存（data/video_covers，不回写媒体目录）
    cache_kind, tmdb_id = _art_key(it)
    if tmdb_id:
        cached = tmdb.cache_path(ART_DIR, cache_kind, tmdb_id, "backdrop" if fanart else "poster")
        if cached is not None:
            return cached
    return None


_LOGO_STEMS = ("logo", "clearlogo")


def _pick_logo(item_path: Path, root: Path, it: VideoItem) -> Path | None:
    """标题 Logo（艺术字）：同目录 logo/clearlogo（含 <片名>-logo 变体），分集回探剧集目录，
    最后用在线补全缓存；无则 404，前端回退文字标题。所有本地命中同样要求留在媒体根内。"""
    stem = Path(it.path).stem
    own = item_path.parent
    own_stems = [f"{stem}-logo", f"{stem}-clearlogo", *_LOGO_STEMS]
    if it.kind == "episode":
        own_stems += [f"{own.name}-logo", f"{own.name}-clearlogo"]
    bases: list[tuple[Path, tuple[str, ...]]] = [(own, tuple(own_stems))]
    if it.kind == "episode":
        cur = own
        for _ in range(_MAX_ANCESTORS):
            if cur == root:
                break
            parent = cur.parent
            try:
                parent.relative_to(root)
            except ValueError:
                break
            cur = parent
            bases.append((cur, (f"{cur.name}-logo", f"{cur.name}-clearlogo", *_LOGO_STEMS)))
    for directory, stems in bases:
        images = _dir_images(directory)
        if not images:
            continue
        for name in stems:
            for ext in _PIC_EXTS:
                hit = images.get((name + ext).lower())
                if hit is None:
                    continue
                cand = directory / hit
                try:
                    cand.resolve().relative_to(root)
                except (OSError, ValueError):
                    continue
                return cand
    cache_kind, tmdb_id = _art_key(it)
    if tmdb_id:
        cached = tmdb.cache_path(ART_DIR, cache_kind, tmdb_id, "logo")
        if cached is not None:
            return cached
    return None


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
    art = _pick_art(path, root, it, fanart=False)
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
        "has_poster": _pick_art(path, root, it, fanart=False) is not None,
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
    except HTTPException as e:
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
    except HTTPException:
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
