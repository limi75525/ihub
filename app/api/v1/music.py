"""音乐中心：NAS 本地库 / Subsonic 兼容（Navidrome 等）。

设计：
- 配置存系统设置（music_* 键），密码类用 Fernet 加密存储；GET /config 不回传任何密钥
- NAS：扫描容器内挂载目录入 music_tracks 表（后台增量扫描，mtime 未变跳过标签解析），
  播放走 Range 流式响应；专辑/歌手视图由 SQL 聚合，不另建表
- Subsonic 兼容：后端代理（凭据不出服务端），<audio> 用 media_key 拉流；
  流式转发分块透传并透传 Range，默认原文件直出（不做强制转码）
- 用户数据（收藏/播放统计）存 user_music_stats，按用户+音源隔离；
  Subsonic 源的 star/scrobble 双写上游（尽力而为，失败不影响本地记录）
- 出站 HTTP / NAS 扫描状态机均复用 app.services 下的共享实现
"""

import hashlib
import io
import json as jsonlib
import logging
import re
import secrets
import string
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import case, func, or_, tuple_
from sqlalchemy.orm import Session

from app.core.config import settings as cfg
from app.core.deps import get_current_admin, get_current_user, get_media_user
from app.core.sqlutil import escape_like
from app.core.ttlcache import TTLCache
from app.db.helpers import get_or_create
from app.db.session import get_db
from app.models.music_track import MusicTrack
from app.models.music_user_stat import MusicUserStat
from app.models.music_playlist import MusicPlaylist, MusicPlaylistItem
from app.models.system_setting import set_setting
from app.models.user import User
from app.schemas.common import ConnectionTestIn, pick
from app.services import media_scan
from app.services.settings_store import get_cfg, get_cfgs, get_credential, set_credential
from app.services.upstream_http import http as _http
from app.services.upstream_http import http_open as _http_open
from app.services.upstream_http import proxy_stream as _proxy_stream

try:
    import mutagen
except ImportError:  # pragma: no cover
    mutagen = None

router = APIRouter(prefix="/music", tags=["music"])

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".m4a", ".ogg", ".opus", ".wma", ".ape"}
SCAN_STATE_KEY = "music_scan_state"

# 图片解码上限：4000 万像素（约 8000x5000）。服务端 Image.load() 是全量解码，
# 不设上限时一张几百 KB 的 PNG 可膨胀到数百 MB 内存（解压炸弹，认证后 DoS）
_MAX_COVER_PIXELS = 40_000_000

logger = logging.getLogger(__name__)


# ---------------- 配置存取 ----------------

# 可用音源：未设置 / NAS 本地 / Subsonic 兼容（Navidrome 等）
MUSIC_SOURCES = ("none", "nas", "subsonic")


def _music_source(db: Session) -> str:
    """当前音源；旧库里已下线的源（jellyfin / radio）一律按「未设置」处理。"""
    src = get_cfg(db, "music_source", "none")
    return src if src in MUSIC_SOURCES else "none"


def _config_out(db: Session) -> dict:
    v = get_cfgs(db, (
        "music_enabled", "music_autoplay", "music_nas_path",
        "music_sub_url", "music_sub_user", "music_sub_pass",
    ))
    return {
        "enabled": v.get("music_enabled", "") == "true",
        "autoplay": v.get("music_autoplay", "") == "true",
        "source": _music_source(db),
        "nas_path": v.get("music_nas_path", ""),
        "nas_track_count": db.query(MusicTrack.id).count() if v.get("music_nas_path", "") else 0,
        "sub_url": v.get("music_sub_url", ""),
        "sub_user": v.get("music_sub_user", ""),
        "sub_pass_set": bool(v.get("music_sub_pass", "")),
    }


class MusicConfigIn(BaseModel):
    enabled: bool = False
    autoplay: bool = False
    source: str = "none"
    nas_path: str | None = None
    sub_url: str | None = None
    sub_user: str | None = None
    sub_pass: str | None = None  # None=不改；空串=清除


