"""MoviePilot v3 客户端。

认证：优先 API_TOKEN（X-API-KEY）；也兼容用户名/密码换 JWT（旧版或未配置 Token 的实例）。
接口：
- MCP REST 辅助端点（官方推荐给非 MCP 程序的入口）：/api/v1/mcp/tools、/tools/call；
- MCP 未覆盖的稳定 REST：通知中心、发现、刷流插件自定义 API；
- 所有响应在服务层归一化，前端不直接消费 MP 原始 JSON。
"""

from __future__ import annotations

import json
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPSHandler, Request, build_opener

from app.services.seed_common import (
    SeedAuthError,
    SeedError,
    is_connect_refused,
    normalize_base_url,
    parse_json,
    unwrap_mp,
)

DEFAULT_TIMEOUT = 15
SEARCH_TIMEOUT = 90
# 推荐页单板块：上游是 MP 代拉的外部 API（TMDB/豆瓣/AniList），NAS 侧耗时波动大
# （实测 5~30s 不等）。25s 是「有限时但少误伤」的折中——配合前端骨架屏，慢板块
# 只是晚点亮；实测仍拉不到的（如 Bangumi 每日放送）由前端 lazy 标记整块隐藏
RECOMMEND_TIMEOUT = 25
# 连接失败熔断窗口：MP 不可达时 30s 内后续请求直接秒回同一错误，不再各自干等满超时
# （否则 5s 一轮的概览轮询 × 15s 超时会占满线程池/DB 连接池，整个平台跟着卡）
BREAKER_COOLDOWN = 30.0
MAX_RESPONSE = 32 * 1024 * 1024

_MEDIA_SOURCES = {"themoviedb", "douban", "bangumi", "imdb", "tvdb", "musicbrainz"}
_SOURCE_ALIASES = {"tmdb": "themoviedb", "douban_music": "doubanmusic", "audio_db": "theaudiodb"}

# 探索页来源 -> MP REST 路径（与 MP 前端实际请求保持一致）
DISCOVER_PATHS = {
    "tmdb_movies": "discover/tmdb_movies",
    "tmdb_tvs": "discover/tmdb_tvs",
    "douban_movies": "discover/douban_movies",
    "douban_tvs": "discover/douban_tvs",
    "douban_music": "music/explore",
    "bangumi": "discover/bangumi",
    "anilist": "anilist/discover",
    "musicbrainz": "music/explore",
}
RECOMMEND_PATHS = {
    "recommend/tmdb_trending",
    "recommend/douban_showing",
    "recommend/bangumi_calendar",
    "anilist/trending",
    "anilist/popular-this-season",
    "recommend/music_weekly",
    "recommend/music_douban",
    "recommend/tmdb_movies",
    "recommend/tmdb_tvs",
    "recommend/douban_movie_hot",
    "recommend/douban_tv_hot",
    "recommend/douban_tv_animation",
    "recommend/douban_movies",
    "recommend/douban_tvs",
    "recommend/douban_movie_top250",
    "recommend/douban_tv_weekly_chinese",
    "recommend/douban_tv_weekly_global",
}


def _media_source(value) -> str:
    raw = str(value or "").strip().lower()
    return _SOURCE_ALIASES.get(raw, raw)


def _cn_media_type(value) -> str:
    raw = str(value or "").strip()
    if raw in ("电影", "电视剧", "音乐"):
        return raw
    low = raw.lower()
    if low in ("movie", "film"):
        return "电影"
    if low in ("tv", "show", "series", "episode"):
        return "电视剧"
    if low == "music":
        return "音乐"
    return ""


def operation_context(row: dict) -> dict:
    """只保留下载/订阅需要的上下文切片，避免把整条搜索响应长期留在内存。"""
    if not isinstance(row, dict):
        return {}
    torrent = row.get("torrent_info") if isinstance(row.get("torrent_info"), dict) else row
    return {
        "meta_info": row.get("meta_info") if isinstance(row.get("meta_info"), dict) else {},
        "media_info": row.get("media_info") if isinstance(row.get("media_info"), dict) else {},
        "torrent_info": torrent if isinstance(torrent, dict) else {},
    }


