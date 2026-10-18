"""TMDB 海报/剧照获取（影视中心在线补全，默认启用、失败一律静默）。

- 只认 NFO 里的 TMDB 编号且必须是纯数字（这里再校验一次；拼 URL 前 quote，防路径/参数注入）
- 走 TMDB API v3，需要 API Key（官网网页有 Cloudflare 人机验证，不做无 Key 的网页兜底）
- API 与图片下载共用代理设置；base 地址可配置（默认官方域名，国内可指向镜像或配代理）
- 下载缓存到 data/video_covers/：poster-<kind>-<id>.<ext> / backdrop-<kind>-<id>.<ext>
  （kind = movie / tv；缓存文件即"已补全"标记，只补缺的，删除条目后由调用方清理）
"""

from __future__ import annotations

import json as jsonlib
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

from urllib.request import Request as UrlRequest

logger = logging.getLogger(__name__)

ID_RE = re.compile(r"^\d{1,10}$")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
LOGO_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".svg")  # TMDB 的 logo 常见 png / svg
MAX_IMAGE_BYTES = 5 * 1024 * 1024
API_TIMEOUT = 10
USER_AGENT = "iHub/1.0"
FANART_MAX = 6  # 详情页剧照轮播：每个条目最多缓存几张（主图 + 扩展图）

API_DEFAULT = "https://api.themoviedb.org"
IMAGE_DEFAULT = "https://image.tmdb.org"


def _opener(proxy: str):
    if proxy:
        handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        return urllib.request.build_opener(handler)
    return urllib.request.build_opener()


def cache_path(art_dir: Path, kind: str, tmdb_id: str, art: str = "poster") -> Path | None:
    """已落盘的缓存图（后缀未知，按常见后缀探测）；art = poster / backdrop / logo；无则 None。"""
    if art not in ("poster", "backdrop", "logo"):
        return None
    exts = LOGO_EXTS if art == "logo" else IMAGE_EXTS
    base = f"{art}-{'movie' if kind == 'movie' else 'tv'}-{tmdb_id}"
    for ext in exts:
        cand = art_dir / (base + ext)
        try:
            if cand.is_file():
                return cand
        except OSError:
            continue
    return None


def missing_art(art_dir: Path, kind: str, tmdb_id: str) -> set[str]:
    """缓存里还缺哪些图（poster/backdrop/logo）。"""
    return {a for a in ("poster", "backdrop", "logo") if cache_path(art_dir, kind, tmdb_id, a) is None}


def cached_arts(art_dir: Path, kind: str, tmdb_id: str, art: str = "backdrop") -> list[Path]:
    """同 id 的全部缓存图（主图 + 序号扩展图 `-2`/`-3`…），顺序即展示顺序；无则空列表。"""
    if art not in ("poster", "backdrop", "logo"):
        return []
    section = "movie" if kind == "movie" else "tv"
    exts = LOGO_EXTS if art == "logo" else IMAGE_EXTS
    out: list[Path] = []
    primary = cache_path(art_dir, kind, tmdb_id, art)
    if primary is not None:
        out.append(primary)
    for k in range(2, 12):  # 序号从 2 起（FANART_MAX 上限保护）
        for ext in exts:
            cand = art_dir / f"{art}-{section}-{tmdb_id}-{k}{ext}"
            try:
                if cand.is_file():
                    out.append(cand)
                    break
            except OSError:
                continue
    return out


def _tried_path(art_dir: Path, kind: str, tmdb_id: str) -> Path:
    section = "movie" if kind == "movie" else "tv"
    return art_dir / f"bd-tried-{section}-{tmdb_id}"


def backdrop_tried(art_dir: Path, kind: str, tmdb_id: str) -> bool:
    """扩展剧照是否已尝试补全过（避免每轮扫描对"上游只有一张"的条目反复请求）。"""
    try:
        return _tried_path(art_dir, kind, tmdb_id).is_file()
    except OSError:
        return False


