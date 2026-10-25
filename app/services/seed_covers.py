"""种子封面图片代理与本地缓存。

MoviePilot 下载历史里的封面往往来自 TMDB / 豆瓣 / Amazon；这些图片对
Referer、网络出口比较敏感，浏览器直连可能被拒。这里只代理白名单内的
HTTPS 图片，按 URL 哈希落盘缓存，并对豆瓣补上可用的 Referer。
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import Request as UrlRequest

from app.core.config import settings

from app.core import outbound
from app.services.seed_common import SeedError
from app.core import data_dirs

logger = logging.getLogger(__name__)

CACHE_TTL = 30 * 24 * 3600
MAX_IMAGE_BYTES = 5 * 1024 * 1024
TIMEOUT = 12
# 抓取失败负缓存：上游不可达（如 TMDB 被墙且代理失效）时，一张封面要干等满超时才 502，
# 种子页几十张卡片来回切换会反复重发全部失败抓取，把线程池/DB 连接池占满、拖慢全站。
# 5 分钟内同 URL 直接秒回（有旧缓存回旧图、没旧缓存报 502），窗口过后自动放行一次真实探测。
FAIL_TTL = 300.0
FAILS: dict[str, tuple[float, str]] = {}
_FAILS_GUARD = threading.Lock()
CACHE_DIR = Path(settings.DATA_DIR) / data_dirs.SEED_COVERS

# 内置图片源：只允许这些域名的 HTTPS 图片（种子模块各来源：TMDB/豆瓣/Amazon/
# Bangumi/AniList/Cover Art Archive）。额外的自建图片代理域名可通过
# IHUB_SEED_COVER_HOSTS="img.example.com,.example.net" 追加（逗号分隔）。
_EXACT_HOSTS = {"image.tmdb.org", "m.media-amazon.com", "lain.bgm.tv", "coverartarchive.org"}
_SUFFIX_HOSTS = (".doubanio.com", ".media-amazon.com", ".ssl-images-amazon.com", ".bgm.tv", ".anilist.co")

_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_TYPE_BY_EXT = {ext: mime for mime, ext in _TYPES.items()}
_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _custom_hosts() -> tuple[set[str], tuple[str, ...]]:
    exact: set[str] = set()
    suffixes: list[str] = []
    for raw in (os.environ.get("IHUB_SEED_COVER_HOSTS") or "").split(","):
        item = raw.strip().lower()
        if not item:
            continue
        if item.startswith("."):
            suffixes.append(item)
        else:
            exact.add(item)
    return exact, tuple(suffixes)


def _host_allowed(host: str) -> bool:
    host = (host or "").strip().lower().rstrip(".")
    if not host:
        return False
    exact, suffixes = _custom_hosts()
    allowed_exact = _EXACT_HOSTS | exact
    if host in allowed_exact:
        return True
    return any(host == suffix.lstrip(".") or host.endswith(suffix) for suffix in (*_SUFFIX_HOSTS, *suffixes))


def _validate_url(raw: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise SeedError("封面地址为空", 400)
    parts = urlsplit(raw)
    if parts.scheme.lower() != "https":
        raise SeedError("封面地址必须是 HTTPS", 400)
    if parts.username or parts.password:
        raise SeedError("封面地址不允许携带凭据", 400)
    host = (parts.hostname or "").strip().lower().rstrip(".")
    if not host or not _host_allowed(host):
        raise SeedError("封面地址不在允许的图片域名内", 400)
    try:
        ipaddress.ip_address(host)
        raise SeedError("封面地址不允许使用 IP", 400)
    except ValueError:
        pass
    return raw


def proxy_url(raw: str) -> str | None:
    """把允许代理的封面地址转成 iHub 代理地址；不适合代理时返回 None。"""
    try:
        _validate_url(raw)
    except SeedError:
        return None
    return "/api/v1/seeds/cover?url=" + quote(raw, safe="")


def _headers(raw: str) -> dict[str, str]:
    host = (urlsplit(raw).hostname or "").lower()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    if host.endswith(".doubanio.com"):
        # 豆瓣图片对来源较敏感；不要带 iHub 的 localhost Referer。
        headers["Referer"] = "https://movie.douban.com/"
    return headers


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        target = urljoin(req.full_url, newurl)
        _validate_url(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


def _media_kind(body: bytes, content_type: str) -> str:
    for magic, kind in _MAGIC:
        if body.startswith(magic):
            return kind
    if body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return "image/webp"
    raise SeedError("上游返回的不是受支持的图片", 404)


def _cache_lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def _cache_file(key: str) -> Path | None:
    for ext in _TYPE_BY_EXT:
        candidate = CACHE_DIR / (key + ext)
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _fetch(raw: str) -> tuple[bytes, str]:
    _validate_url(raw)
    opener = outbound.opener_for(raw, _SafeRedirectHandler())
    req = UrlRequest(raw, headers=_headers(raw))
    try:
        with outbound.open_with_retry(req, TIMEOUT) as resp:
            content_type = (resp.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if content_type not in _TYPES:
                raise SeedError("上游返回了非图片内容", 404)
            length = resp.headers.get("Content-Length")
            if length and int(length) > MAX_IMAGE_BYTES:
                raise SeedError("封面图片超过 5MB", 404)
            body = resp.read(MAX_IMAGE_BYTES + 1)
    except SeedError:
        raise
    except urllib.error.HTTPError as e:
        # 418/403 常见于豆瓣防盗链；统一按拿不到封面处理，让前端回退。
        status = 404 if e.code in (403, 404, 418) else 502
        raise SeedError(f"封面源返回 HTTP {e.code}", status)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = str(getattr(e, "reason", None) or e)
        raise SeedError(f"获取封面失败：{reason}", 502)
    if len(body) > MAX_IMAGE_BYTES:
        raise SeedError("封面图片超过 5MB", 404)
    kind = _media_kind(body, content_type)
    # 上游 Content-Type 与文件魔数冲突时，以魔数为准。
    if kind != content_type:
        content_type = kind
    return body, content_type


def get_cover(raw: str) -> tuple[Path, str]:
    """返回 (缓存文件, mime)。优先缓存；上游失败时使用过期缓存兜底。"""
    _validate_url(raw)
    key = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    with _FAILS_GUARD:
        fail = FAILS.get(key)
    fail_active = bool(fail and now < fail[0])
    with _cache_lock(key):
        cached = _cache_file(key)
        if cached is not None:
            try:
                if now - cached.stat().st_mtime < CACHE_TTL:
                    return cached, _TYPE_BY_EXT.get(cached.suffix.lower(), "image/jpeg")
            except OSError:
                cached = None
        if fail_active:
            # 负缓存命中：上游近期刚失败过。有旧缓存秒回旧图，否则秒报 502，不碰上游
            if cached is not None:
                return cached, _TYPE_BY_EXT.get(cached.suffix.lower(), "image/jpeg")
            raise SeedError(fail[1] if fail else "获取封面失败", 502)
        try:
            body, content_type = _fetch(raw)
        except SeedError as e:
            with _FAILS_GUARD:
                FAILS[key] = (time.time() + FAIL_TTL, e.message)
                if len(FAILS) > 2000:
                    limit = time.time()
                    for stale_key in [k for k, v in FAILS.items() if v[0] < limit][:1000]:
                        FAILS.pop(stale_key, None)
            if cached is not None:
                return cached, _TYPE_BY_EXT.get(cached.suffix.lower(), "image/jpeg")
            raise
        with _FAILS_GUARD:
            FAILS.pop(key, None)
        ext = _TYPES.get(content_type, ".jpg")
        target = CACHE_DIR / f"{key}{ext}"
        tmp = CACHE_DIR / f"{key}.{os.getpid()}.tmp"
        try:
            tmp.write_bytes(body)
            os.replace(tmp, target)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        for stale in CACHE_DIR.glob(key + ".*"):
            if stale != target and stale.suffix in _TYPE_BY_EXT:
                try:
                    stale.unlink(missing_ok=True)
                except OSError:
                    pass
        return target, content_type
