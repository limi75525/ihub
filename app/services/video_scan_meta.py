"""影视中心 NAS 扫描管道：文件名解析、NFO 叠加、在线补全（TMDB）、海报/剧照/Logo 探测。

从 api/v1/video.py 平移的纯算法层（读 NFO / 文件系统 / TMDB，不碰路由逻辑）。
边界约定（防回退，改前先读）：
- 所有本地图片命中必须 resolve() 后仍在媒体根内（NFO 引用与符号链接都不能把根外文件带出去），
  `_pick_art` / `_pick_logo` / `_local_fanarts` 内的 relative_to 校验勿删；
- 本地已有图永远优先，在线补全只补缺失的类别（_art_wants 按类判定，勿改回 all()）；
- 在线补全缓存只落 data/video_covers，不回写媒体目录。
"""

import logging
import os
import re
import threading
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.core import data_dirs
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.video_item import VideoItem
from app.services import media_scan, nfo, tmdb
from app.services.settings_store import get_credential, get_cfgs

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

_LOGO_STEMS = ("logo", "clearlogo")


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
    want_poster = tmdb.cache_path(ART_DIR, kind, tmdb_id, "poster") is None and _pick_art(path, root, it) is None
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
        _pick_art(path, root, it) is None
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


# ---------------- 图片探测（海报 / 剧照 / 标题 Logo） ----------------

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


def _pick_art(item_path: Path, root: Path, it: VideoItem) -> Path | None:
    """海报探测：NFO 声明引用 → 自身目录文件名主干 → 通用名 →（分集）剧集目录回探 →
    在线补全缓存（data/video_covers）。剧照轮播列表见 `_fanart_list`，标题 Logo 见 `_pick_logo`。

    所有本地命中都要求解析后仍在媒体根内（目录里放符号链接不能把根外文件带出去）。
    """
    kind = it.kind
    stem = Path(it.path).stem
    ref = it.poster_ref
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
        cached = tmdb.cache_path(ART_DIR, cache_kind, tmdb_id, "poster")
        if cached is not None:
            return cached
    return None


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
