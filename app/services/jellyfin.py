"""Jellyfin（Emby 大体兼容）共享客户端（影视中心使用，见模块底部的 `VIDEO_JF`）。

- 令牌缓存与 DeviceId 由实例参数注入（上游按设备区分会话与播放进度），
  配置键/设备号/错误文案在构造时指定；
- 协议细节（认证 / 401 重认证一次 / Items 查询 / 非 Items GET / 流式打开 / 进度上报）
  由本类统一实现。
"""

import json as jsonlib
from urllib.error import HTTPError as UrlHTTPError
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.services.settings_store import get_cfg, get_credential
from app.services.upstream_http import http as _http
from app.services.upstream_http import http_passthrough_401
from app.services.upstream_http import open_stream_raw


def _json_or_502(body: bytes) -> dict:
    try:
        return jsonlib.loads(body.decode("utf-8", "replace"))
    except ValueError:
        raise HTTPException(502, "Jellyfin 返回的不是有效 JSON") from None


def _unauthorized(body: bytes) -> HTTPException:
    """重认证后仍是 401：与 upstream_http 的错误文案保持一致（上游返回 401：<body>）。"""
    return HTTPException(502, f"上游返回 401：{body[:200].decode('utf-8', 'replace')}")


class JellyfinClient:
    def __init__(
        self,
        *,
        url_key: str,
        user_key: str,
        pass_key: str,
        device_id: str,
        config_error: str,
    ) -> None:
        self._url_key = url_key
        self._user_key = user_key
        self._pass_key = pass_key
        self._device_id = device_id
        self._config_error = config_error
        # 进程内缓存 url -> (accessToken, user_id)（重启后重新认证）
        self._tokens: dict[str, tuple[str, str]] = {}

    # ---------- 凭据 / 令牌 ----------

    def creds(self, db: Session) -> tuple[str, str, str]:
        url = get_cfg(db, self._url_key).rstrip("/")
        user = get_cfg(db, self._user_key)
        pwd = get_credential(db, self._pass_key)
        if not (url and user):
            raise HTTPException(400, self._config_error)
        return url, user, pwd

    def auth(self, url: str, user: str, pwd: str) -> tuple[str, str]:
        """AuthenticateByName -> (access_token, user_id)"""
        body = jsonlib.dumps({"Username": user, "Pw": pwd}).encode()
        headers = {
            "Content-Type": "application/json",
            "X-Emby-Authorization": (
                f'MediaBrowser Client="iHub", Device="iHub Web", '
                f'DeviceId="{self._device_id}", Version="1.0"'
            ),
        }
        _, resp = _http(f"{url}/Users/AuthenticateByName", method="POST", headers=headers, data=body)
        try:
            data = jsonlib.loads(resp.decode("utf-8", "replace"))
        except ValueError:
            raise HTTPException(502, "Jellyfin 返回的不是有效 JSON（请检查服务器地址）") from None
        token = data.get("AccessToken") or ""
        uid = (data.get("User") or {}).get("Id") or ""
        if not token:
            raise HTTPException(502, "Jellyfin 认证失败：未获得令牌")
        return token, uid

    def token(self, db: Session) -> tuple[str, str, str]:
        """返回 (url, accessToken, jellyfin_user_id)；第三元素是 Jellyfin 用户 GUID。"""
        url, user, pwd = self.creds(db)
        cached = self._tokens.get(url)
        if cached:
            return url, cached[0], cached[1]
        token, uid = self.auth(url, user, pwd)
        self._tokens[url] = (token, uid)
        return url, token, uid

    def cache_token(self, url: str, token: str, uid: str) -> None:
        """测试连接成功后预置令牌缓存（免去随后播放的再一次认证）。"""
        self._tokens[url] = (token, uid)

    def clear_tokens(self) -> None:
        """凭据变更后旧 accessToken（改密即被上游吊销）必须重认证。"""
        self._tokens.clear()

    # ---------- 请求 ----------

    @staticmethod
    def query(params: dict) -> str:
        return "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())

    def _reauth(self, db: Session, url: str) -> tuple[str, str, str]:
        """令牌被上游吊销（如改密）：清缓存后重认证一次。"""
        self._tokens.pop(url, None)
        return self.token(db)

    def items(self, db: Session, extra: dict) -> dict:
        """GET /Items（递归查询）；令牌被吊销（401）时清缓存重认证一次后重试。"""
        url, token, uid = self.token(db)
        params = {"userId": uid, "Recursive": "true", **extra}
        status, resp = http_passthrough_401(f"{url}/Items?{self.query(params)}", headers={"X-Emby-Token": token})
        if status == 401:
            url, token, uid = self._reauth(db, url)
            params["userId"] = uid
            status, resp = http_passthrough_401(f"{url}/Items?{self.query(params)}", headers={"X-Emby-Token": token})
        if status == 401:
            raise _unauthorized(resp)
        return _json_or_502(resp)

    def get(self, db: Session, path: str, raw: bool = False):
        """歌词/封面等非 /Items 端点的统一 GET：令牌被吊销（401）同样重认证一次。
        path 以 / 开头（如 /Audio/{id}/Lyrics）。raw=True 返回原始字节（图片）。
        """
        url, token, _ = self.token(db)
        status, body = http_passthrough_401(f"{url}{path}", headers={"X-Emby-Token": token})
        if status == 401:
            url, token, _ = self._reauth(db, url)
            status, body = http_passthrough_401(f"{url}{path}", headers={"X-Emby-Token": token})
        if status == 401:
            raise _unauthorized(body)
        if raw:
            return status, body
        return status, _json_or_502(body)

    def open_stream(self, db: Session, path: str, range_header: str | None):
        """流式打开（static=true 原文件直出）；令牌被吊销（401）清缓存重认证一次后重开。"""
        url, token, _ = self.token(db)
        headers = {"X-Emby-Token": token}
        if range_header:
            headers["Range"] = range_header
        try:
            return open_stream_raw(f"{url}{path}", headers)
        except UrlHTTPError as e:
            if e.code != 401:
                raise HTTPException(502, f"上游返回 {e.code}") from None
            self._tokens.pop(url, None)
            url, token, _ = self.token(db)
            headers = {"X-Emby-Token": token}
            if range_header:
                headers["Range"] = range_header
            try:
                return open_stream_raw(f"{url}{path}", headers)
            except UrlHTTPError as e2:
                raise HTTPException(502, f"上游返回 {e2.code}") from None

    def post_progress(self, db: Session, item_id: str, position: float, stopped: bool = False) -> None:
        """进度双写上游（尽力而为，与音乐 Subsonic 双写同策略）：上报失败不影响本地记录。"""
        try:
            url, token, _ = self.token(db)
            endpoint = "/Sessions/Playing/Stopped" if stopped else "/Sessions/Playing/Progress"
            body = jsonlib.dumps({
                "ItemId": item_id,
                "PositionTicks": int(max(0, position) * 10_000_000),
            }).encode()
            _http(
                f"{url}{endpoint}", method="POST",
                headers={"X-Emby-Token": token, "Content-Type": "application/json"}, data=body,
            )
        except Exception:
            pass


# 音乐中心（DeviceId=ihub-player）与影视中心（DeviceId=ihub-video）各持一个实例
VIDEO_JF = JellyfinClient(
    url_key="video_jf_url",
    user_key="video_jf_user",
    pass_key="video_jf_pass",
    device_id="ihub-video",
    config_error="Jellyfin 影视源尚未配置完整",
)
