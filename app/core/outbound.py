"""统一出站代理：内置国外域名白名单命中才走代理，其余一律直连。

作用范围（谁会用它）：
  - 影视 TMDB 刮削（services/tmdb.py，API + 图片下载）
  - 种子封面代理拉图（services/seed_covers.py，TMDB/bgm/anilist/amazon 图床）
明确不走的（不要接入）：MP / qBittorrent / Subsonic（局域网或用户自配服务）、
IMAP（非 HTTP 代理可及）、豆瓣图床（国内直连）。

安全线：私网/回环地址的 URL 一律直连，绝不进代理（防把内网流量送进代理）。
"""

from __future__ import annotations

import ipaddress
import time
import urllib.request
from urllib.parse import urlsplit

from app.models.system_setting import get_setting

PROXY_KEY = "network_proxy"
EXTRA_KEY = "network_proxy_extra_domains"

# 内置白名单：host 等于后缀或以「.后缀」结尾即命中
# ⚠️ TMDB 有两个域名：API/网页是 themoviedb.org，**图片 CDN 是 image.tmdb.org（tmdb.org）**——
# 只写 themoviedb.org 会让所有 TMDB 海报/剧照绕过代理直连（国内被墙 → 502/超时，
# 表现为「代理配了但封面加载不出来」）。两个都要在。
BUILTIN_SUFFIXES: tuple[str, ...] = (
    "themoviedb.org",
    "tmdb.org",
    "bgm.tv",
    "anilist.co",
    "media-amazon.com",
    "ssl-images-amazon.com",
    "coverartarchive.org",
    "github.com",
    "githubusercontent.com",
)

_RETRY_DELAY = 0.5


def _extra_suffixes() -> list[str]:
    raw = get_setting(EXTRA_KEY, "")
    out = []
    for part in raw.replace("；", ",").replace(";", ",").replace("，", ",").split(","):
        d = part.strip().lower().lstrip(".")
        if d:
            out.append(d)
    return out


def _host_matches(host: str, suffixes: tuple[str, ...] | list[str]) -> bool:
    return any(host == s or host.endswith("." + s) for s in suffixes)


def _is_private_host(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def proxy_for_url(url: str) -> str | None:
    """该 URL 是否应走全局出站代理；返回代理地址或 None（直连）。"""
    proxy = (get_setting(PROXY_KEY, "") or "").strip()
    if not proxy:
        return None
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return None
    if not host or _is_private_host(host):
        return None
    if _host_matches(host, BUILTIN_SUFFIXES) or _host_matches(host, _extra_suffixes()):
        return proxy
    return None


def opener_for(url: str, *handlers):
    """按 URL 解析代理并构建 opener；未命中代理时显式禁用系统代理（行为确定，不吃环境变量）。"""
    proxy = proxy_for_url(url)
    handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {})
    return urllib.request.build_opener(handler, *handlers)


def open_with_retry(
    req: urllib.request.Request, timeout: int, *, retry_refused: bool = True, handlers: tuple = ()
):
    """ opener_for(req.full_url) 的带重试封装：连接在建立前被拒（请求未被对端处理，
    POST 亦安全）时退避重试一次；超时不重试（可能已受理，避免写操作重复执行）。
    handlers 透传给 opener（如安全重定向校验）。"""
    opener = opener_for(req.full_url, *handlers)
    last: Exception | None = None
    for attempt in range(2):
        try:
            return opener.open(req, timeout=timeout)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = e
            reason = getattr(e, "reason", None) or e
            refused = isinstance(reason, ConnectionRefusedError) or "10061" in str(reason) or "getaddrinfo" in str(reason)
            if retry_refused and attempt == 0 and refused:
                time.sleep(_RETRY_DELAY)
                continue
            raise
    raise last if last else RuntimeError("request failed")