def _context_media_info(context: dict) -> dict:
    """由搜索上下文拼出 MP download 接口需要的 MediaInfo。"""
    meta = context.get("meta_info") if isinstance(context.get("meta_info"), dict) else {}
    torrent = context.get("torrent_info") if isinstance(context.get("torrent_info"), dict) else {}
    raw_media = context.get("media_info") if isinstance(context.get("media_info"), dict) else {}
    media_type = (
        _cn_media_type(raw_media.get("type"))
        or _cn_media_type(meta.get("type"))
        or _cn_media_type(torrent.get("category"))
    )
    title = str(
        raw_media.get("title")
        or meta.get("cn_name")
        or meta.get("name")
        or meta.get("title")
        or torrent.get("title")
        or ""
    ).strip()
    if not title:
        raise SeedError("MoviePilot 搜索结果缺少媒体标题，无法建立下载任务")

    media = dict(raw_media)
    media["title"] = title
    if media_type:
        media["type"] = media_type
    year = raw_media.get("year") or meta.get("year") or torrent.get("year")
    if year not in (None, ""):
        media["year"] = str(year)

    source = _media_source(
        raw_media.get("media_source")
        or meta.get("media_source")
        or torrent.get("media_source")
        or ""
    )
    media_id = raw_media.get("media_id") or meta.get("media_id") or torrent.get("media_id")
    if source in _MEDIA_SOURCES and media_id not in (None, ""):
        media["media_source"] = source
        media["media_id"] = str(media_id)
        if source == "themoviedb" and str(media_id).isdigit():
            media["tmdb_id"] = int(media_id)

    if not media.get("poster_path"):
        media["poster_path"] = raw_media.get("poster") or raw_media.get("poster_path")
    if not media.get("backdrop_path"):
        media["backdrop_path"] = raw_media.get("backdrop") or raw_media.get("backdrop_path")
    if not media.get("vote_average"):
        vote = meta.get("vote_average") or meta.get("vote")
        if vote not in (None, ""):
            try:
                media["vote_average"] = float(vote)
            except (TypeError, ValueError):
                pass
    if not media.get("overview"):
        overview = meta.get("overview") or torrent.get("description")
        if overview:
            media["overview"] = str(overview)[:2000]
    return media


def _context_subscription(context: dict) -> dict:
    """由搜索上下文拼出 MP 新增订阅的扁平请求体。"""
    meta = context.get("meta_info") if isinstance(context.get("meta_info"), dict) else {}
    torrent = context.get("torrent_info") if isinstance(context.get("torrent_info"), dict) else {}
    raw_media = context.get("media_info") if isinstance(context.get("media_info"), dict) else {}
    title = str(
        raw_media.get("title")
        or meta.get("cn_name")
        or meta.get("name")
        or meta.get("title")
        or torrent.get("title")
        or ""
    ).strip()
    if not title:
        raise SeedError("MoviePilot 搜索结果缺少媒体名称，无法添加订阅")

    mtype = (
        _cn_media_type(raw_media.get("type"))
        or _cn_media_type(meta.get("type"))
        or _cn_media_type(torrent.get("category"))
    )
    if mtype not in ("电影", "电视剧"):
        raise SeedError("该资源不是影视资源，暂不支持添加订阅")
    payload: dict = {"name": title, "type": mtype}
    year = raw_media.get("year") or meta.get("year") or torrent.get("year")
    if year not in (None, ""):
        payload["year"] = str(year)

    source = _media_source(
        raw_media.get("media_source")
        or meta.get("media_source")
        or torrent.get("media_source")
        or ""
    )
    media_id = raw_media.get("media_id") or meta.get("media_id") or torrent.get("media_id")
    # MP 要求 media_source/media_id 为空对或完整对；缺一个就都不传，让它按标题识别。
    if source in _MEDIA_SOURCES and media_id not in (None, ""):
        payload["media_source"] = source
        payload["media_id"] = str(media_id)

    season = raw_media.get("season") or meta.get("begin_season")
    if season not in (None, ""):
        try:
            payload["season"] = int(season)
        except (TypeError, ValueError):
            pass
    if payload.get("type") == "电视剧":
        total = raw_media.get("number_of_episodes") or meta.get("total_episode")
        if total not in (None, "", 0, "0"):
            try:
                payload["total_episode"] = int(total)
            except (TypeError, ValueError):
                pass
    return payload


