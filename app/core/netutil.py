"""客户端 IP 解析（限流维度）。

限流/锁定按 IP 计数，而请求头是客户端可伪造的：默认直接采用 TCP 对端地址，
只有显式设置 `IHUB_TRUST_PROXY_HEADERS=true`（部署在 nginx / Caddy / Lucky 等
反代之后，由反代追加或覆写转发头）时才采信请求头，避免伪造头绕过登录锁定与推送限流。

采信时的取值顺序（`IHUB_TRUSTED_PROXY_HOPS` 默认 1，即只信任最近一跳上游）：
1. `X-Forwarded-For` 从右往左第 N 个值——Go / nginx($proxy_add_x_forwarded_for) / Caddy /
   Traefik 的反代都会把「自己看到的客户端地址」追加在**列表末尾**，客户端自带的伪造值留在
   左侧，因此必须从右往左取；取第一个值等于把伪造权交给调用方。
2. `X-Real-IP`（单值头，代理若覆写则可用）。
3. 都不可用 / 不是合法 IP → 回退 TCP 对端地址。

多级代理（如 Cloudflare → 本机 nginx）时把 HOPS 设为代理层数，取「最外层可信代理写入的那个值」。
"""

import html as _html_mod
import ipaddress
import re as _re

from fastapi import Request

from app.core.config import settings

# logo_url 展示端按 <img src> 使用；允许 http(s)://、/ 相对路径与裸域名
# （展示端自动补 https://a.favicon.im/ 前缀），但拒绝可执行/危险 scheme 入库
_DANGEROUS_URL_SCHEMES = ("javascript:", "vbscript:", "data:text/html", "data:image/svg+xml")


def safe_logo_url(value: str | None) -> str | None:
    """logo_url 入库前过滤：深度实体解码 + 剥空白后命中危险 scheme 一律拒绝。

    与 navlinks._ensure_http_url 的白名单不同：logo 允许无 scheme 的裸域名
    （前端会补全 favicon.im 前缀），所以只做黑名单，但解码归一化必须同样彻底——
    `jav\\tascript:` 与 `&#106;avascript:` 在 <img src> 语义下等价。
    """
    if not value:
        return value
    text = value
    for _ in range(5):
        decoded = _html_mod.unescape(text)
        if decoded == text:
            break
        text = decoded
    probe = _re.sub(r"[\t\r\n\f\x00\s]", "", text).lower()
    if probe.startswith(_DANGEROUS_URL_SCHEMES):
        return None
    return value


def host_resolves_private(host: str) -> str | None:
    """域名/IP 解析出的 IP 命中私网/环回/链路本地/保留/多播段时返回该 IP，否则 None。

    供普通用户可触发出站连接的入口做 SSRF 校验（与 logos._assert_public_http_url
    同一策略：getaddrinfo 的**所有**结果都必须是公网 IP，防 DNS 多解析绕过）。
    解析失败（域名不存在）返回 None——交由连接环节按「连接失败」回报，不改写语义。
    """
    if not host or not host.strip():
        return None
    import socket

    try:
        infos = socket.getaddrinfo(host.strip(), None)
    except OSError:
        return None
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if not ip.is_global or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return str(ip)
    return None


def _parse_ip(raw: str) -> str:
    """取合法 IP 文本；非法值（"unknown"、注入的垃圾串）返回空串。"""
    v = (raw or "").strip().strip('"')
    if v.startswith("[") and "]" in v:  # [2001:db8::1]:1234
        v = v[1 : v.index("]")]
    elif v.count(":") == 1 and "." in v:  # 1.2.3.4:5678
        v = v.split(":", 1)[0]
    if not v:
        return ""
    try:
        ipaddress.ip_address(v)
    except ValueError:
        return ""
    return v


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else ""
    if not settings.TRUST_PROXY_HEADERS:
        return peer

    hops = max(1, settings.TRUSTED_PROXY_HOPS)
    # 同一头可能出现多行（多次 Set），合并后再按从右往左取
    values = [
        part
        for line in request.headers.getlist("x-forwarded-for")
        for part in line.split(",")
        if part.strip()
    ]
    if len(values) >= hops:
        candidate = _parse_ip(values[-hops])
        if candidate:
            return candidate

    candidate = _parse_ip(request.headers.get("x-real-ip", ""))
    if candidate:
        return candidate

    return peer
