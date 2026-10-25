"""qBittorrent WebUI API 客户端（标准库实现，无第三方依赖）。

qB 4.x / 5.x 兼容点：
- 会话 Cookie 名称可能是 SID，也可能是 QBT_SID_<port>：由 CookieJar 自动保存，不写死；
- 非 GET 请求必须带与访问地址一致的 Referer/Origin（CSRF）；
- 5.x 把 pause/resume 改名为 stop/start，状态名 paused* → stopped*；
  这里按 webapi 能力做一次回退，不改调用方语义。
"""

from __future__ import annotations

import http.cookiejar
import json
import secrets
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import (
    HTTPCookieProcessor,
    HTTPSHandler,
    Request,
    build_opener,
)

from app.services.seed_common import (
    SeedAuthError,
    SeedError,
    is_connect_refused,
    normalize_base_url,
    parse_json,
)

DEFAULT_TIMEOUT = 8
ACTION_TIMEOUT = 20
# 连接失败熔断窗口（与 moviepilot.py 同语义）：qB 不可达时 30s 内秒回同一错误，
# 避免概览轮询反复撞超时占满线程池/DB 连接池
BREAKER_COOLDOWN = 30.0
MAX_RESPONSE = 32 * 1024 * 1024


class QbClient:
    def __init__(
        self,
        base_url: str,
        *,
        username: str = "",
        password: str = "",
        auth_mode: str = "password",
        verify_tls: bool = True,
    ) -> None:
        self.base_url = normalize_base_url(base_url)
        self.username = username or ""
        self.password = password or ""
        self.auth_mode = auth_mode if auth_mode in ("password", "none") else "password"
        self.verify_tls = verify_tls
        self._lock = threading.RLock()
        self._logged_in = self.auth_mode == "none"
        self._login_failed = False
        # 登录失败冷却：避免页面轮询/事件线程在 qB 封禁或临时拒绝时反复登录，
        # 反而延长 qB 的登录限制。手动“保存并测试”会重建客户端，不受此冷却影响。
        # 连续失败按 1/2/5/10/30 分钟退避，给 qB 的临时 IP 封禁留出解除时间。
        self._login_retry_at = 0.0
        self._login_fail_count = 0
        self._jar = http.cookiejar.CookieJar()
        handlers = [HTTPCookieProcessor(self._jar)]
        if self.base_url.lower().startswith("https://"):
            ctx = ssl.create_default_context()
            if not verify_tls:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            handlers.append(HTTPSHandler(context=ctx))
        self._opener = build_opener(*handlers)
        # 连接熔断状态（与登录冷却相互独立）：客户端实例与连接一一对应
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

    # ---- 底层请求 ----
    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        data: bytes | None = None,
        headers: dict | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> tuple[int, bytes, dict]:
        url = self.base_url + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None and v != ""}
            if clean:
                url += ("&" if "?" in url else "?") + urlencode(clean, doseq=True)
        req_headers = {
            "Referer": self.base_url,
            "Origin": self.base_url,
            "User-Agent": "iHub-Seed/1.0",
        }
        req_headers.update(headers or {})
        req = Request(url, data=data, method=method, headers=req_headers)
        self._breaker_check()
        # 连接在建立前被拒（高并发突发下偶发 RST/DNS 抖动）时，请求未被 qB 处理，
        # 退避后重试一次是安全的；超时不重试（可能已受理，避免写操作重复执行）
        for attempt in range(2):
            try:
                with self._opener.open(req, timeout=timeout) as resp:
                    body = resp.read(MAX_RESPONSE)
                    result = (resp.status, body, dict(resp.headers))
                self._breaker_clear()
                return result
            except HTTPError as e:
                self._breaker_clear()
                body = b""
                try:
                    body = e.read(4096)
                except Exception:
                    pass
                detail = body.decode("utf-8", "replace").strip()[:200]
                if e.code == 401:
                    raise SeedAuthError("qBittorrent 认证失败，请检查用户名/密码或白名单设置")
                if e.code == 403:
                    raise SeedAuthError(
                        "qBittorrent 拒绝访问（403）：可能是 IP 被临时封禁或白名单限制，请稍后重试"
                    )
                raise SeedError(f"qBittorrent 返回 {e.code}：{detail or e.reason}", 502)
            except (URLError, TimeoutError, OSError) as e:
                reason = str(getattr(e, "reason", None) or e)
                if attempt == 0 and is_connect_refused(e):
                    time.sleep(0.5)
                    continue
                msg = f"无法连接 qBittorrent：{reason}"
                self._breaker_record(msg)
                raise SeedError(msg, 503)

    def _json(self, method: str, path: str, **kwargs):
        # 必须走 _api：它会先登录/续期 SID。直接 _request 会在新客户端上
        # 未登录就请求业务接口，qB 返回 403（表现为「测试连接正常，页面全失败」）。
        _, body, _ = self._api(method, path, **kwargs)
        value = parse_json(body)
        return value if value is not None else {}

    def _post_form(self, path: str, fields: dict, *, timeout: int = DEFAULT_TIMEOUT) -> bytes:
        clean = {k: v for k, v in fields.items() if v is not None and v != ""}
        data = urlencode(clean, doseq=True).encode("utf-8")
        _, body, _ = self._api(
            "POST",
            path,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
        )
        return body

    # ---- 登录 ----
    def login(self) -> None:
        if self.auth_mode == "none":
            self._logged_in = True
            return
        if not self.username:
            raise SeedAuthError("qBittorrent 未配置用户名")
        if time.time() < self._login_retry_at:
            minutes = max(1, int((self._login_retry_at - time.time()) // 60) + 1)
            raise SeedAuthError(
                f"qBittorrent 登录失败，已暂停重试约 {minutes} 分钟，请在设置中手动测试连接"
            )
        # 清掉旧 SID：上一轮失败/过期会话不应继续参与本次登录后的请求
        self._jar.clear()
        data = urlencode(
            {"username": self.username, "password": self.password}
        ).encode("utf-8")
        try:
            _, body, _ = self._request(
                "POST",
                "/api/v2/auth/login",
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except SeedAuthError as e:
            # 403 是 qB 的 IP 临时封禁，不是密码错误：按封禁时长退避，
            # 否则每次页面轮询都去登录，会把封禁一直续上。
            self._mark_login_failure(banned="403" in e.message)
            raise
        except SeedError:
            self._mark_login_failure()
            raise
        text = body.decode("utf-8", "replace").strip().lower()
        if text.startswith("fails") or text.startswith("fail"):
            self._mark_login_failure()
            raise SeedAuthError(
                "qBittorrent 登录失败，请检查用户名/密码；连续失败会触发 qB 的临时 IP 封禁"
            )
        self._logged_in = True
        self._login_failed = False
        self._login_fail_count = 0
        self._login_retry_at = 0.0

    def _mark_login_failure(self, *, banned: bool = False) -> None:
        self._logged_in = False
        self._login_failed = True
        self._login_fail_count = min(self._login_fail_count + 1, 6)
        if banned:
            # qB 默认 web_ui_ban_duration=3600：封禁期间不再自动登录，
            # 给用户留出重启 qB / 等待封禁解除的时间。
            self._login_retry_at = time.time() + 3600
            return
        delays = (60, 120, 300, 600, 1800)
        self._login_retry_at = time.time() + delays[
            min(self._login_fail_count - 1, len(delays) - 1)
        ]

    def _ensure_login(self) -> None:
        if not self._logged_in:
            self.login()

    def cooldown_remaining(self) -> float:
        """登录冷却剩余秒数；事件线程据此跳过轮询，避免无意义的 DB 写入与日志。"""
        return max(0.0, self._login_retry_at - time.time())

    def _api(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        data: bytes | None = None,
        headers: dict | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        with self._lock:
            self._ensure_login()
            try:
                status, body, hdrs = self._request(
                    method, path, params=params, data=data, headers=headers, timeout=timeout
                )
            except SeedAuthError:
                # 会话过期：重登一次再试
                self._logged_in = False
                self.login()
                status, body, hdrs = self._request(
                    method, path, params=params, data=data, headers=headers, timeout=timeout
                )
            return status, body, hdrs

    # ---- 版本/状态 ----
    def app_version(self) -> str:
        _, body, _ = self._api("GET", "/api/v2/app/version")
        return body.decode("utf-8", "replace").strip()[:64]

    def webapi_version(self) -> str:
        _, body, _ = self._api("GET", "/api/v2/app/webapiVersion")
        return body.decode("utf-8", "replace").strip()[:64]

    def transfer_info(self) -> dict:
        value = self._json("GET", "/api/v2/transfer/info")
        return value if isinstance(value, dict) else {}

    def sync_maindata(self, rid: int = 0) -> dict:
        value = self._json("GET", "/api/v2/sync/maindata", params={"rid": rid})
        return value if isinstance(value, dict) else {}

    def test(self) -> dict:
        # 手动测试必须真实发起连接：临时挂起熔断
        self._breaker_suspended = True
        try:
            return self._test_impl()
        finally:
            self._breaker_suspended = False

    def _test_impl(self) -> dict:
        app = self.app_version()
        webapi = self.webapi_version()
        info = self.transfer_info()
        return {
            "ok": True,
            "version": app,
            "webapi_version": webapi,
            "download_speed": int(info.get("dl_info_speed") or 0),
            "upload_speed": int(info.get("up_info_speed") or 0),
        }

    # ---- 种子列表/详情 ----
    def torrents(
        self,
        *,
        filter: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        hashes: str | None = None,
        sort: str | None = None,
        reverse: bool | None = None,
    ) -> list[dict]:
        params = {
            "filter": filter,
            "category": category,
            "tag": tag,
            "hashes": hashes,
            "sort": sort,
            "reverse": "true" if reverse else ("false" if reverse is not None else None),
        }
        value = self._json("GET", "/api/v2/torrents/info", params=params)
        return value if isinstance(value, list) else []

    def torrent_properties(self, torrent_hash: str) -> dict:
        value = self._json("GET", "/api/v2/torrents/properties", params={"hash": torrent_hash})
        return value if isinstance(value, dict) else {}

    def torrent_files(self, torrent_hash: str) -> list[dict]:
        value = self._json("GET", "/api/v2/torrents/files", params={"hash": torrent_hash})
        return value if isinstance(value, list) else []

    def torrent_trackers(self, torrent_hash: str) -> list[dict]:
        value = self._json("GET", "/api/v2/torrents/trackers", params={"hash": torrent_hash})
        return value if isinstance(value, list) else []

    def torrent_peers(self, torrent_hash: str) -> dict:
        # qB WebUI 的 Peers 数据在 sync/torrentPeers（torrents/peers 不存在，4.6.7 会 404）
        try:
            value = self._json("GET", "/api/v2/sync/torrentPeers", params={"hash": torrent_hash})
        except SeedError as e:
            # Peers 是详情页的附属信息：单个任务没有 peers 时不应让整个详情失败
            if "404" in e.message:
                return {}
            raise
        return value if isinstance(value, dict) else {}

    def categories(self) -> dict:
        value = self._json("GET", "/api/v2/torrents/categories")
        return value if isinstance(value, dict) else {}

    def tags(self) -> list:
        value = self._json("GET", "/api/v2/torrents/tags")
        return value if isinstance(value, list) else []

    # ---- 操作 ----
    def _action_request(self, action: str, hashes: list[str] | str) -> None:
        hashes_value = "|".join(hashes) if isinstance(hashes, list) else hashes
        paths: list[str]
        if action == "pause":
            paths = ["/api/v2/torrents/pause", "/api/v2/torrents/stop"]
        elif action == "resume":
            paths = ["/api/v2/torrents/resume", "/api/v2/torrents/start"]
        elif action == "recheck":
            paths = ["/api/v2/torrents/recheck"]
        elif action == "reannounce":
            paths = ["/api/v2/torrents/reannounce"]
        else:
            raise SeedError("不支持的种子操作", 400)

        last: SeedError | None = None
        for path in paths:
            try:
                self._post_form(path, {"hashes": hashes_value}, timeout=ACTION_TIMEOUT)
                return
            except SeedError as e:
                last = e
                # 4.x/5.x 命名差异：只有 404/405 才尝试下一个路径
                if e.status_code != 502 or not ("404" in e.message or "405" in e.message):
                    raise
        raise last or SeedError("qBittorrent 操作失败", 502)

    def action(self, torrent_hash: str, action: str) -> None:
        self._action_request(action, [torrent_hash])

    def actions(self, hashes: list[str], action: str) -> None:
        self._action_request(action, hashes)

    def delete(self, torrent_hash: str, delete_files: bool = False) -> None:
        self.delete_many([torrent_hash], delete_files)

    def delete_many(self, hashes: list[str], delete_files: bool = False) -> None:
        body = self._post_form(
            "/api/v2/torrents/delete",
            {"hashes": "|".join(hashes), "deleteFiles": "true" if delete_files else "false"},
            timeout=ACTION_TIMEOUT,
        )
        text = body.decode("utf-8", "replace").strip().lower()
        if text.startswith("fails"):
            raise SeedError("qBittorrent 删除失败", 502)

    @staticmethod
    def _check_action_body(body: bytes, action: str) -> None:
        text = body.decode("utf-8", "replace").strip().lower()
        if text.startswith("fail") or text.startswith("error"):
            raise SeedError(f"qBittorrent {action}失败", 502)

    def set_location(self, hashes: list[str] | str, location: str) -> None:
        """移动种子保存位置；qB 负责移动文件并保持任务。"""
        hashes_value = "|".join(hashes) if isinstance(hashes, list) else hashes
        body = self._post_form(
            "/api/v2/torrents/setLocation",
            {"hashes": hashes_value, "location": location},
            timeout=ACTION_TIMEOUT,
        )
        self._check_action_body(body, "移动保存位置")

    def add_tags(self, hashes: list[str] | str, tags: list[str]) -> None:
        clean = [tag.strip() for tag in tags if tag and tag.strip()]
        if not clean:
            return
        hashes_value = "|".join(hashes) if isinstance(hashes, list) else hashes
        body = self._post_form(
            "/api/v2/torrents/addTags",
            {"hashes": hashes_value, "tags": ",".join(clean)},
            timeout=ACTION_TIMEOUT,
        )
        self._check_action_body(body, "添加标签")

    def remove_tags(self, hashes: list[str] | str, tags: list[str]) -> None:
        clean = [tag.strip() for tag in tags if tag and tag.strip()]
        if not clean:
            return
        hashes_value = "|".join(hashes) if isinstance(hashes, list) else hashes
        body = self._post_form(
            "/api/v2/torrents/removeTags",
            {"hashes": hashes_value, "tags": ",".join(clean)},
            timeout=ACTION_TIMEOUT,
        )
        self._check_action_body(body, "移除标签")

    def set_category(self, hashes: list[str] | str, category: str = "") -> None:
        """设置分类；空字符串也必须发送，不能走 _post_form 的空白字段过滤。"""
        hashes_value = "|".join(hashes) if isinstance(hashes, list) else hashes
        data = urlencode({"hashes": hashes_value, "category": category}).encode("utf-8")
        _, body, _ = self._api(
            "POST",
            "/api/v2/torrents/setCategory",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=ACTION_TIMEOUT,
        )
        self._check_action_body(body, "设置分类")

    def add_url(
        self,
        url: str,
        *,
        save_path: str = "",
        category: str = "",
        tags: str = "",
        paused: bool = False,
    ) -> None:
        fields = {
            "urls": url,
            "savepath": save_path,
            "category": category,
            "tags": tags,
            "paused": "true" if paused else "false",
            "autoTMM": "false" if save_path else None,
        }
        body = self._post_form("/api/v2/torrents/add", fields, timeout=ACTION_TIMEOUT)
        text = body.decode("utf-8", "replace").strip().lower()
        if text.startswith("fails"):
            raise SeedError("qBittorrent 添加种子失败", 502)

    def add_file(
        self,
        filename: str,
        content: bytes,
        *,
        save_path: str = "",
        category: str = "",
        tags: str = "",
        paused: bool = False,
    ) -> None:
        boundary = "----ihub" + secrets.token_hex(10)
        fields = {
            "savepath": save_path,
            "category": category,
            "tags": tags,
            "paused": "true" if paused else "false",
            "autoTMM": "false" if save_path else "",
        }
        parts: list[bytes] = []
        for key, value in fields.items():
            if value == "":
                continue
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode()
            )
        safe_name = (filename or "upload.torrent").replace('"', "_")[-180:]
        parts.append(
            (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"torrents\"; "
                f"filename=\"{safe_name}\"\r\nContent-Type: application/x-bittorrent\r\n\r\n"
            ).encode()
        )
        parts.append(content)
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        data = b"".join(parts)
        _, body, _ = self._api(
            "POST",
            "/api/v2/torrents/add",
            data=data,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            timeout=30,
        )
        text = body.decode("utf-8", "replace").strip().lower()
        if text.startswith("fails"):
            raise SeedError("qBittorrent 添加种子文件失败", 502)


def safe_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