@router.get("/config")
def get_music_config(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # 非管理员只下发开关三态：nas_path（服务器目录）、上游地址/账号（内网拓扑）不对普通用户暴露
    if user.role != "admin":
        return {
            "enabled": get_cfg(db, "music_enabled") == "true",
            "autoplay": get_cfg(db, "music_autoplay") == "true",
            "source": _music_source(db),
        }
    return _config_out(db)


@router.put("/config")
def set_music_config(body: MusicConfigIn, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    if body.source not in MUSIC_SOURCES:
        raise HTTPException(400, "未知的音乐源类型")
    set_setting("music_enabled", "true" if body.enabled else "false")
    set_setting("music_autoplay", "true" if body.autoplay else "false")
    set_setting("music_source", body.source)
    if body.nas_path is not None:
        set_setting("music_nas_path", body.nas_path.strip()[:1024])
    if body.sub_url is not None:
        set_setting("music_sub_url", body.sub_url.strip()[:1024])
    if body.sub_user is not None:
        set_setting("music_sub_user", body.sub_user.strip()[:256])
    if body.sub_pass is not None:
        set_credential("music_sub_pass", body.sub_pass.strip())
    return {"ok": True, "config": _config_out(db)}


# ---------------- Subsonic 兼容（Navidrome / Airsonic） ----------------

def _sub_creds(db: Session) -> tuple[str, str, str]:
    url = get_cfg(db, "music_sub_url").rstrip("/")
    user = get_cfg(db, "music_sub_user")
    pwd = get_credential(db, "music_sub_pass")
    if not (url and user and pwd):
        raise HTTPException(400, "Subsonic 音乐源尚未配置完整")
    return url, user, pwd


def _sub_qs(user: str, pwd: str, extra: dict | None = None) -> str:
    salt = secrets.token_hex(8)
    token = hashlib.md5((pwd + salt).encode()).hexdigest()
    params = {"u": user, "t": token, "s": salt, "v": "1.16.1", "c": "iHub", "f": "json"}
    if extra:
        params.update(extra)
    return "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())


def _sub_request(url: str, user: str, pwd: str, endpoint: str, extra: dict | None = None, raw: bool = False):
    """用显式凭据调 Subsonic 端点（test 接口允许用表单临时值，不必先保存）。"""
    full = f"{url.rstrip('/')}/rest/{endpoint}?{_sub_qs(user, pwd, extra)}"
    status, body = _http(full)
    if raw:
        return body
    try:
        data = jsonlib.loads(body.decode("utf-8", "replace"))
    except ValueError:
        # 上游是反代错误页/HTML 登录页时按 502 回报，而非未处理 500
        raise HTTPException(502, "上游返回的不是有效 JSON（请检查音乐服务器地址）") from None
    wrapper = data.get("subsonic-response", {})
    if wrapper.get("status") != "ok":
        err = wrapper.get("error", {})
        raise HTTPException(502, f"Subsonic 错误：{err.get('message', '未知')}")
    return wrapper


def _sub_get(db: Session, endpoint: str, extra: dict | None = None, raw: bool = False):
    url, user, pwd = _sub_creds(db)
    return _sub_request(url, user, pwd, endpoint, extra=extra, raw=raw)


_SUB_ALL_TTL = 120.0
_SUB_ALL_LOCK = threading.Lock()
_SUB_ALL_CACHE: dict[str, tuple[float, list]] = {}


def _sub_all_songs(db: Session) -> list:
    """Subsonic 全量曲目：分页拉取（每页 2000，上限 30000）→ 按入库时间倒序 → 缓存 120s。
    供歌曲列表分页切片与统计复用，避免大曲库多次全量拉取。"""
    url, u, pwd = _sub_creds(db)
    key = f"{url}|{u}"
    now = time.time()
    with _SUB_ALL_LOCK:
        ts, cached = _SUB_ALL_CACHE.get(key, (0.0, None))
        if cached is not None and now - ts < _SUB_ALL_TTL:
            return cached
    out: list = []
    offset = 0
    while offset <= 30000:
        batch = (
            _sub_request(url, u, pwd, "search3", {
                "query": "", "songCount": 2000, "songOffset": offset, "artistCount": 0, "albumCount": 0,
            })
            .get("searchResult3", {})
            .get("song", [])
        )
        out.extend(batch)
        if len(batch) < 2000:
            break
        offset += 2000
    out.sort(key=lambda s: str(s.get("created", "")), reverse=True)
    with _SUB_ALL_LOCK:
        _SUB_ALL_CACHE[key] = (time.time(), out)
    return out


def _song_out(s: dict) -> dict:
    return {
        "id": s.get("id"),
        "title": s.get("title", ""),
        "artist": s.get("artist", ""),
        "album": s.get("album", ""),
        "duration": int(s.get("duration") or 0),
        "album_id": s.get("albumId") or "",
        "artist_id": s.get("artistId") or "",
        "cover_art": s.get("coverArt") or "",
        "track_no": int(s.get("track") or 0),
        "year": int(s.get("year") or 0),
    }


def _album_out(a: dict) -> dict:
    return {
        "id": a.get("id"),
        "name": a.get("name") or a.get("title") or "",
        "artist": a.get("artist") or "",
        "artist_id": a.get("artistId") or "",
        "year": int(a.get("year") or 0),
        "song_count": int(a.get("songCount") or 0),
        "duration": int(a.get("duration") or 0),
        "cover_art": a.get("coverArt") or "",
    }


@router.get("/subsonic/songs")
def subsonic_songs(
    q: str = "",
    sort: str = "mtime",
    letter: str = "",
    limit: int = 200,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """q 为空 = 全库浏览（默认按入库时间倒序，sort 可切 artist/title 排序，支持 letter 字母跳转）；
    有关键词 = 搜索。排序基于全量缓存切片，letter_offset 供前端虚拟滚动定位。"""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    sort = sort if sort in ("mtime", "artist", "title") else "mtime"
    letter_key = (letter or "").strip()[:6].lower()
    if not q.strip():
        all_songs = _sub_all_songs(db)
        if sort == "artist":
            view = sorted(
                all_songs,
                key=lambda s: (str(s.get("artist") or "").lower(), str(s.get("album") or "").lower(),
                               int(s.get("track") or 0), str(s.get("title") or "").lower()),
            )
        elif sort == "title":
            view = sorted(
                all_songs,
                key=lambda s: (str(s.get("title") or "").lower(), str(s.get("artist") or "").lower()),
            )
        else:
            view = all_songs
        total = len(view)
        letter_offset = 0
        if letter_key and sort in ("artist", "title"):
            field = "artist" if sort == "artist" else "title"

            def _firstc(s: dict) -> str:
                return str(s.get(field) or "")[:1].lower()

            if letter_key == "other":
                letter_offset = sum(1 for s in view if _firstc(s) in string.ascii_lowercase)
                view = [s for s in view if _firstc(s) not in string.ascii_lowercase]
            else:
                letter_offset = sum(1 for s in view if _firstc(s) < letter_key)
                view = [s for s in view if _firstc(s) == letter_key]
        page = view[offset : offset + limit]
        return {"items": [_song_out(s) for s in page], "total": total, "letter_offset": letter_offset}
    extra = {"query": q.strip(), "songCount": limit, "songOffset": offset, "artistCount": 0, "albumCount": 0}
    wrapper = _sub_get(db, "search3", extra)
    songs = wrapper.get("searchResult3", {}).get("song", [])
    # 浏览与搜索两个分支保持同一返回形状（前端共用取数逻辑）
    return {"items": [_song_out(s) for s in songs], "total": len(songs), "letter_offset": 0}


# 专辑浏览类型白名单（Navidrome 支持的 getAlbumList2 type 子集）
SUB_ALBUM_TYPES = {"newest", "recent", "frequent", "random", "starred", "alphabeticalByName"}


@router.get("/subsonic/albums")
def subsonic_albums(
    type: str = "newest",
    limit: int = 60,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ltype = type if type in SUB_ALBUM_TYPES else "newest"
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    wrapper = _sub_get(db, "getAlbumList2", {"type": ltype, "size": limit, "offset": offset})
    albums = wrapper.get("albumList2", {}).get("album", [])
    return {"items": [_album_out(a) for a in albums]}


@router.get("/subsonic/album/{album_id}")
def subsonic_album(album_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    wrapper = _sub_get(db, "getAlbum", {"id": album_id})
    a = wrapper.get("album", {}) or {}
    return {"album": _album_out(a), "items": [_song_out(s) for s in a.get("song", []) or []]}


@router.get("/subsonic/starred")
def subsonic_starred(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    wrapper = _sub_get(db, "getStarred2")
    songs = wrapper.get("starred2", {}).get("song", [])
    return {"items": [_song_out(s) for s in songs]}


@router.get("/subsonic/lyrics/{song_id}")
def subsonic_lyrics(song_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """OpenSubsonic getLyricsBySongId——Navidrome 实际提供歌词的端点
    （旧版 getLyrics 对 id 参数直接返回空）；老服务不支持时回退传统纯文本。"""
    try:
        try:
            wrapper = _sub_get(db, "getLyricsBySongId", {"id": song_id})
        except HTTPException:
            wrapper = _sub_get(db, "getLyrics", {"id": song_id})
    except HTTPException:
        return {"synced": False, "lines": []}
    lines_out: list[dict] = []
    synced = False
    structured = (wrapper.get("lyricsList") or {}).get("structuredLyrics") or []
    if structured:
        sl = structured[0]
        synced = bool(sl.get("synced"))
        for ln in sl.get("line") or []:
            start = ln.get("start")
            t = (start / 1000) if isinstance(start, (int, float)) else None
            lines_out.append({"t": t, "text": ln.get("value", "") or ""})
    else:
        legacy = (wrapper.get("lyrics") or {}).get("value") or ""
        lines_out = [{"t": None, "text": ln} for ln in legacy.splitlines() if ln.strip()]
    return {"synced": synced, "lines": lines_out}


@router.post("/subsonic/test")
def subsonic_test(body: ConnectionTestIn, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    url = pick(body.url, get_cfg(db, "music_sub_url"))
    user = pick(body.user, get_cfg(db, "music_sub_user"))
    pwd = pick(body.password, get_credential(db, "music_sub_pass"))
    if not (url and user and pwd):
        return {"ok": False, "error": "Subsonic 音乐源尚未配置完整"}
    try:
        wrapper = _sub_request(url, user, pwd, "ping")
        return {"ok": wrapper.get("status") == "ok", "server": wrapper.get("serverVersion", "")}
    except HTTPException as e:
        return {"ok": False, "error": e.detail}


@router.get("/subsonic/stream/{song_id}")
def subsonic_stream(song_id: str, request: Request, user: User = Depends(get_media_user), db: Session = Depends(get_db)):
    url, su, sp = _sub_creds(db)
    # 不传 maxBitRate：原文件直出（固定 320 会把无损强制转码成 mp3）
    full = f"{url.rstrip('/')}/rest/stream?{_sub_qs(su, sp, {'id': song_id})}"
    range_header = request.headers.get("range")
    upstream = _http_open(full, headers={"Range": range_header} if range_header else None)
    return _proxy_stream(upstream)


@router.get("/subsonic/cover/{song_id}")
def subsonic_cover(song_id: str, user: User = Depends(get_media_user), db: Session = Depends(get_db)):
    body = _sub_get(db, "getCoverArt", {"id": song_id, "size": "300"}, raw=True)
    return Response(content=body, media_type="image/jpeg")


# ---------------- NAS 本地库 ----------------

def _nas_root(db: Session) -> Path:
    root = get_cfg(db, "music_nas_path")
    if not root:
        raise HTTPException(400, "尚未设置音乐目录")
    path = Path(root)
    if not path.is_dir():
        raise HTTPException(400, f"音乐目录不存在或不可访问：{root}")
    return path


def _cover_dir() -> Path:
    d = Path(cfg.DATA_DIR) / "music_covers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _extract_cover(mf, rel: str) -> str:
    """提取内嵌封面到 data/music_covers/<hash>.<ext>，返回相对路径；无封面返回空。
    哈希取自相对路径：同一路径重复扫描时复用/覆盖，不产生垃圾文件。"""
    data = b""
    try:
        if hasattr(mf, "pictures") and mf.pictures:  # FLAC / APEv2
            data = mf.pictures[0].data or b""
        if not data and mf.tags:
            tags = mf.tags
            try:
                covr = tags["covr"]  # MP4/M4A（键查找大小写不敏感，dict.get 不可用）
                data = bytes(covr[0])
            except (KeyError, ValueError, IndexError, TypeError):
                # ID3（MP3）：APIC 的描述非空时 dict 键是 "APIC:<desc>"（iTunes 等工具常写
                # desc="cover"），tags["APIC"] / tags["APIC:"] 都取不到——用 getall 全取，
                # 多帧时优先 type=3（正面前封面）
                try:
                    pics = tags.getall("APIC")
                except Exception:
                    pics = []
                if pics:
                    front = next((p for p in pics if getattr(p, "type", 0) == 3), pics[0])
                    data = front.data or b""
    except Exception:
        return ""
    if len(data) < 64:
        return ""
    from PIL import Image  # 可选依赖：延迟导入，扫描时才需要

    name = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:24]
    ext = ".png" if data[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg"
    target = _cover_dir() / f"{name}{ext}"
    # 压到 300px 方边内，避免几 MB 的原封面拖累列表加载
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.width * im.height > _MAX_COVER_PIXELS:
                return ""  # 异常超大封面（解压炸弹形态）：跳过，不影响曲目入库
            im = im.convert("RGB") if ext == ".jpg" else im
            im.thumbnail((300, 300))
            im.save(target, quality=85)
    except Exception:
        return ""
    return f"music_covers/{target.name}"


_YEAR_RE = re.compile(r"(\d{4})")


def _read_tags(path: Path, rel: str) -> dict:
    title, artist, album, duration = "", "", "", 0.0
    album_artist = genre = ""
    year = track_no = disc_no = bitrate = sample_rate = 0
    cover_path = None
    note = ""
    if mutagen is not None:
        try:
            mf = mutagen.File(str(path))
            if mf is not None:
                duration = float(getattr(mf.info, "length", 0) or 0)
                bitrate = int(getattr(mf.info, "bitrate", 0) or 0) // 1000
                sample_rate = int(getattr(mf.info, "sample_rate", 0) or 0)
                tags = mf.tags or {}

                def first(*keys):
                    """按序取第一个非空标签。注意必须走 tags[k]（dict.get 匹配不到）；
                    mutagen 各容器对缺失键抛的异常不一（VComment 抛 ValueError，
                    ID3/MP4 抛 KeyError），两样都要接住。"""
                    for k in keys:
                        try:
                            v = tags[k]
                        except (KeyError, ValueError):
                            continue
                        if v:
                            return str(v[0] if isinstance(v, list) else v)
                    return ""

                def first_int(*keys):
                    raw = first(*keys)
                    m = re.search(r"\d+", raw)
                    return int(m.group()) if m else 0

                title = first("TIT2", "©nam", "TITLE")
                artist = first("TPE1", "©ART", "ARTIST")
                album = first("TALB", "©alb", "ALBUM")
                album_artist = first("TPE2", "aART", "ALBUMARTIST", "ALBUM ARTIST")
                genre = first("TCON", "©gen", "©gne", "GENRE")[:128]
                ym = _YEAR_RE.search(first("TDRC", "TDRL", "TDOR", "TYER", "©day", "DATE"))
                year = int(ym.group(1)) if ym else 0
                track_no = first_int("TRCK", "trkn", "TRACKNUMBER")
                disc_no = first_int("TPOS", "disk", "DISCNUMBER")
                cover_path = _extract_cover(mf, rel) or None
        except Exception as e:
            note = f"标签读取失败：{e}"
    stem = path.stem
    if not title:
        title = stem
        note = note or "无标题标签，按文件名识别"
    if not artist:
        artist = "未知歌手"
    if not album:
        album = "未知专辑"
    return {
        "path": rel,
        "title": title[:512],
        "artist": artist[:512],
        "album": album[:512],
        "album_artist": album_artist[:512],
        "genre": genre,
        "year": year,
        "track_no": track_no,
        "disc_no": disc_no,
        "duration": duration,
        "bitrate": bitrate,
        "sample_rate": sample_rate,
        "ext": path.suffix.lower()[:16],
        "size": path.stat().st_size,
        "mtime": int(path.stat().st_mtime),
        "cover_path": cover_path,
        "note": note[:512],
    }


# ---- 后台增量扫描（mtime 未变的文件直接跳过标签解析；共享引擎 app.services.media_scan） ----

_SCAN = media_scan.ScanStateStore(SCAN_STATE_KEY)

# 标签解析器版本：提取逻辑修复后 +1，扫描时与 state 里记录的不一致则无视 mtime
# 全量重解析（老库升级后点一次「重新扫描」即可补齐此前提取失败的封面等元数据）
SCANNER_VERSION = 2


def _apply_track_meta(row: MusicTrack, meta: dict, data: Path) -> None:
    """把新解析结果写入已有行，并回收被替换掉的旧封面文件。"""
    old_cover = row.cover_path
    for k, v in meta.items():
        setattr(row, k, v)
    if old_cover and old_cover != row.cover_path:
        (data / old_cover).unlink(missing_ok=True)


def _drop_track_cover(row: MusicTrack, data: Path) -> None:
    if row.cover_path:
        (data / row.cover_path).unlink(missing_ok=True)


def _run_scan(root_str: str, data_dir: str) -> None:
    root = Path(root_str).resolve()
    data = Path(data_dir)
    rescan_all = _SCAN.read().get("scanner_version") != SCANNER_VERSION
    files = media_scan.walk_media_files(root, AUDIO_EXTS)
    media_scan.run_media_scan(
        store=_SCAN,
        model=MusicTrack,
        root=root,
        files=files,
        parse=lambda path, rel, st: _read_tags(path, rel),
        apply_meta=lambda row, meta: _apply_track_meta(row, meta, data),
        force_parse=rescan_all,
        need_update=lambda row, meta: rescan_all or row.mtime != meta["mtime"],
        on_remove=lambda row: _drop_track_cover(row, data),
        done_extra={"scanner_version": SCANNER_VERSION},
    )


@router.post("/scan")
def scan_library(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    if mutagen is None:
        raise HTTPException(500, "后端缺少 mutagen 依赖")
    root = _nas_root(db).resolve()
    started, state = _SCAN.begin()
    if not started:
        return {"ok": True, "started": False, "state": state}
    threading.Thread(target=_run_scan, args=(str(root), str(Path(cfg.DATA_DIR))), daemon=True).start()
    return {"ok": True, "started": True}


@router.get("/scan/status")
def scan_status(admin: User = Depends(get_current_admin)):
    return _SCAN.read()


@router.get("/tracks")
def list_tracks(
    q: str = "",
    album: str = "",
    album_artist: str = "",
    artist: str = "",
    ids: str = "",
    sort: str = "mtime",
    letter: str = "",
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """sort：mtime=入库时间倒序（默认）/ artist=歌手 A-Z / title=歌名 A-Z。
    letter：字母跳转（a-z / 0-9 / other），配合 sort=artist|title 返回该字母块的第一页，
    letter_offset = 排序全表中位于该字母块之前的行数（前端虚拟滚动定位用）。"""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    sort = sort if sort in ("mtime", "artist", "title") else "mtime"
    letter_key = (letter or "").strip()[:6].lower()
    query = db.query(MusicTrack)
    by_album = False
    if ids.strip():
        id_list = []
        for x in ids.split(","):
            x = x.strip()
            if x.isdigit() and x.isascii():  # isdigit 对 ² 等上标数字也为 True 但 int() 抛错
                id_list.append(int(x))
        query = query.filter(MusicTrack.id.in_(id_list[:500]))
    if album.strip():
        query = query.filter(MusicTrack.album == album.strip()[:512])
        by_album = True
    if album_artist.strip():
        query = query.filter(MusicTrack.album_artist == album_artist.strip()[:512])
        by_album = True
    if artist.strip():
        query = query.filter(MusicTrack.artist == artist.strip()[:512])
    if q.strip():
        # 转义 LIKE 通配符：否则 q="%%%" 退化为全表通配扫描（与 messages 同策略）
        kw = f"%{escape_like(q.strip())}%"
        query = query.filter(
            or_(
                MusicTrack.title.ilike(kw, escape="\\"),
                MusicTrack.artist.ilike(kw, escape="\\"),
                MusicTrack.album.ilike(kw, escape="\\"),
                MusicTrack.album_artist.ilike(kw, escape="\\"),
                MusicTrack.genre.ilike(kw, escape="\\"),
            )
        )
    total = query.with_entities(MusicTrack.id).count()
    if by_album:
        # 专辑详情页：按碟号/曲目号排
        query = query.order_by(
            MusicTrack.disc_no.asc(), MusicTrack.track_no.asc(), MusicTrack.title.asc()
        )
    elif sort == "artist":
        query = query.order_by(
            func.lower(MusicTrack.artist).asc(), func.lower(MusicTrack.album).asc(),
            MusicTrack.disc_no.asc(), MusicTrack.track_no.asc(), func.lower(MusicTrack.title).asc(),
        )
    elif sort == "title":
        query = query.order_by(
            func.lower(MusicTrack.title).asc(), func.lower(MusicTrack.artist).asc()
        )
    elif not q.strip() and not ids.strip():
        # 歌曲页默认：按更新时间倒序（新入库/新改动的排前面）
        query = query.order_by(MusicTrack.mtime.desc(), MusicTrack.id.desc())
    else:
        query = query.order_by(
            MusicTrack.artist.asc(), MusicTrack.album.asc(), MusicTrack.disc_no.asc(),
            MusicTrack.track_no.asc(), MusicTrack.title.asc(),
        )

    letter_offset = 0
    if letter_key and sort in ("artist", "title") and not ids.strip():
        col = MusicTrack.artist if sort == "artist" else MusicTrack.title
        firstc = func.lower(func.substr(col, 1, 1))
        if letter_key == "other":
            # 非字母开头（数字/中文/符号等）块：偏移 = 字母块总行数
            letter_offset = (
                query.with_entities(MusicTrack.id)
                .filter(func.instr("abcdefghijklmnopqrstuvwxyz", firstc) > 0)
                .count()
            )
            query = query.filter(func.instr("abcdefghijklmnopqrstuvwxyz", firstc) == 0)
        else:
            letter_offset = (
                query.with_entities(MusicTrack.id).filter(firstc < letter_key).count()
            )
            query = query.filter(firstc == letter_key)

    rows = query.offset(offset).limit(limit).all()
    return {
        "total": total,
        "letter_offset": letter_offset,
        "items": [
            {
                "id": t.id,
                "title": t.title,
                "artist": t.artist,
                "album": t.album,
                "album_artist": t.album_artist,
                "genre": t.genre,
                "year": t.year or 0,
                "track_no": t.track_no or 0,
                "disc_no": t.disc_no or 0,
                "duration": t.duration or 0,
                "bitrate": t.bitrate or 0,
                "sample_rate": t.sample_rate or 0,
                "ext": t.ext,
                "has_cover": bool(t.cover_path),
            }
            for t in rows
        ],
    }


def _album_order_key():
    """专辑聚合排序键：专辑歌手为空时退回专辑名（「未知歌手」沉底逻辑一致）。"""
    return case((MusicTrack.album_artist == "", MusicTrack.album), else_=MusicTrack.album_artist)


@router.get("/nas/albums")
def nas_albums(
    q: str = "",
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 300))
    offset = max(0, offset)
    base = db.query(MusicTrack)
    if q.strip():
        kw = f"%{escape_like(q.strip())}%"
        base = base.filter(
            or_(
                MusicTrack.album.ilike(kw, escape="\\"), 
                MusicTrack.album_artist.ilike(kw, escape="\\"),
            )
        )
    grouped = base.with_entities(
        MusicTrack.album.label("album"),
        MusicTrack.album_artist.label("album_artist"),
        func.count(MusicTrack.id).label("cnt"),
        func.max(MusicTrack.year).label("year"),
    ).group_by(MusicTrack.album, MusicTrack.album_artist)
    sub = grouped.subquery()
    total = db.query(func.count()).select_from(sub).scalar() or 0
    rows = (
        grouped.order_by(func.lower(_album_order_key()).asc(), MusicTrack.album.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    # 本页专辑各自取一个有封面的曲目 id（无则空，前端回退渐变卡）
    cover_map: dict[tuple, int] = {}
    keys = [(r.album, r.album_artist) for r in rows]
    if keys:
        cover_rows = (
            db.query(
                MusicTrack.album.label("album"),
                MusicTrack.album_artist.label("album_artist"),
                func.min(MusicTrack.id).label("cid"),
            )
            .filter(MusicTrack.cover_path.isnot(None), MusicTrack.cover_path != "")
            .filter(tuple_(MusicTrack.album, MusicTrack.album_artist).in_(keys))
            .group_by(MusicTrack.album, MusicTrack.album_artist)
            .all()
        )
        for cr in cover_rows:
            cover_map[(cr.album, cr.album_artist)] = int(cr.cid)
    items = []
    for r in rows:
        items.append({
            "name": r.album,
            "album": r.album,
            "artist": r.album_artist or "未知歌手",
            "album_artist": r.album_artist,
            "year": int(r.year or 0),
            "song_count": int(r.cnt or 0),
            "cover_track_id": cover_map.get((r.album, r.album_artist)),
        })
    return {"total": total, "items": items}


@router.get("/nas/artists")
def nas_artists(
    q: str = "",
    limit: int = 200,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    base = db.query(MusicTrack)
    if q.strip():
        kw = f"%{escape_like(q.strip())}%"
        base = base.filter(MusicTrack.artist.ilike(kw, escape="\\"))
    grouped = base.with_entities(
        MusicTrack.artist.label("artist"),
        func.count(MusicTrack.id).label("cnt"),
        func.count(func.distinct(MusicTrack.album)).label("albums"),
    ).group_by(MusicTrack.artist)
    sub = grouped.subquery()
    total = db.query(func.count()).select_from(sub).scalar() or 0
    rows = (
        grouped.order_by(func.lower(MusicTrack.artist).asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    cover_map: dict[str, int] = {}
    keys = [(r.artist,) for r in rows]
    if keys:
        cover_rows = (
            db.query(
                MusicTrack.artist.label("artist"),
                func.min(MusicTrack.id).label("cid"),
            )
            .filter(MusicTrack.cover_path.isnot(None), MusicTrack.cover_path != "")
            .filter(tuple_(MusicTrack.artist).in_([(k[0],) for k in keys]))
            .group_by(MusicTrack.artist)
            .all()
        )
        for cr in cover_rows:
            cover_map[cr.artist] = int(cr.cid)
    return {
        "total": total,
        "items": [
            {
                "name": r.artist,
                "track_count": int(r.cnt or 0),
                "album_count": int(r.albums or 0),
                "cover_track_id": cover_map.get(r.artist),
            }
            for r in rows
        ],
    }


# ---- 歌词：同名 .lrc 优先，其次内嵌 USLT / ©lyr / LYRICS ----

_LRC_LINE = re.compile(r"\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]")


def _parse_lrc(text: str) -> list[dict]:
    out: list[dict] = []
    for raw in text.splitlines():
        stamps = _LRC_LINE.findall(raw)
        if not stamps:
            continue
        content = _LRC_LINE.sub("", raw).strip()
        if not content:
            continue
        for m, s, frac in stamps:
            t = int(m) * 60 + int(s) + (int(frac.ljust(3, "0")) / 1000 if frac else 0.0)
            out.append({"t": t, "text": content})
    out.sort(key=lambda x: x["t"])
    return out


def _read_lyric_text(path: Path) -> str:
    lrc = path.with_suffix(".lrc")
    if not lrc.is_file():
        return ""
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return lrc.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
        except OSError:
            return ""
    return ""


def _embedded_lyrics(path: Path) -> str:
    if mutagen is None:
        return ""
    try:
        mf = mutagen.File(str(path))
        tags = mf.tags if mf else None
        if not tags:
            return ""
        if hasattr(tags, "getall"):  # ID3
            try:
                for frame in tags.getall("USLT"):
                    if getattr(frame, "text", ""):
                        return str(frame.text)
            except Exception:
                pass
            return ""
        for key in ("©lyr", "LYRICS", "LYRIC"):
            try:
                v = tags[key]
            except (KeyError, ValueError):
                continue
            if isinstance(v, list) and v:
                return str(v[0])
    except Exception:
        return ""
    return ""


@router.get("/nas/lyrics/{track_id}")
def nas_lyrics(track_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    root = _nas_root(db).resolve()
    t = db.get(MusicTrack, track_id)
    if not t:
        raise HTTPException(404, "曲目不存在")
    path = (root / t.path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise HTTPException(404, "曲目不存在")
    if not path.is_file():
        raise HTTPException(404, "音频文件缺失")
    raw = _read_lyric_text(path) or _embedded_lyrics(path)
    if not raw.strip():
        return {"synced": False, "lines": []}
    lines = _parse_lrc(raw)
    if lines:
        return {"synced": True, "lines": lines}
    lines = [{"t": None, "text": ln.strip()} for ln in raw.splitlines() if ln.strip()]
    return {"synced": False, "lines": lines}


@router.get("/cover/{track_id}")
def track_cover(track_id: int, user: User = Depends(get_media_user), db: Session = Depends(get_db)):
    t = db.get(MusicTrack, track_id)
    if not t or not t.cover_path:
        raise HTTPException(404, "无封面")
    path = (Path(cfg.DATA_DIR) / t.cover_path).resolve()
    try:
        path.relative_to(Path(cfg.DATA_DIR).resolve())
    except ValueError:
        raise HTTPException(404, "无封面")
    if not path.is_file():
        raise HTTPException(404, "无封面")
    return FileResponse(path, media_type="image/png" if path.suffix == ".png" else "image/jpeg")


@router.get("/stream/{track_id}")
def stream_track(track_id: int, user: User = Depends(get_media_user), db: Session = Depends(get_db)):
    root = _nas_root(db).resolve()
    t = db.get(MusicTrack, track_id)
    if not t:
        raise HTTPException(404, "曲目不存在")
    path = (root / t.path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise HTTPException(404, "曲目不存在")
    if not path.is_file():
        raise HTTPException(404, "音频文件缺失")
    return FileResponse(path, media_type=f"audio/{t.ext.lstrip('.') or 'mpeg'}")


# ---------------- 音乐统计（用户卡） ----------------

@router.get("/summary")
def music_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """音乐页用户卡统计：歌曲 / 专辑 / 歌手（按当前音源）+ 今日听曲（当日实际播放过几首，跨音源）。"""
    source = _music_source(db)
    midnight = int(datetime.combine(datetime.now().astimezone().date(), datetime.min.time()).timestamp())
    out = {"source": source, "songs": 0, "albums": 0, "artists": 0, "today": 0}
    # 今日听曲 = user_music_stats 里当日播过（last_played）的曲目数；跨音源累计，切音源不清零
    out["today"] = (
        db.query(MusicUserStat.id)
        .filter(MusicUserStat.user_id == user.id, MusicUserStat.last_played >= midnight)
        .count()
    )
    if source == "nas":
        out["songs"] = db.query(MusicTrack.id).count()
        # 与 /nas/albums 同口径的分组子查询计数——SQLite 3.44 之前没有 concat 函数，
        # func.concat 在 NAS 旧镜像上会渲染成 no such function: concat 直接 500
        grouped = db.query(MusicTrack.album, MusicTrack.album_artist).group_by(
            MusicTrack.album, MusicTrack.album_artist
        )
        out["albums"] = db.query(func.count()).select_from(grouped.subquery()).scalar() or 0
        out["artists"] = db.query(func.count(func.distinct(MusicTrack.artist))).scalar() or 0
    elif source == "subsonic":
        try:
            songs = _sub_all_songs(db)
        except HTTPException:
            return out
        out["songs"] = len(songs)
        out["albums"] = len({
            str(s.get("albumId") or s.get("album") or "")
            for s in songs
            if s.get("albumId") or s.get("album")
        })
        out["artists"] = len({
            str(s.get("artistId") or s.get("artist") or "")
            for s in songs
            if s.get("artistId") or s.get("artist")
        })
    return out


# ---------------- 总览统计辅助 ----------------

_COUNT_CACHE = TTLCache(60.0)  # 上游库计数 60s 缓存（总览统计防抖）


def library_song_count(db: Session) -> int:
    """总览用户卡「音乐」计数：nas=表计数；subsonic=上游计数（60s 缓存）。失败计 0。"""
    source = _music_source(db)
    try:
        if source == "nas":
            return db.query(MusicTrack.id).count()
        if source == "subsonic":
            cached = _COUNT_CACHE.get(source)
            if cached is not None:
                return cached
            n = len(_sub_all_songs(db))
            _COUNT_CACHE.put(source, n)
            return n
    except Exception:
        return 0
    return 0


# ---------------- 用户数据（收藏 / 播放统计） ----------------

def _stat_out(r: MusicUserStat) -> dict:
    return {
        "source": r.source,
        "key": r.track_key,
        "title": r.title,
        "artist": r.artist,
        "album": r.album,
        "duration": r.duration or 0,
        "starred": bool(r.starred),
        "play_count": r.play_count or 0,
        "last_played": r.last_played or 0,
    }


@router.get("/stats")
def music_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(MusicUserStat).filter(MusicUserStat.user_id == user.id).all()
    return {"items": [_stat_out(r) for r in rows]}


def _get_or_create_stat(db: Session, user_id: int, source: str, key: str) -> MusicUserStat:
    """并发同曲 star/scrobble 撞 (user_id,source,track_key) 唯一约束时由 get_or_create 兜住。"""
    return get_or_create(db, MusicUserStat, user_id=user_id, source=source, track_key=key)


class MusicStatIn(BaseModel):
    source: str
    key: str
    starred: bool | None = None
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    duration: float | None = None


def _apply_snapshot(row: MusicUserStat, body: MusicStatIn) -> None:
    if body.title is not None:
        row.title = body.title.strip()[:512]
    if body.artist is not None:
        row.artist = body.artist.strip()[:512]
    if body.album is not None:
        row.album = body.album.strip()[:512]
    if body.duration is not None:
        row.duration = max(0.0, float(body.duration))


def _sub_dual_write(db: Session, endpoint: str, song_id: str) -> str:
    """Subsonic 上游双写（star/unstar/scrobble），尽力而为：失败只回报不影响本地。"""
    try:
        url, user, pwd = _sub_creds(db)
    except HTTPException:
        return ""  # 源未配置（可能已切换），跳过
    try:
        _sub_request(url, user, pwd, endpoint, {"id": song_id})
        return ""
    except HTTPException as e:
        return f"上游同步失败：{e.detail}"


@router.post("/stats/star")
def music_star(body: MusicStatIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.source not in ("nas", "subsonic") or not body.key.strip():
        raise HTTPException(400, "参数不完整")
    row = _get_or_create_stat(db, user.id, body.source, body.key.strip()[:512])
    row.starred = bool(body.starred)
    _apply_snapshot(row, body)
    note = ""
    if body.source == "subsonic":
        note = _sub_dual_write(db, "star" if row.starred else "unstar", row.track_key)
    db.commit()
    return {"ok": True, "stat": _stat_out(row), "note": note}


@router.post("/stats/scrobble")
def music_scrobble(body: MusicStatIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.source not in ("nas", "subsonic") or not body.key.strip():
        raise HTTPException(400, "参数不完整")
    row = _get_or_create_stat(db, user.id, body.source, body.key.strip()[:512])
    row.play_count = (row.play_count or 0) + 1
    row.last_played = int(time.time())
    _apply_snapshot(row, body)
    note = ""
    if body.source == "subsonic":
        note = _sub_dual_write(db, "scrobble", row.track_key)
    db.commit()
    return {"ok": True, "stat": _stat_out(row), "note": note}


# ---------------- 用户歌单 ----------------

def _own_playlist(db: Session, pid: int, user_id: int) -> MusicPlaylist:
    row = db.get(MusicPlaylist, pid)
    if not row or row.user_id != user_id:
        raise HTTPException(404, "歌单不存在")
    return row


def _pl_item_out(it: MusicPlaylistItem) -> dict:
    return {
        "id": it.id,
        "source": it.source,
        "key": it.track_key,
        "title": it.title,
        "artist": it.artist,
        "album": it.album,
        "duration": it.duration or 0,
    }


def _pl_cover_dir() -> Path:
    d = Path(cfg.DATA_DIR) / "playlist_covers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pl_out(p: MusicPlaylist, song_count: int = 0, cover_key: str = "", cover_source: str = "") -> dict:
    cover_v = 0
    if p.cover_path:
        try:
            cover_v = int((Path(cfg.DATA_DIR) / p.cover_path).stat().st_mtime)
        except OSError:
            cover_v = 0
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description or "",
        "song_count": song_count,
        "cover_key": cover_key,
        "cover_source": cover_source,
        "has_cover": bool(p.cover_path),
        "cover_v": cover_v,
        "created_at": int(p.created_at.timestamp()) if p.created_at else 0,
    }


@router.get("/playlists")
def playlists_list(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """当前用户的歌单列表：单曲数与封面取自第一首曲目（cover_key + cover_source）。"""
    rows = (
        db.query(MusicPlaylist)
        .filter(MusicPlaylist.user_id == user.id)
        .order_by(MusicPlaylist.created_at.asc(), MusicPlaylist.id.asc())
        .all()
    )
    counts: dict[int, int] = {}
    covers: dict[int, tuple[str, str]] = {}
    ids = [r.id for r in rows]
    if ids:
        items = (
            db.query(MusicPlaylistItem)
            .filter(MusicPlaylistItem.playlist_id.in_(ids))
            .order_by(MusicPlaylistItem.position.asc(), MusicPlaylistItem.id.asc())
            .all()
        )
        for it in items:
            counts[it.playlist_id] = counts.get(it.playlist_id, 0) + 1
            if it.playlist_id not in covers and it.track_key:
                covers[it.playlist_id] = (it.track_key, it.source)
    return {
        "items": [
            _pl_out(p, counts.get(p.id, 0), *(covers.get(p.id) or ("", "")))
            for p in rows
        ]
    }


class PlaylistIn(BaseModel):
    name: str
    description: str = ""


MAX_PLAYLISTS_PER_USER = 200  # 每用户歌单个数上限：防循环调用灌表


@router.post("/playlists")
def playlist_create(body: PlaylistIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    name = body.name.strip()[:256]
    if not name:
        raise HTTPException(400, "歌单名不能为空")
    count = db.query(MusicPlaylist.id).filter(MusicPlaylist.user_id == user.id).count()
    if count >= MAX_PLAYLISTS_PER_USER:
        raise HTTPException(400, f"歌单数量已达上限（{MAX_PLAYLISTS_PER_USER} 个）")
    row = MusicPlaylist(user_id=user.id, name=name, description=body.description.strip()[:1024])
    db.add(row)
    db.commit()
    return {"ok": True, "playlist": _pl_out(row)}


class PlaylistPatchIn(BaseModel):
    """编辑歌单：名称与描述均可选，至少改一项。"""
    name: str | None = None
    description: str | None = None


@router.patch("/playlists/{pid}")
def playlist_patch(pid: int, body: PlaylistPatchIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = _own_playlist(db, pid, user.id)
    if body.name is None and body.description is None:
        raise HTTPException(400, "没有要修改的内容")
    if body.name is not None:
        name = body.name.strip()[:256]
        if not name:
            raise HTTPException(400, "歌单名不能为空")
        row.name = name
    if body.description is not None:
        row.description = body.description.strip()[:1024]
    db.commit()
    return {"ok": True, "playlist": _pl_out(row)}


@router.delete("/playlists/{pid}")
def playlist_delete(pid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = _own_playlist(db, pid, user.id)
    db.query(MusicPlaylistItem).filter(MusicPlaylistItem.playlist_id == row.id).delete()
    if row.cover_path:
        (Path(cfg.DATA_DIR) / row.cover_path).unlink(missing_ok=True)
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/playlists/{pid}")
def playlist_detail(pid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = _own_playlist(db, pid, user.id)
    items = (
        db.query(MusicPlaylistItem)
        .filter(MusicPlaylistItem.playlist_id == row.id)
        .order_by(MusicPlaylistItem.position.asc(), MusicPlaylistItem.id.asc())
        .all()
    )
    return {"playlist": _pl_out(row, len(items)), "items": [_pl_item_out(it) for it in items]}


class PlaylistAddIn(BaseModel):
    source: str
    key: str
    title: str = ""
    artist: str = ""
    album: str = ""
    duration: float = 0


MAX_PLAYLIST_ITEMS = 1000  # 单歌单曲目上限：防认证用户无限加曲灌表


@router.post("/playlists/{pid}/items")
def playlist_add_item(pid: int, body: PlaylistAddIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = _own_playlist(db, pid, user.id)
    if body.source not in ("nas", "subsonic") or not body.key.strip():
        raise HTTPException(400, "参数不完整")
    count = (
        db.query(func.count(MusicPlaylistItem.id))
        .filter(MusicPlaylistItem.playlist_id == row.id)
        .scalar()
        or 0
    )
    if count >= MAX_PLAYLIST_ITEMS:
        raise HTTPException(400, f"歌单曲目已达上限（{MAX_PLAYLIST_ITEMS} 首）")
    key = body.key.strip()[:512]
    exists = (
        db.query(MusicPlaylistItem.id)
        .filter(
            MusicPlaylistItem.playlist_id == row.id,
            MusicPlaylistItem.source == body.source,
            MusicPlaylistItem.track_key == key,
        )
        .first()
    )
    if exists:
        return {"ok": True, "duplicate": True}
    max_pos = (
        db.query(func.max(MusicPlaylistItem.position))
        .filter(MusicPlaylistItem.playlist_id == row.id)
        .scalar()
    ) or 0
    item = MusicPlaylistItem(
        playlist_id=row.id,
        source=body.source,
        track_key=key,
        title=(body.title or "").strip()[:512],
        artist=(body.artist or "").strip()[:512],
        album=(body.album or "").strip()[:512],
        duration=max(0.0, float(body.duration or 0)),
        position=int(max_pos) + 1,
    )
    db.add(item)
    db.commit()
    return {"ok": True, "item": _pl_item_out(item)}


@router.delete("/playlists/{pid}/items/{item_id}")
def playlist_remove_item(pid: int, item_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = _own_playlist(db, pid, user.id)
    deleted = (
        db.query(MusicPlaylistItem)
        .filter(MusicPlaylistItem.id == item_id, MusicPlaylistItem.playlist_id == row.id)
        .delete()
    )
    if not deleted:
        raise HTTPException(404, "曲目不在该歌单中")
    db.commit()
    return {"ok": True}


# ---- 歌单封面（自定义；空 = 前端用第一首曲目封面兜底） ----

# 只收位图（SVG 按 SVG 安全约定不进歌单封面）
_PL_COVER_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}


@router.get("/playlist-cover/{pid}")
def playlist_cover_get(pid: int, user: User = Depends(get_media_user), db: Session = Depends(get_db)):
    row = db.get(MusicPlaylist, pid)
    # 与书架 /books/{id}/cover 同一标准：媒体接口必须做属主校验，他人歌单封面一律 404
    if not row or row.user_id != user.id or not row.cover_path:
        raise HTTPException(404, "无封面")
    path = (Path(cfg.DATA_DIR) / row.cover_path).resolve()
    try:
        path.relative_to(Path(cfg.DATA_DIR).resolve())
    except ValueError:
        raise HTTPException(404, "无封面")
    if not path.is_file():
        raise HTTPException(404, "无封面")
    return FileResponse(path, media_type="image/png" if path.suffix == ".png" else "image/jpeg")


def _process_playlist_cover(data: bytes, ext: str, pid: int) -> str:
    """解码并压缩歌单封面（PIL 全量解码最重可吃数百 MB 内存，必须放线程池，
    不能在事件循环里跑）。返回落盘的相对路径。"""
    from PIL import Image

    try:
        im = Image.open(io.BytesIO(data))
        # 解压炸弹防护：Image.open 只读头部，先核对声明尺寸再解码（load/thumbnail 才真正吃内存）
        if im.width * im.height > _MAX_COVER_PIXELS:
            raise HTTPException(400, "图片尺寸过大（长宽乘积不能超过 4000 万像素）")
        im.load()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "图片文件无法解析")
    # 压到 512px 方边内（展示最大约 300px），带透明通道的 PNG 保留 PNG，其余统一 JPG
    try:
        im.thumbnail((512, 512))
        cover_dir = _pl_cover_dir()
        if ext == ".png" and im.mode in ("RGBA", "LA", "P"):
            target = cover_dir / f"pl_{pid}.png"
            im.convert("RGBA").save(target)
        else:
            target = cover_dir / f"pl_{pid}.jpg"
            im.convert("RGB").save(target, quality=85)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "封面处理失败")
    for old_ext in (".png", ".jpg"):
        if old_ext != target.suffix:
            (cover_dir / f"pl_{pid}{old_ext}").unlink(missing_ok=True)
    return f"playlist_covers/{target.name}"


@router.post("/playlists/{pid}/cover")
async def playlist_cover_upload(
    pid: int,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = _own_playlist(db, pid, user.id)
    ext = _PL_COVER_TYPES.get(file.content_type or "")
    if not ext:
        raise HTTPException(400, "仅支持 PNG / JPG / WebP / GIF 图片")
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "封面图片不能超过 10MB")
    if not data:
        raise HTTPException(400, "文件为空")
    try:
        rel = await run_in_threadpool(_process_playlist_cover, data, ext, row.id)
    except HTTPException:
        raise
    row.cover_path = rel
    db.commit()
    return {"ok": True, "playlist": _pl_out(row)}


@router.delete("/playlists/{pid}/cover")
def playlist_cover_remove(pid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = _own_playlist(db, pid, user.id)
    if row.cover_path:
        (Path(cfg.DATA_DIR) / row.cover_path).unlink(missing_ok=True)
        row.cover_path = None
        db.commit()
    return {"ok": True, "playlist": _pl_out(row)}
