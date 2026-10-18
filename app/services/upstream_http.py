"""上游 HTTP 出站（标准库 urllib，无第三方依赖）。

音乐 / 影视 / 电台等所有出站请求共用：连接类失败自动重试一次（HTTP 状态错误不重试）、
小响应带字节上限读取、流式转发透传 Range/Content-Range。

"""

import time
from urllib.error import HTTPError as UrlHTTPError
from urllib.error import URLError
from urllib.request import Request as UrlRequest, urlopen

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

HTTP_TIMEOUT = 8


def urlopen_retry(req: UrlRequest, timeout: int):
    """连接类失败（拒绝/超时/网络抖动）自动重试一次；HTTP 状态错误不重试。"""
    last: Exception | None = None
    for attempt in range(2):
        try:
            return urlopen(req, timeout=timeout)
        except UrlHTTPError:
            raise
        except (URLError, TimeoutError, ConnectionError, OSError) as e:
            last = e
            if attempt == 0:
                time.sleep(0.4)
    raise last if last else RuntimeError("request failed")


def conn_message(e: Exception) -> str:
    reason = str(getattr(e, "reason", None) or e)
    if "10061" in reason or isinstance(getattr(e, "reason", None), ConnectionRefusedError):
        return "无法连接音乐服务器（对方拒绝连接）：请确认服务器与 Navidrome 是否在线"
    if "10060" in reason or "timed out" in reason:
        return "连接音乐服务器超时：请稍后再试"
    return f"无法连接上游服务：{e}"


def http(
    url: str,
    method: str = "GET",
    headers: dict | None = None,
    data: bytes | None = None,
    timeout: int = HTTP_TIMEOUT,
    max_bytes: int = 10 * 1024 * 1024,
):
    """JSON/封面等小响应的读取；max_bytes 封顶（上游异常返回超大 body 时防内存放大）。"""
    req = UrlRequest(url, method=method, data=data, headers=headers or {})
    try:
        with urlopen_retry(req, timeout) as resp:
            return resp.status, resp.read(max_bytes)
    except UrlHTTPError as e:  # 非 2xx：读出错误体便于提示
        try:
            detail = e.read()[:200].decode("utf-8", "replace")
        except Exception:
            detail = ""
        raise HTTPException(502, f"上游返回 {e.code}：{detail}") from None
    except (URLError, TimeoutError, OSError) as e:
        raise HTTPException(502, conn_message(e)) from None


def http_open(url: str, headers: dict | None = None, timeout: int = 30):
    """打开上游连接返回原始响应（流式转发用）；非 2xx 统一 502。"""
    req = UrlRequest(url, headers=headers or {})
    try:
        return urlopen_retry(req, timeout)
    except UrlHTTPError as e:
        try:
            detail = e.read()[:200].decode("utf-8", "replace")
        except Exception:
            detail = ""
        raise HTTPException(502, f"上游返回 {e.code}：{detail}") from None
    except (URLError, TimeoutError, OSError) as e:
        raise HTTPException(502, conn_message(e)) from None


def http_passthrough_401(
    url: str,
    method: str = "GET",
    headers: dict | None = None,
    data: bytes | None = None,
    timeout: int = HTTP_TIMEOUT,
    max_bytes: int = 10 * 1024 * 1024,
):
    """小响应读取；401 原样返回 (401, body) 供调用方清缓存重认证一次，其余非 2xx 仍统一 502。

    需要「令牌被上游吊销后自动重认证」的调用方（Jellyfin）用本函数：`http` 会把 401
    一并转成 502，重认证分支永远进不去。
    """
    req = UrlRequest(url, method=method, data=data, headers=headers or {})
    try:
        with urlopen_retry(req, timeout) as resp:
            return resp.status, resp.read(max_bytes)
    except UrlHTTPError as e:
        if e.code == 401:
            try:
                return 401, e.read(max_bytes)
            except Exception:
                return 401, b""
        try:
            detail = e.read()[:200].decode("utf-8", "replace")
        except Exception:
            detail = ""
        raise HTTPException(502, f"上游返回 {e.code}：{detail}") from None
    except (URLError, TimeoutError, OSError) as e:
        raise HTTPException(502, conn_message(e)) from None


def open_stream_raw(full_url: str, headers: dict) -> object:
    """流式转发专用打开：UrlHTTPError 原样抛给调用方（401 重认证要区分状态码），
    其余连接错误统一 502。"""
    req = UrlRequest(full_url, headers=headers)
    try:
        return urlopen_retry(req, 30)
    except UrlHTTPError:
        raise
    except (URLError, TimeoutError, OSError) as e:
        raise HTTPException(502, conn_message(e)) from None


def proxy_stream(upstream, fallback_type: str = "audio/mpeg"):
    """把上游音频/视频响应包装成分块 StreamingResponse，透传 Range/Content-Range，
    浏览器拖动进度条（Range 请求）全程可用；不再整首读入内存。"""
    if upstream.status not in (200, 206):
        # http_open 已把非 2xx 拦下，这里兜底：把上游错误体当媒体回给播放器
        # 会让进度条/重试行为异常且难排查
        try:
            upstream.close()
        except Exception:
            pass
        raise HTTPException(502, f"上游返回异常状态 {upstream.status}")
    headers: dict[str, str] = {}
    status = 200
    content_range = upstream.headers.get("Content-Range")
    if content_range:
        headers["Content-Range"] = content_range
        status = upstream.status
    accept_ranges = upstream.headers.get("Accept-Ranges")
    if accept_ranges:
        headers["Accept-Ranges"] = accept_ranges
    content_length = upstream.headers.get("Content-Length")
    if content_length:
        headers["Content-Length"] = content_length
    media_type = upstream.headers.get("Content-Type") or fallback_type

    def gen():
        try:
            while True:
                chunk = upstream.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                upstream.close()
            except Exception:
                pass

    return StreamingResponse(gen(), status_code=status, media_type=media_type, headers=headers)
