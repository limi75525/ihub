"""种子模块公共工具：异常、上游地址校验、响应解包、共享 HTTP 传输层。"""

from __future__ import annotations

import ipaddress
import json
import posixpath
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPSHandler, Request, build_opener

from app.core.errors import UpstreamError


class SeedError(UpstreamError):
    """种子上游/配置错误（统一由 core.errors 的领域错误映射处理）。"""


class SeedAuthError(SeedError):
    def __init__(self, message: str = "上游认证失败，请检查连接配置") -> None:
        super().__init__(message, 502)


def normalize_base_url(value: str) -> str:
    """校验并归一化管理员配置的上游地址。

    种子连接由管理员显式配置，允许局域网/私网地址（QB/MP 通常就在 NAS 上），
    但仍拒绝非 http(s)、云元数据地址和带用户信息的 URL。
    """
    raw = (value or "").strip().rstrip("/")
    if not raw:
        raise SeedError("请填写服务地址", 400)
    try:
        parsed = urlsplit(raw)
    except ValueError:
        raise SeedError("服务地址格式不正确", 400)
    if parsed.scheme not in ("http", "https"):
        raise SeedError("服务地址只支持 http:// 或 https://", 400)
    if not parsed.hostname:
        raise SeedError("服务地址缺少主机名", 400)
    if parsed.username or parsed.password:
        raise SeedError("服务地址不要包含用户名/密码", 400)
    host = parsed.hostname.strip("[]").lower()
    # 云元数据/保留地址：即使是管理员配置也不应被当作上游
    if host in {"metadata.google.internal", "metadata", "169.254.169.254"}:
        raise SeedError("不允许连接云元数据地址", 400)
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_unspecified or ip.is_multicast:
            raise SeedError("服务地址不能是通配/组播地址", 400)
    except ValueError:
        pass
    return raw


def parse_json(body: bytes):
    """解析 JSON；空响应返回 None，非法 JSON 抛 SeedError。"""
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except (ValueError, UnicodeDecodeError):
        raise SeedError("上游返回了无法解析的内容")


def is_connect_refused(e: Exception) -> bool:
    """连接在建立前就被拒绝（RST / DNS 解析失败）。

    此时请求未被对端处理，重试是安全的（POST 也不会重复执行）；
    超时则可能是对端已受理但响应慢，重试有重复执行风险，调用方不应重试。
    MP/qB 在局域网高并发突发下偶发这类拒绝，退避后单次重试即可恢复。
    """
    reason = getattr(e, "reason", None) or e
    return isinstance(reason, ConnectionRefusedError) or "10061" in str(reason) or "getaddrinfo" in str(reason)


def unwrap_mp(payload):
    """MoviePilot 响应解包：兼容 {success,data}、{data} 与裸列表/对象。"""
    if isinstance(payload, dict):
        if "data" in payload and ("success" in payload or "message" in payload):
            return payload.get("data")
        if set(payload.keys()) == {"data"}:
            return payload["data"]
    return payload


def mp_list(value) -> list:
    """MP 分页响应统一拆包：unwrap_mp 后，字典按 items→list→data 兜底取列表。

    兼容 MP 各版本/插件的分页结构（items / list / data），非字典直接透传；
    结果不是列表时返回空列表。键序统一为 items→list→data（与现多数派一致），
    新端点禁止再手写第四种键序变体。"""
    data = unwrap_mp(value)
    if isinstance(data, dict):
        data = data.get("items") or data.get("list") or data.get("data") or []
    return data if isinstance(data, list) else []


def normalize_remote_path(value) -> str:
    """归一化上游返回的 NAS 路径，用于转媒体历史匹配（不做任何文件系统访问）。"""
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    normalized = posixpath.normpath(raw)
    return "" if normalized == "." else normalized


def mp_transfer_matches(
    row: dict,
    *,
    digest: str = "",
    save_path: str = "",
    name: str = "",
    content_path: str = "",
) -> bool:
    """MP 整理历史是否属于某个 qB 任务。

    优先用 download_hash；MP 的真实整理历史里这个字段可能为 null（尤其刷流
    种子没有下载历史时），此时回退到源路径与 qB 的保存目录/种子名比对。
    """
    if not isinstance(row, dict):
        return False
    row_hash = str(row.get("download_hash") or "").strip().lower()
    want_hash = str(digest or "").strip().lower()
    if row_hash and want_hash and row_hash == want_hash:
        return True
    src_item = row.get("src_fileitem")
    src = normalize_remote_path(
        row.get("src")
        or (src_item.get("path") if isinstance(src_item, dict) else "")
    )
    if not src:
        return False
    candidates = [content_path]
    if save_path and name:
        candidates.append(posixpath.join(str(save_path), str(name)))
    for candidate in candidates:
        base = normalize_remote_path(candidate)
        if base and (src == base or src.startswith(base + "/")):
            return True
    return False