class MpClient:
    def __init__(
        self,
        base_url: str,
        *,
        api_token: str = "",
        username: str = "",
        password: str = "",
        auth_mode: str = "api_token",
        verify_tls: bool = True,
    ) -> None:
        self.base_url = normalize_base_url(base_url)
        self.api_token = (api_token or "").strip()
        self.username = (username or "").strip()
        self.password = password or ""
        self.auth_mode = auth_mode if auth_mode in ("api_token", "password") else "api_token"
        self.verify_tls = verify_tls
        self._jwt = ""
        handlers = []
        if self.base_url.lower().startswith("https://"):
            ctx = ssl.create_default_context()
            if not verify_tls:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            handlers.append(HTTPSHandler(context=ctx))
        self._opener = build_opener(*handlers)
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

    # ---- 底层请求 ----
    def _headers(self, json_body: bool = False) -> dict:
        headers = {"Accept": "application/json", "User-Agent": "iHub-Seed/1.0"}
        if json_body:
            headers["Content-Type"] = "application/json"
        if self.auth_mode == "api_token":
            if not self.api_token:
                raise SeedAuthError("MoviePilot 未配置 API_TOKEN")
            headers["X-API-KEY"] = self.api_token
        else:
            if not self._jwt:
                self.login_password()
            headers["Authorization"] = f"Bearer {self._jwt}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        form: dict | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> tuple[int, bytes, dict]:
        url = self.base_url + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None and v != ""}
            if clean:
                url += ("&" if "?" in url else "?") + urlencode(clean, doseq=True)
        data = None
        headers = None
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            headers = self._headers(json_body=True)
        elif form is not None:
            data = urlencode(form).encode("utf-8")
            headers = self._headers()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            headers = self._headers()
        req = Request(url, data=data, method=method, headers=headers)
        self._breaker_check()
        # 连接在建立前被拒（MP 高压突发下偶发 RST/DNS 抖动）时，请求从未被 MP 处理，
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
                if e.code in (401, 403):
                    raise SeedAuthError(
                        "MoviePilot 认证失败：请检查 API_TOKEN（或用户名/密码）是否有管理员权限"
                    )
                if e.code == 404:
                    raise SeedError("MoviePilot 未提供该接口", 404)
                raise SeedError(f"MoviePilot 返回 {e.code}：{detail or e.reason}", 502)
            except (URLError, TimeoutError, OSError) as e:
                reason = str(getattr(e, "reason", None) or e)
                if attempt == 0 and is_connect_refused(e):
                    time.sleep(0.5)
                    continue
                msg = f"无法连接 MoviePilot：{reason}"
                self._breaker_record(msg)
                raise SeedError(msg, 503)

    def _json(self, method: str, path: str, **kwargs):
        _, body, _ = self._request(method, path, **kwargs)
        value = parse_json(body)
        return value

    def _api(self, method: str, path: str, **kwargs):
        try:
            return self._json(method, path, **kwargs)
        except SeedAuthError:
            if self.auth_mode != "password":
                raise
            self._jwt = ""
            return self._json(method, path, **kwargs)

    # ---- 认证 ----
    def login_password(self) -> None:
        if not self.username or not self.password:
            raise SeedAuthError("MoviePilot 未配置用户名/密码")
        data = urlencode({"username": self.username, "password": self.password}).encode("utf-8")
        req = Request(
            self.base_url + "/api/v1/login/access-token",
            data=data,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "iHub-Seed/1.0",
            },
        )
        try:
            with self._opener.open(req, timeout=15) as resp:
                body = resp.read(MAX_RESPONSE)
        except HTTPError as e:
            raise SeedAuthError("MoviePilot 登录失败，请检查用户名/密码") from None
        except (URLError, TimeoutError, OSError) as e:
            reason = str(getattr(e, "reason", None) or e)
            msg = f"无法连接 MoviePilot：{reason}"
            self._breaker_record(msg)
            raise SeedError(msg, 503)
        self._breaker_clear()
        value = parse_json(body) or {}
        value = unwrap_mp(value) or {}
        token = value.get("access_token") if isinstance(value, dict) else None
        if not token:
            raise SeedAuthError("MoviePilot 登录失败，请检查用户名/密码")
        self._jwt = str(token)

    def test(self) -> dict:
        # 手动测试必须真实发起连接：临时挂起熔断（成功后 _request/_breaker_clear 会自然复位）
        self._breaker_suspended = True
        try:
            return self._test_impl()
        finally:
            self._breaker_suspended = False

    def _test_impl(self) -> dict:
        tools: list = []
        # MCP 端点只接受固定 API_KEY（X-API-KEY），不接受用户名/密码换来的 JWT。
        # 用户名/密码模式下直接跳过 MCP，否则会被 401 误判成整条连接认证失败。
        if self.auth_mode == "api_token":
            try:
                tools = self.mcp_tools() or []
            except SeedError:
                # MCP 是可选能力：实例没开/版本不支持时不影响业务 REST 测试
                tools = []
        # 用页面实际依赖的业务接口校验凭据；这里的 401 才是真正的认证失败
        try:
            self.subscriptions(page=1, count=1)
        except SeedAuthError:
            raise
        except SeedError:
            # 业务接口异常（非认证）不应阻断连接测试，交给实际页面提示
            pass
        version = ""
        try:
            status = self._api("GET", "/api/v1/system/status")
            data = unwrap_mp(status) or {}
            if isinstance(data, dict):
                version = str(data.get("version") or data.get("app_version") or "")
        except SeedError:
            pass
        plugins = []
        try:
            installed = self.plugins() or []
            plugins = [
                str(p.get("id") or p.get("plugin_id") or "")
                for p in installed
                if isinstance(p, dict)
            ]
        except SeedError:
            pass
        return {
            "ok": True,
            "version": version,
            "mcp": bool(tools),
            "tool_count": len(tools) if isinstance(tools, list) else 0,
            "plugins": [p for p in plugins if p][:50],
        }

    # ---- MCP ----
    def mcp_tools(self) -> list:
        value = self._api("GET", "/api/v1/mcp/tools", timeout=30)
        data = unwrap_mp(value)
        return data if isinstance(data, list) else []

    def mcp_call(self, tool_name: str, arguments: dict | None = None):
        value = self._api(
            "POST",
            "/api/v1/mcp/tools/call",
            json_body={"tool_name": tool_name, "arguments": arguments or {}},
            timeout=60,
        )
        data = unwrap_mp(value)
        # MCP REST 返回 data.result（可能是 JSON 文本）
        if isinstance(data, dict) and "result" in data:
            result = data.get("result")
            if isinstance(result, str):
                try:
                    return json.loads(result)
                except ValueError:
                    return result
            return result
        return data

    def mcp_operation(
        self,
        operation_id: str,
        *,
        path_params: dict | None = None,
        query: dict | None = None,
        body: dict | None = None,
    ):
        args: dict = {"operation_id": operation_id}
        if path_params:
            args["path_params"] = path_params
        if query:
            args["query"] = query
        if body is not None:
            args["body"] = body
        return self.mcp_call("moviepilot_api", args)

    # ---- 存储 ----
    def storage(self) -> dict:
        """MP 配置的本地存储真实容量（psutil 读文件系统，按磁盘去重）。"""
        value = self._api("GET", "/api/v1/dashboard/storage")
        data = unwrap_mp(value) or {}
        if not isinstance(data, dict):
            return {}
        try:
            total = int(data.get("total_storage") or 0)
            used = int(data.get("used_storage") or 0)
        except (TypeError, ValueError):
            return {}
        if total <= 0:
            return {}
        used = max(0, min(used, total))
        return {"total": total, "used": used, "free": total - used}

    # ---- 通知 ----
    def notifications(self, page: int = 1, count: int = 50) -> list:
        value = self._api(
            "GET", "/api/v1/message/notification", params={"page": page, "count": count}
        )
        data = unwrap_mp(value)
        if isinstance(data, dict):
            # 真实 MP 的下载历史同样是 data.list（可能没有 total）。
            data = data.get("items") or data.get("list") or data.get("data") or []
        return data if isinstance(data, list) else []

    # ---- 订阅/站点 ----
    def subscriptions(self, page: int = 1, count: int = 50) -> list:
        value = self._api("GET", "/api/v1/subscribe/", params={"page": page, "count": count})
        data = unwrap_mp(value)
        if isinstance(data, dict):
            data = data.get("items") or data.get("list") or data.get("data") or []
        return data if isinstance(data, list) else []

    def transfer_history(self, page: int = 1, count: int = 200) -> list:
        """整理历史（含 download_hash、状态、海报），用于转媒体完成确认/封面兜底。"""
        value = self._api(
            "GET",
            "/api/v1/history/transfer",
            params={"page": page, "count": count},
            timeout=5,
        )
        data = unwrap_mp(value)
        if isinstance(data, dict):
            # MP v3 整理历史分页结构是 {"list": [...], "total": N}；
            # 兼容旧版/插件可能返回的 items/data。
            data = data.get("items") or data.get("list") or data.get("data") or []
        return data if isinstance(data, list) else []

    def download_history(self, page: int = 1, count: int = 200) -> list:
        """下载历史（含 hash 与媒体海报），用于给 qB 任务补封面。"""
        value = self._api(
            "GET",
            "/api/v1/history/download",
            params={"page": page, "count": count},
            timeout=5,
        )
        data = unwrap_mp(value)
        if isinstance(data, dict):
            # 真实 MP 的下载历史同样是 data.list（可能没有 total）。
            data = data.get("items") or data.get("list") or data.get("data") or []
        return data if isinstance(data, list) else []

    def sites(self) -> list:
        for path in ("/api/v1/site/agent", "/api/v1/site/"):
            try:
                value = self._api("GET", path)
                data = unwrap_mp(value)
                if isinstance(data, dict):
                    data = data.get("items") or data.get("data") or []
                return data if isinstance(data, list) else []
            except SeedError as e:
                if e.status_code == 404:
                    continue
                raise
        return []

    def site_statistics(self) -> list:
        value = self._api("GET", "/api/v1/site/statistic")
        data = unwrap_mp(value)
        if isinstance(data, dict):
            data = data.get("items") or data.get("data") or []
        return data if isinstance(data, list) else []

    def site_icon(self, site_id) -> str:
        """站点图标：MP 返回 {icon: "data:image/...;base64,..."}，直接内联给前端。

        站点从未被访问过时 MP 可能 404，按无图标处理。"""
        try:
            value = self._api(
                "GET", f"/api/v1/site/icon/{quote(str(site_id), safe='')}", timeout=15
            )
        except SeedError:
            return ""
        data = unwrap_mp(value)
        if isinstance(data, dict):
            return str(data.get("icon") or "")
        return ""

    # ---- 搜索/发现/推荐 ----
    def search_title(
        self, keyword: str, *, mtype: str | None = None, sites: str | None = None, page: int = 1
    ) -> list:
        value = self._api(
            "GET",
            "/api/v1/search/title",
            params={"keyword": keyword, "mtype": mtype, "sites": sites, "page": page},
            timeout=SEARCH_TIMEOUT,
        )
        data = unwrap_mp(value)
        return data if isinstance(data, list) else []

    def episodes(self, tmdbid: str | int, season: int) -> list:
        """TMDB 剧集某季的集数列表（MP v3：GET /api/v1/tmdb/{tmdbid}/{season}）。"""
        value = self._api(
            "GET",
            f"/api/v1/tmdb/{quote(str(tmdbid), safe='')}/{int(season)}",
            timeout=30,
        )
        data = unwrap_mp(value)
        return data if isinstance(data, list) else []

    def subscribe_create(self, payload: dict) -> dict:
        """新增订阅（POST /api/v1/subscribe/，body 为 Subscribe schema；注意尾斜杠，否则 307）。"""
        value = self._api("POST", "/api/v1/subscribe/", json_body=payload, timeout=30)
        return unwrap_mp(value) if isinstance(value, dict) else {}

    def subscribe_delete_media(self, tmdbid: str | int, season: int | None = None) -> None:
        """按媒体身份删除订阅（DELETE /api/v1/subscribe/media/{media_id}，可带 season）。"""
        params = {"media_source": "themoviedb"}
        if season is not None:
            params["season"] = season
        self._api(
            "DELETE",
            f"/api/v1/subscribe/media/{quote(str(tmdbid), safe='')}",
            params=params,
            timeout=15,
        )

    def media_detail(self, media_id: str, media_source: str, type_name: str) -> dict:
        """媒体详情（海报/宽幅背景/简介）；用历史记录里的 media_id + 来源查询。

        电视剧首查时 MP 会现拉 TMDB 的季/演职员信息，耗时可达十几秒，
        超时不能沿用常规 15s（实测用户环境电视剧首查直接超时）。"""
        mid = str(media_id or "").strip()
        source = str(media_source or "").strip()
        kind = str(type_name or "").strip()
        if not mid or not source or not kind:
            raise SeedError("MoviePilot 媒体信息不完整")
        value = self._api(
            "GET",
            f"/api/v1/media/{quote(mid, safe='')}",
            params={"media_source": source, "type_name": kind},
            timeout=45,
        )
        data = unwrap_mp(value)
        return data if isinstance(data, dict) else {}

    def media_search(
        self,
        title: str,
        *,
        mtype: str | None = None,
        sources: list[str] | None = None,
        page: int = 1,
        count: int = 20,
    ) -> list:
        # MP 的 media/search 只接受 media/music/collection/person，电影/剧集统一用 media
        api_type = "music" if mtype == "music" else "media"
        params: dict = {"title": title, "type": api_type, "page": page, "count": count}
        if sources:
            params["media_source"] = sources
        value = self._api("GET", "/api/v1/media/search", params=params, timeout=SEARCH_TIMEOUT)
        data = unwrap_mp(value)
        return data if isinstance(data, list) else []

    def search_torrents(
        self,
        media_id: str,
        media_source: str,
        *,
        mtype: str | None = None,
        season: int | None = None,
        sites: str | None = None,
        page: int = 1,
        count: int = 50,
    ) -> list:
        quoted = quote(str(media_id), safe="")
        params = {
            "media_source": media_source,
            "mtype": mtype,
            "season": season,
            "page": page,
            "count": count,
        }
        if sites:
            params["sites"] = sites
        value = self._api(
            "GET",
            f"/api/v1/search/media/{quoted}",
            params=params,
            timeout=SEARCH_TIMEOUT,
        )
        data = unwrap_mp(value)
        if isinstance(data, dict):
            data = data.get("items") or data.get("data") or []
        return data if isinstance(data, list) else []

    def download_clients(self) -> list:
        """可用的下载器列表（MP /api/v1/download/clients）。"""
        value = self._api("GET", "/api/v1/download/clients", timeout=DEFAULT_TIMEOUT)
        data = unwrap_mp(value)
        return data if isinstance(data, list) else []

    def download_paths(self) -> list:
        """下载保存目录配置（MP /api/v1/download/paths，含 name/save_path/media_type）。"""
        value = self._api("GET", "/api/v1/download/paths", timeout=DEFAULT_TIMEOUT)
        data = unwrap_mp(value)
        return data if isinstance(data, list) else []

    def download_context(
        self,
        context: dict,
        *,
        downloader: str = "",
        save_path: str = "",
        media_source: str = "",
        media_id: str = "",
        media_type: str = "",
    ) -> dict:
        """按搜索结果上下文手动添加下载（服务端保留 enclosure/Cookie）。

        downloader / save_path 留空 = MP 默认下载器 / 自动匹配目录；
        media_source + media_id 同时给出时覆盖媒体身份（MP 弹窗的高级选项）。
        """
        torrent = context.get("torrent_info") if isinstance(context.get("torrent_info"), dict) else {}
        if not torrent.get("enclosure"):
            raise SeedError("该 PT 资源没有下载链接，可能已过期")
        media_in = _context_media_info(context)
        if media_type:
            media_in["type"] = media_type
        payload = {
            "media_in": media_in,
            "torrent_in": torrent,
            "downloader": downloader,
            "save_path": save_path,
        }
        if media_source and media_id:
            payload["media_source"] = media_source
            payload["media_id"] = str(media_id)
        value = self._api("POST", "/api/v1/download/", json_body=payload, timeout=SEARCH_TIMEOUT)
        if isinstance(value, dict) and value.get("success") is False:
            raise SeedError(str(value.get("message") or "MoviePilot 添加下载任务失败"))
        data = unwrap_mp(value)
        return data if isinstance(data, dict) else {}

    def subscribe_context(self, context: dict) -> dict:
        """按搜索结果上下文新增订阅。"""
        payload = _context_subscription(context)
        value = self._api("POST", "/api/v1/subscribe/", json_body=payload, timeout=SEARCH_TIMEOUT)
        if isinstance(value, dict) and value.get("success") is False:
            raise SeedError(str(value.get("message") or "MoviePilot 添加订阅失败"))
        data = unwrap_mp(value)
        return data if isinstance(data, dict) else {}

    def recommend(
        self,
        *,
        source: str = "tmdb_trending",
        media_type: str = "all",
        page: int = 1,
        count: int = 20,
    ) -> list:
        value = self._api(
            "GET",
            "/api/v1/recommend/agent",
            params={"source": source, "media_type": media_type, "page": page, "count": count},
            timeout=SEARCH_TIMEOUT,
        )
        data = unwrap_mp(value)
        if isinstance(data, dict):
            data = data.get("items") or data.get("data") or []
        return data if isinstance(data, list) else []

    def discover(self, source: str, *, page: int = 1, count: int = 30, **extra) -> list:
        allowed = {
            "tmdb_movies",
            "tmdb_tvs",
            "douban_movies",
            "douban_tvs",
            "bangumi",
        }
        if source not in allowed:
            raise SeedError("不支持的探索来源", 400)
        value = self._api(
            "GET",
            f"/api/v1/discover/{source}",
            params={"page": page, "count": count, **extra},
            timeout=SEARCH_TIMEOUT,
        )
        data = unwrap_mp(value)
        return data if isinstance(data, list) else []

    def discover_explore(self, source: str, *, page: int = 1, count: int = 20, params: dict | None = None) -> list:
        """探索页来源；路径和参数与 MP 前端一致。"""
        path = DISCOVER_PATHS.get(source)
        if not path:
            raise SeedError("不支持的探索来源", 400)
        clean = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        clean["page"] = page
        clean["count"] = count
        # MP 的封面/时间范围参数是布尔值；前端传的是 all / with_cover 这类选项
        if "with_cover" in clean:
            clean["with_cover"] = str(clean["with_cover"]).lower() in {"1", "true", "with_cover", "yes"}
        for key in ("past", "future"):
            if key in clean:
                clean[key] = str(clean[key]).lower() in {"1", "true", "yes"}
        if source == "douban_music":
            clean["media_source"] = "doubanmusic"
        elif source == "musicbrainz":
            clean["media_source"] = "musicbrainz"
        value = self._api(
            "GET",
            f"/api/v1/{path}",
            params=clean,
            timeout=SEARCH_TIMEOUT,
        )
        data = unwrap_mp(value)
        if isinstance(data, dict):
            data = data.get("items") or data.get("data") or data.get("list") or []
        return data if isinstance(data, list) else []

    def recommend_section(self, source: str, *, page: int = 1, count: int = 20) -> list:
        """推荐页的单个板块（source 为 MP 前端的 apipath，如 recommend/tmdb_trending）。"""
        if source not in RECOMMEND_PATHS:
            raise SeedError("不支持的推荐板块", 400)
        value = self._api(
            "GET",
            f"/api/v1/{source}",
            params={"page": page, "count": count},
            timeout=RECOMMEND_TIMEOUT,
        )
        data = unwrap_mp(value)
        if isinstance(data, dict):
            data = data.get("items") or data.get("data") or data.get("list") or []
        return data if isinstance(data, list) else []

    # ---- 插件/刷流 ----
    def plugins(self) -> list:
        value = self._api("GET", "/api/v1/plugin/", params={"state": "installed"})
        data = unwrap_mp(value)
        if isinstance(data, dict):
            data = data.get("items") or data.get("data") or []
        return data if isinstance(data, list) else []

    def brush_status(self) -> dict:
        value = self._api("GET", "/api/v1/plugin/BrushFlow/status")
        data = unwrap_mp(value)
        return data if isinstance(data, dict) else {}

    def brush_task(self, task_id: str) -> dict:
        value = self._api(
            "GET",
            f"/api/v1/plugin/BrushFlow/tasks/{quote(str(task_id), safe='')}",
            params={"state": "active", "page": 1, "page_size": 50},
        )
        data = unwrap_mp(value)
        return data if isinstance(data, dict) else {}
