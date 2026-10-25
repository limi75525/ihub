"""种子模块公共工具：异常、上游地址校验、响应解包。"""

from __future__ import annotations

import ipaddress
import json
import posixpath
from urllib.parse import urlsplit


class SeedError(Exception):
    """种子上游/配置错误。status_code 供 API 层映射为 HTTP 状态。"""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


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