# ---- 共享 HTTP 传输层（MpClient/QbClient 共用：熔断 + connect-refused 重试） ----

# 连接失败熔断窗口：上游不可达时 30s 内后续请求直接秒回同一错误，不再各自干等满超时
# （否则 5s 一轮的概览轮询 × 15s 超时会占满线程池/DB 连接池，整个平台跟着卡）
BREAKER_COOLDOWN = 30.0
MAX_RESPONSE = 32 * 1024 * 1024


class BreakerTransport:
    """MpClient / QbClient 共享的底层 HTTP 传输骨架。

    统一承载：opener 构造（HTTPS + 可选跳过证书校验）、连接熔断三方法、
    `_transport_request` 的「2 次循环 + connect-refused 退避重试 + HTTPError 分类 +
    熔断记录」。客户端差异必须留在子类：认证方式（X-API-KEY/JWT vs Cookie 会话）、
    请求体形态（json/form vs 原始字节/multipart）、HTTPError 的错误分类文案
    （覆写 `_http_error`，各自文案一字不改）、上游名称（`service_name`）。

    行为保持铁律（勿改）：重试只针对连接建立前被拒（is_connect_refused）、
    退避 0.5s、共 2 次尝试；超时不重试（可能已受理，避免 POST 重复执行）；
    熔断阈值/冷却时间/响应体上限以本模块常量为准。
    """

    # 子类须先设置 self.base_url 再调用 _init_opener（两类现状顺序即如此）
    service_name = ""

    def _init_opener(self, verify_tls: bool, handlers: list) -> None:
        """构造 opener；handlers 由子类提供（如 qB 的 HTTPCookieProcessor）。"""
        handlers = list(handlers)
        if str(self.base_url).lower().startswith("https://"):
            ctx = ssl.create_default_context()
            if not verify_tls:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            handlers.append(HTTPSHandler(context=ctx))
        self._opener = build_opener(*handlers)

    def __init__(self) -> None:
        # 连接熔断状态：客户端实例与连接一一对应，保存连接重建时自然复位
        self._fail_lock = threading.Lock()
        self._fail_until = 0.0
        self._fail_msg = ""
        self._breaker_suspended = False

    # ---- 连接熔断 ----
    def _breaker_check(self) -> None:
        if self._breaker_suspended:
            return
        with self._fail_lock:
            active = time.monotonic() < self._fail_until
            msg = self._fail_msg
        if active and msg:
            raise SeedError(msg, 503)

    def _breaker_record(self, msg: str) -> None:
        if self._breaker_suspended:
            return
        with self._fail_lock:
            self._fail_until = time.monotonic() + BREAKER_COOLDOWN
            self._fail_msg = msg

    def _breaker_clear(self) -> None:
        with self._fail_lock:
            self._fail_until = 0.0
            self._fail_msg = ""

    # ---- HTTPError 分类（子类覆写；保持各自错误文案与状态码语义） ----
    def _http_error(self, code: int, detail: str, reason) -> Exception:
        raise NotImplementedError

    # ---- 请求骨架 ----
    def _transport_request(self, req: Request, *, timeout: int) -> tuple[int, bytes, dict]:
        """共享请求骨架：熔断检查 + connect-refused 退避重试 + 错误分类 + 熔断记录。"""
        self._breaker_check()
        # 连接在建立前被拒（上游高压突发下偶发 RST/DNS 抖动）时，请求从未被上游处理，
        # 退避后重试一次是安全的；超时不重试（可能已受理，避免 POST 重复执行）
        for attempt in range(2):
            try:
                with self._opener.open(req, timeout=timeout) as resp:
                    result = (resp.status, resp.read(MAX_RESPONSE), dict(resp.headers))
                self._breaker_clear()
                return result
            except HTTPError as e:
                self._breaker_clear()
                body = b""
                try:
                    body = e.read(4096)
                except Exception:
                    pass
                detail = body.decode("utf-8", "replace").strip()[:240]
                raise self._http_error(e.code, detail, e.reason)
            except (URLError, TimeoutError, OSError) as e:
                reason = str(getattr(e, "reason", None) or e)
                if attempt == 0 and is_connect_refused(e):
                    time.sleep(0.5)
                    continue
                msg = f"无法连接 {self.service_name}：{reason}"
                self._breaker_record(msg)
                raise SeedError(msg, 503)