def _api_item(api_base: str, kind: str, tmdb_id: str, api_key: str, proxy: str, with_images: bool = False) -> dict | None:
    section = "movie" if kind == "movie" else "tv"
    url = (
        f"{api_base.rstrip('/')}/3/{section}/{tmdb_id}"
        f"?api_key={quote(api_key, safe='')}&language=zh-CN"
    )
    if with_images:
        url += "&append_to_response=images"
    req = UrlRequest(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with _opener(proxy).open(req, timeout=API_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            data = jsonlib.loads(resp.read(1_000_000))
    except Exception:  # noqa: BLE001 — 在线补全失败绝不抛出
        logger.debug("TMDB 查询失败：%s/%s", section, tmdb_id, exc_info=True)
        return None
    return data if isinstance(data, dict) else None


def _download(image_base: str, size: str, path: str, art_dir: Path, stem: str, proxy: str) -> bool:
    if not path.startswith("/"):
        return False
    suffix = Path(path).suffix.lower()
    if suffix not in LOGO_EXTS:
        suffix = ".jpg"
    url = f"{image_base.rstrip('/')}/t/p/{size}{path}"
    dest = art_dir / (stem + suffix)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        req = UrlRequest(url, headers={"User-Agent": USER_AGENT})
        art_dir.mkdir(parents=True, exist_ok=True)
        with _opener(proxy).open(req, timeout=API_TIMEOUT + 15) as resp:
            if resp.status != 200:
                return False
            written = 0
            with open(tmp, "wb") as fh:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_IMAGE_BYTES:
                        raise ValueError("image too large")
                    fh.write(chunk)
        tmp.replace(dest)
        return True
    except Exception:  # noqa: BLE001 — 同上
        logger.debug("TMDB 图片下载失败：%s", url, exc_info=True)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


_ZH_LANGS = ("zh", "cn", "zh-cn", "zh-tw", "zh-hk")


def _pick_logo_path(data: dict) -> str | None:
    """从 images.logos 里挑一个 logo：中文优先、png 优先，语言不限（找不到合适的就取第一个）。"""
    logos = (data.get("images") or {}).get("logos") or []
    best: tuple[tuple[int, int], str] | None = None
    for entry in logos:
        path = entry.get("file_path") or ""
        if not isinstance(path, str) or not path.startswith("/"):
            continue
        lang = (entry.get("iso_639_1") or "").lower()
        if lang in _ZH_LANGS or lang.startswith("zh"):
            rank = 0
        elif lang in ("en", ""):
            rank = 1
        else:
            rank = 2
        png = 0 if path.lower().endswith(".png") else 1
        key = (rank, png)
        if best is None or key < best[0]:
            best = (key, path)
    return best[1] if best else None


def _pick_backdrop_paths(data: dict, limit: int) -> list[str]:
    """剧照候选：主图（backdrop_path）在前，其次 images.backdrops 里挑补充图（无语言标记优先，
    按票分/票数排序），去重后最多 limit 张。"""
    out: list[str] = []
    primary = data.get("backdrop_path")
    if isinstance(primary, str) and primary.startswith("/"):
        out.append(primary)
    cands: list[tuple[int, float, int, str]] = []
    for entry in (data.get("images") or {}).get("backdrops") or []:
        path = entry.get("file_path") or ""
        if not isinstance(path, str) or not path.startswith("/") or path in out:
            continue
        lang = (entry.get("iso_639_1") or "").lower()
        try:
            va = float(entry.get("vote_average") or 0)
        except (TypeError, ValueError):
            va = 0.0
        try:
            vc = int(entry.get("vote_count") or 0)
        except (TypeError, ValueError):
            vc = 0
        cands.append((0 if not lang else 1, -va, -vc, path))
    cands.sort()
    for _, _, _, path in cands:
        if len(out) >= limit:
            break
        out.append(path)
    return out[:limit]


def fetch_art(
    art_dir: Path,
    kind: str,
    tmdb_id: str,
    api_key: str,
    proxy: str,
    api_base: str = API_DEFAULT,
    image_base: str = IMAGE_DEFAULT,
    want_poster: bool = True,
    want_backdrop: bool = True,
    want_logo: bool = True,
) -> tuple[bool, bool, bool]:
    """拉取并落盘缺失的海报（w500）/剧照（w1280，最多 FANART_MAX 张）/Logo（w500）；返回三类图是否就绪。

    want_* 由调用方按「本地已有图 + 缓存已有图」逐类给出（本地永远优先，不为已有的图下载）。
    剧照的扩展图（`-2` 起）只在 want_backdrop 且尚未尝试过时补拉一次，落 `bd-tried-*` 标记避免反复请求。
    """
    arts = ("poster", "backdrop", "logo")
    ready = {a: cache_path(art_dir, kind, tmdb_id, a) is not None for a in arts}
    if not api_key or not ID_RE.match(tmdb_id or ""):
        return ready["poster"], ready["backdrop"], ready["logo"]
    wants = {"poster": want_poster, "backdrop": want_backdrop, "logo": want_logo}
    need_poster = wants["poster"] and not ready["poster"]
    need_logo = wants["logo"] and not ready["logo"]
    need_backdrop = wants["backdrop"]  # 调用方已按「本地无图 + 未尝试过」给出
    if not (need_poster or need_backdrop or need_logo):
        return ready["poster"], ready["backdrop"], ready["logo"]
    data = _api_item(api_base, kind, tmdb_id, api_key, proxy, with_images=need_logo or need_backdrop)
    if data is None:
        return ready["poster"], ready["backdrop"], ready["logo"]
    section = "movie" if kind == "movie" else "tv"
    if need_poster and isinstance(data.get("poster_path"), str):
        _download(image_base, "w500", data["poster_path"], art_dir, f"poster-{section}-{tmdb_id}", proxy)
    if need_backdrop:
        paths = _pick_backdrop_paths(data, FANART_MAX)
        if not ready["backdrop"] and paths:
            _download(image_base, "w1280", paths[0], art_dir, f"backdrop-{section}-{tmdb_id}", proxy)
        for k, path in enumerate(paths[1:], start=2):
            _download(image_base, "w1280", path, art_dir, f"backdrop-{section}-{tmdb_id}-{k}", proxy)
        # 落标记：拿到多张、或上游本来就没有更多（单张）——两种情况都不必再试；
        # 上游有多张但全下载失败时不落标记，下轮扫描/详情页会重试
        if len(cached_arts(art_dir, kind, tmdb_id, "backdrop")) > 1 or len(paths) <= 1:
            try:
                _tried_path(art_dir, kind, tmdb_id).write_bytes(b"1")
            except OSError:
                pass
    if need_logo:
        logo_path = _pick_logo_path(data)
        if logo_path:
            _download(image_base, "w500", logo_path, art_dir, f"logo-{section}-{tmdb_id}", proxy)
    return (
        cache_path(art_dir, kind, tmdb_id, "poster") is not None,
        cache_path(art_dir, kind, tmdb_id, "backdrop") is not None,
        cache_path(art_dir, kind, tmdb_id, "logo") is not None,
    )


# ---------------- 无编号兜底：按标题+年份自动匹配 ----------------

_NORM_STRIP_RE = re.compile(r"[\s\-_.·:：,，。；;！!？?（）()\[\]【】'\"“”‘’&+/]+")


def _norm_title(s: str) -> str:
    return _NORM_STRIP_RE.sub("", (s or "").lower())


def _title_hit(query: str, name: str) -> bool:
    q, n = _norm_title(query), _norm_title(name)
    return bool(q) and bool(n) and (q == n or q in n or n in q)


def _cand_year(r: dict, kind: str) -> int:
    m = re.match(r"(\d{4})", (r.get("release_date") if kind == "movie" else r.get("first_air_date")) or "")
    return int(m.group(1)) if m else 0


def _year_ok(kind: str, cand_year: int, want_year: int) -> bool:
    """电影：年份 ±1；剧集：上游首播年 ≤ nfo 年 + 1（nfo 年份常是季年份，不能要求相等）。无年份要求则放开。"""
    if not want_year:
        return True
    if not cand_year:
        return False
    if kind == "movie":
        return abs(cand_year - want_year) <= 1
    return cand_year <= want_year + 1


def search(api_base: str, kind: str, query: str, api_key: str, proxy: str) -> list[dict]:
    """TMDB 搜索：返回候选列表（失败返回空）。标题只做 quote 编码，绝不拼进 URL 参数之外的位置。"""
    section = "movie" if kind == "movie" else "tv"
    if not query or not api_key:
        return []
    url = (
        f"{api_base.rstrip('/')}/3/search/{section}"
        f"?api_key={quote(api_key, safe='')}&language=zh-CN&include_adult=false"
        f"&query={quote(query, safe='')}"
    )
    req = UrlRequest(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with _opener(proxy).open(req, timeout=API_TIMEOUT) as resp:
            if resp.status != 200:
                return []
            data = jsonlib.loads(resp.read(1_000_000))
    except Exception:  # noqa: BLE001 — 在线补全失败绝不抛出
        logger.debug("TMDB 搜索失败：%s / %s", section, query, exc_info=True)
        return []
    results = data.get("results") if isinstance(data, dict) else None
    return [r for r in (results or []) if isinstance(r, dict)]


def resolve_id(
    api_base: str, kind: str, titles: list[str] | str, year: int, api_key: str, proxy: str
) -> str | None:
    """NFO 无编号时的兜底匹配：按候选标题（按优先级依次尝试）搜索，**宁缺毋滥**——
    候选必须年份吻合；同名多候选且年份无法区分时放弃（返回 None），绝不猜。"""
    if isinstance(titles, str):
        titles = [titles]
    for query in dict.fromkeys(t.strip() for t in titles if t and t.strip()):
        cands = [
            r
            for r in search(api_base, kind, query, api_key, proxy)
            if _year_ok(kind, _cand_year(r, kind), year)
        ]
        if not cands:
            continue
        strong = [
            r
            for r in cands
            if _title_hit(query, r.get("title") or r.get("name") or "")
            or _title_hit(query, r.get("original_title") or r.get("original_name") or "")
        ]
        if len(strong) == 1:
            pick = strong[0]
        elif len(strong) > 1 and year and kind == "movie":
            # 仅电影可用「上映年精确相等」消歧；剧集 nfo 年份常是季年份、上游是首播年，精确匹配会选错
            exact = [r for r in strong if _cand_year(r, kind) == year]
            pick = exact[0] if len(exact) == 1 else None
        elif not strong and len(cands) == 1:
            pick = cands[0]
        else:
            pick = None
        if pick is None:
            continue
        tmdb_id = str(pick.get("id") or "")
        if ID_RE.match(tmdb_id):
            return tmdb_id
    return None


_CACHE_NAME_RE = re.compile(r"^(poster|backdrop|logo)-(movie|tv)-(\d{1,10})(?:-\d{1,2})?\.[A-Za-z0-9]+$")
_TRIED_NAME_RE = re.compile(r"^bd-tried-(movie|tv)-(\d{1,10})$")

def prune_cache(art_dir: Path, valid: set[tuple[str, str]]) -> int:
    """删除不再被库引用的缓存图、`bd-tried-*` 标记与残留 .part 文件；返回删除数。
    valid 元素为 (kind, tmdb_id)。"""
    removed = 0
    try:
        entries = [p for p in art_dir.iterdir() if p.is_file()]
    except OSError:
        return 0
    for path in entries:
        name = path.name
        if name.endswith(".part"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
            continue
        m = _CACHE_NAME_RE.match(name)
        if m:
            keep = (m.group(2), m.group(3)) in valid  # 缓存图：组 2=kind、组 3=id
        else:
            m = _TRIED_NAME_RE.match(name)
            if not m:
                continue
            keep = (m.group(1), m.group(2)) in valid  # 标记文件：组 1=kind、组 2=id
        if keep:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed
