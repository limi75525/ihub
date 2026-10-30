# -*- coding: utf-8 -*-
"""音乐/影视/统计重构回归：假 Jellyfin 服务 + 假 NAS 目录，纯标准库。

用法（需全新数据目录的实例，脚本会注册首个管理员）：
  cd iHub && .venv/Scripts/python -m uvicorn app.main:app --port 18766 --no-proxy-headers
  .venv/Scripts/python scripts/media_regression_test.py http://127.0.0.1:18766

覆盖冒烟 / 专项脚本未覆盖的重构面：
  1. Jellyfin 客户端（app/services/jellyfin.py，影视）：认证 / 401 清缓存重认证一次 /
     Items 查询 / 封面 / 剧集 NextUp 续播目标 / 流式 Range 透传 / 观影进度双写上游；
  2. 共享 NAS 扫描引擎（app/services/media_scan.py）：首次全量 → 增量跳过 →
     mtime/size 变化更新 → 文件删除，音乐与影视共用引擎且状态键独立；
  3. 总览趋势 SQL 分桶（stats.py）：跨日消息落在本地日界对应的那一天，
     窗口外（8 天前）的消息不计入任何桶；
  4. 影视 NFO 元数据（app/services/nfo.py + video.py）：文件名启发式之上叠加同名/剧集 NFO
     （标题与年份覆盖、新版评分结构、导演去重、演员表）；NFO 重写（视频未动）触发单条重解析；
     海报/剧照探测（NFO 引用优先、通用名、分集回探剧集目录、引用越界拦截）；
  5. 在线补全（app/services/tmdb.py + 假 TMDB 服务）：未配 Key 静默跳过、配 Key 后按 TMDB 编号
     下载海报/剧照并缓存（含缓存文件断言）、本地已有图不发起在线请求、非法编号不拼入请求、
     条目删除后缓存清理。
"""

import hashlib
import hmac
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit
from zoneinfo import ZoneInfo

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18766").rstrip("/")
# 后端的数据目录（缓存文件断言用；与启动后端时的 IHUB_DATA_DIR 保持一致）
DATA_DIR = Path(os.environ.get("IHUB_DATA_DIR", ".smoke-data"))

USER, PWD = "mediaref", "media-ref-123"

TOKEN = {"v": None}
MEDIA_KEY = {"v": ""}
DEV = {}
PASSED = 0
FAILED = 0


def check(ok: bool, label: str, detail: str = "") -> None:
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"  [ok]   {label}")
    else:
        FAILED += 1
        print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))


def call(method, path, body=None, token=None, raw=None, ctype=None, headers=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", ctype or "application/json")
    t = token or TOKEN["v"]
    if t:
        req.add_header("Authorization", f"Bearer {t}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    last_err: Exception | None = None
    for attempt in range(2):  # 本机快速轮询下偶发 WinError 10061（连接被瞬时拒绝），重试一次
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = resp.read()
                return resp.status, (json.loads(payload) if payload else {}), dict(resp.headers)
        except urllib.error.HTTPError as e:
            payload = e.read()
            try:
                return e.code, json.loads(payload), dict(e.headers)
            except Exception:
                return e.code, {"raw": payload.decode(errors="replace")[:200]}, dict(e.headers)
        except urllib.error.URLError as e:
            last_err = e
            time.sleep(0.5)
    raise last_err  # type: ignore[misc]


def sign(did, secret, ts, nonce, body):
    body_sha = hashlib.sha256(body).hexdigest()
    return hmac.new(secret.encode(), f"{did}\n{ts}\n{nonce}\n{body_sha}".encode(), hashlib.sha256).hexdigest()


def push_msg(payload: dict, ts_seconds: int) -> bool:
    did, secret = DEV["sms"]
    raw = json.dumps(payload).encode()
    nonce = f"mrt-{time.time_ns()}"
    req = urllib.request.Request(BASE + "/api/v1/ingest/device", data=raw, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Device-Id", did)
    req.add_header("X-Timestamp", str(int(time.time())))
    req.add_header("X-Nonce", nonce)
    req.add_header("X-Signature", sign(did, secret, int(time.time()), nonce, raw))
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode()).get("ok") is True


# --------------------------------------------------------------------------- 假 Jellyfin

MOVIES = [{"Id": "mov1", "Type": "Movie", "Name": "Movie One", "ProductionYear": 2019,
           "RunTimeTicks": 7_200_000_000, "ImageTags": {"Primary": "t1"},
           "Overview": "假电影", "UserData": {"PlaybackPositionTicks": 600_000_000}}]
SERIES = [{"Id": "ser1", "Type": "Series", "Name": "Some Show", "ProductionYear": 2020,
           "ChildCount": 2, "ImageTags": {"Primary": "t1"}}]
EPISODES = [
    {"Id": "ep1", "Type": "Episode", "Name": "Ep One", "SeriesName": "Some Show",
     "ParentIndexNumber": 1, "IndexNumber": 1, "RunTimeTicks": 1_500_000_000, "ImageTags": {}},
    {"Id": "ep2", "Type": "Episode", "Name": "Ep Two", "SeriesName": "Some Show",
     "ParentIndexNumber": 1, "IndexNumber": 2, "RunTimeTicks": 1_500_000_000, "ImageTags": {}},
]
JPEG = b"\xff\xd8\xff\xe0" + b"J" * 96  # 非真图，仅验证字节透传
VIDEO_BYTES = bytes(range(256)) * 32


class JFState:
    def __init__(self):
        self.lock = threading.Lock()
        self.tokens = {}        # token -> username
        self.auth_calls = []    # 认证用户名顺序
        self.seen = []          # (path, token) 逐个请求
        self.progress = []      # (endpoint, item_id)
        self.force_401_items = False


JF = JFState()


class JFHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # 静音
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, data, ctype="application/octet-stream", status=200, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _record(self, path):
        token = self.headers.get("X-Emby-Token") or ""
        with JF.lock:
            JF.seen.append((path, token))

    def _authed(self):
        token = self.headers.get("X-Emby-Token") or ""
        with JF.lock:
            return token if token in JF.tokens else None

    def do_POST(self):
        parts = urlsplit(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        path = parts.path
        self._record(path)
        if path == "/Users/AuthenticateByName":
            data = json.loads(raw.decode() or "{}")
            user = data.get("Username", "")
            token = f"tok-{user}"
            with JF.lock:
                JF.tokens[token] = user
                JF.auth_calls.append(user)
            self._json({"AccessToken": token, "User": {"Id": f"uid-{user}"}})
            return
        if path in ("/Sessions/Playing/Progress", "/Sessions/Playing/Stopped"):
            data = json.loads(raw.decode() or "{}")
            with JF.lock:
                JF.progress.append((path, data.get("ItemId")))
            self._json({})
            return
        self._json({"error": "not found"}, 404)

    def do_GET(self):
        parts = urlsplit(self.path)
        path, qs = parts.path, parse_qs(parts.query)
        self._record(path)

        if path == "/Shows/NextUp":
            if not self._authed():
                self._json({"error": "unauthorized"}, 401)
                return
            # 模拟「上次看到第 1 集、下一集是第 2 集」（剧集详情「上次看到哪集」用）
            self._json({"Items": [EPISODES[1]], "TotalRecordCount": 1})
            return

        if path == "/Items":
            if not self._authed():
                self._json({"error": "unauthorized"}, 401)
                return
            with JF.lock:
                if JF.force_401_items:
                    JF.force_401_items = False
                    self._json({"error": "token revoked"}, 401)
                    return
            types = (qs.get("IncludeItemTypes") or [""])[0]
            filters = (qs.get("Filters") or [""])[0]
            if filters == "IsResumable":
                self._json({"Items": MOVIES, "TotalRecordCount": 1})
                return
            if types == "Movie":
                self._json({"Items": MOVIES, "TotalRecordCount": len(MOVIES)})
                return
            if types == "Series":
                self._json({"Items": SERIES, "TotalRecordCount": len(SERIES)})
                return
            if types == "Movie,Series":
                self._json({"Items": MOVIES + SERIES, "TotalRecordCount": len(MOVIES) + len(SERIES)})
                return
            if types == "Movie,Episode":
                self._json({"Items": MOVIES + EPISODES, "TotalRecordCount": 3})
                return
            self._json({"Items": [], "TotalRecordCount": 0})
            return

        if "/Images/Primary" in path:
            if not self._authed():
                self._json({"error": "unauthorized"}, 401)
                return
            self._bytes(JPEG, "image/jpeg")
            return

        if path.startswith("/Shows/") and path.endswith("/Episodes"):
            if not self._authed():
                self._json({"error": "unauthorized"}, 401)
                return
            self._json({"Items": EPISODES})
            return

        # 媒体流：/Videos/{id}（static=true），支持 Range
        if path.startswith("/Videos/"):
            if not self._authed():
                self._json({"error": "unauthorized"}, 401)
                return
            data = VIDEO_BYTES
            rng = self.headers.get("Range")
            if rng and rng.startswith("bytes="):
                start_s, _, end_s = rng[len("bytes="):].partition("-")
                start = int(start_s or 0)
                end = int(end_s) if end_s else len(data) - 1
                chunk = data[start:end + 1]
                self._bytes(chunk, status=206,
                            headers={"Content-Range": f"bytes {start}-{end}/{len(data)}",
                                     "Accept-Ranges": "bytes"})
                return
            self._bytes(data, headers={"Accept-Ranges": "bytes"})
            return

        self._json({"error": "not found"}, 404)


def start_fake_jellyfin():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), JFHandler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{port}"


# --------------------------------------------------------------------------- 假 TMDB

TMDB_KEY = "regr-tmdb-key"
TMDB_HITS: list[str] = []


class TmdbHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # 静音
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _image(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        TMDB_HITS.append(self.path)
        parts = urlsplit(self.path)
        seg = parts.path.strip("/").split("/")
        if len(seg) == 3 and seg[0] == "3" and seg[1] in ("movie", "tv"):
            if (parse_qs(parts.query).get("api_key") or [""])[0] != TMDB_KEY:
                self._json({"status_message": "Invalid API key"}, 401)
                return
            ident = seg[2]
            if seg[1] == "movie":
                self._json({
                    "poster_path": f"/regr-poster-{ident}.jpg",
                    "backdrop_path": f"/regr-backdrop-{ident}.jpg",
                    "images": {
                        "logos": [
                            {"file_path": f"/regr-en-logo-{ident}.png", "iso_639_1": "en"},
                            {"file_path": f"/regr-logo-{ident}.png", "iso_639_1": "zh"},
                        ],
                        "backdrops": [
                            # 与主图相同：_pick_backdrop_paths 必须去重
                            {"file_path": f"/regr-backdrop-{ident}.jpg", "iso_639_1": None,
                             "vote_average": 9.5, "vote_count": 99},
                            {"file_path": f"/regr-bd2-{ident}.jpg", "iso_639_1": None,
                             "vote_average": 7.1, "vote_count": 40},
                            {"file_path": f"/regr-bd3-{ident}.jpg", "iso_639_1": "zh",
                             "vote_average": 8.2, "vote_count": 90},
                        ],
                    },
                })
            else:
                self._json({
                    "poster_path": f"/regr-tvposter-{ident}.jpg",
                    "backdrop_path": None,
                    "images": {"logos": [{"file_path": f"/regr-tvlogo-{ident}.png", "iso_639_1": "zh"}]},
                })
            return
        if parts.path.startswith("/3/search/"):
            qs = parse_qs(parts.query)
            if (qs.get("api_key") or [""])[0] != TMDB_KEY:
                self._json({"status_message": "Invalid API key"}, 401)
                return
            q = (qs.get("query") or [""])[0]
            if parts.path == "/3/search/movie" and q == "无编号电影":
                self._json({"results": [{"id": 7777, "title": "无编号电影", "original_title": "No ID Movie",
                                         "release_date": "2019-05-01", "popularity": 20.0}]})
                return
            if parts.path == "/3/search/movie" and q == "歧义片":
                self._json({"results": [
                    {"id": 8801, "title": "歧义片", "release_date": "2019-03-01", "popularity": 9.0},
                    {"id": 8802, "title": "歧义片", "release_date": "2019-09-01", "popularity": 8.0},
                ]})
                return
            if parts.path == "/3/search/tv" and q == "季名匹配剧":
                self._json({"results": [{"id": 9999, "name": "季名匹配剧", "original_name": "Matched By Season",
                                         "first_air_date": "2023-04-01", "popularity": 11.0}]})
                return
            if parts.path == "/3/search/tv" and q == "无编号剧":
                self._json({"results": [{"id": 8888, "name": "无编号剧", "original_name": "No ID Show",
                                         "first_air_date": "2023-04-01", "popularity": 30.0}]})
                return
            self._json({"results": []})
            return
        if parts.path.startswith("/t/p/"):
            # 图片内容带上完整路径：断言"最终服务的是哪张下载图"用
            self._image(b"IMG:" + parts.path.encode())
            return
        self._json({"detail": "not found"}, 404)


def start_fake_tmdb():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), TmdbHandler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{port}"


# --------------------------------------------------------------------------- NFO 测试素材

MOVIE_NFO = """<?xml version="1.0" encoding="utf-8"?>
<movie>
  <title>给阿嬷的情书</title>
  <originaltitle>给阿嬷的情书</originaltitle>
  <plot><![CDATA[潮汕阿嬷叶淑柔一直守着平淡的日子。]]></plot>
  <year>2026</year>
  <ratings><rating><value>8.7</value><votes>1</votes></rating></ratings>
  <genre>剧情</genre>
  <genre>家庭</genre>
  <director>蓝鸿春</director>
  <director>蓝鸿春</director>
  <director>郑萱轩</director>
  <actor><name>李思潼</name><role>Xie Nanzhi</role><thumb>https://image.tmdb.org/t/p/original/x.jpg</thumb></actor>
  <runtime>118</runtime>
  <poster>art-custom.jpg</poster>
</movie>
"""

EP_NFO = """<?xml version="1.0" encoding="utf-8"?>
<episodedetails><title>初入京都</title><plot>第一集剧情</plot><rating>8.0</rating><runtime>45</runtime></episodedetails>
"""

SHOW_NFO = """<?xml version="1.0" encoding="utf-8"?>
<tvshow><title>庆余年</title><plot>范闲的传奇故事</plot><rating>9.1</rating><genre>古装</genre><genre>权谋</genre></tvshow>
"""

BAD_NFO = """<?xml version="1.0" encoding="utf-8"?>
<movie><title>Bad Ref</title><poster>../../../outside.jpg</poster></movie>
"""


# --------------------------------------------------------------------------- 主流程

def poll_scan(kind: str, timeout: float = 40.0) -> dict:
    deadline = time.time() + timeout
    state = {}
    while time.time() < deadline:
        st, state, _ = call("GET", f"/api/v1/{kind}/scan/status")
        if st == 200 and not state.get("running"):
            return state
        time.sleep(0.3)
    return state


def wait_video_scan(expected_art: int, timeout: float = 90.0) -> dict:
    """等影视「扫描 + 在线补全」全部结束：art_total/art_done 达到期望值且运行态结束。

    只看 running 会在扫描结束与补全阶段起步之间的瞬时窗口提前返回（art_total 还是上一轮的值）。
    """
    deadline = time.time() + timeout
    state: dict = {}
    while time.time() < deadline:
        st, state, _ = call("GET", "/api/v1/video/scan/status")
        if (
            st == 200
            and not state.get("running")
            and state.get("art_total") == expected_art
            and state.get("art_done") == expected_art
        ):
            return state
        time.sleep(0.4)
    return state


def main() -> int:
    srv, jf_url = start_fake_jellyfin()
    tmdb_srv, tmdb_base = start_fake_tmdb()
    tmp = Path(tempfile.mkdtemp(prefix="ihub-media-"))
    music_dir = tmp / "music"
    video_dir = tmp / "video"
    music_dir.mkdir(parents=True)
    video_dir.mkdir(parents=True)
    try:
        print("== 0. 初始化（首个注册用户 = 管理员）==")
        call("POST", "/api/v1/auth/register", body={"username": USER, "password": PWD})
        st, r, _ = call("POST", "/api/v1/auth/login", body={"username": USER, "password": PWD})
        check(st == 200 and r.get("access_token"), "登录成功")
        TOKEN["v"] = r["access_token"]
        st, me, _ = call("GET", "/api/v1/auth/me")
        MEDIA_KEY["v"] = me.get("media_key", "")
        check(bool(MEDIA_KEY["v"]), "取得 media_key")
        st, dev, _ = call("POST", "/api/v1/devices/register", body={"name": "回归短信设备", "kind": "sms"})
        check(st == 200 and dev.get("device_id"), "注册短信设备")
        DEV["sms"] = (dev["device_id"], dev["device_secret"])

        print("== 1. Jellyfin 客户端（影视）==")
        st, _, _ = call("PUT", "/api/v1/video/config", body={
            "enabled": True, "source": "jellyfin", "jf_url": jf_url,
            "jf_user": "video-user", "jf_pass": "video-pass"})
        check(st == 200, "保存影视 Jellyfin 配置")

        with JF.lock:
            JF.seen.clear()
            JF.auth_calls.clear()
        st, mov, _ = call("GET", "/api/v1/video/jf/movies")
        check(st == 200 and mov["total"] == 1 and mov["items"][0]["title"] == "Movie One", "影视电影列表")
        st, ser, _ = call("GET", "/api/v1/video/jf/series")
        check(st == 200 and ser["items"][0]["episode_count"] == 2, "影视剧集列表")
        st, eps, _ = call("GET", "/api/v1/video/jf/episodes/ser1")
        check(st == 200 and len(eps["items"]) == 2, "分集列表")
        check((eps.get("resume") or {}).get("id") == "ep2" and eps["resume"]["episode"] == 2,
              "剧集 resume 来自上游 NextUp（上次看到哪集）", str(eps.get("resume")))
        with JF.lock:
            video_tokens = {t for p, t in JF.seen if p == "/Items" or p.startswith("/Shows/")}
            video_auth = list(JF.auth_calls)
        check(video_tokens == {"tok-video-user"}, "影视侧使用配置的 Jellyfin 账号令牌", str(video_tokens))
        check(video_auth == ["video-user"], "影视侧按配置账号认证", str(video_auth))

        # 401 清缓存重认证一次
        with JF.lock:
            JF.seen.clear()
            JF.auth_calls.clear()
            JF.force_401_items = True
        st, mov2, _ = call("GET", "/api/v1/video/jf/movies")
        check(st == 200 and mov2["total"] == 1, "令牌吊销后自动重认证一次")
        with JF.lock:
            check("video-user" in JF.auth_calls, "重认证确实调用了 AuthenticateByName", str(JF.auth_calls))

        # 流式 Range 透传（media_key 鉴权）
        req = urllib.request.Request(
            f"{BASE}/api/v1/video/jf/stream/ep1?token={MEDIA_KEY['v']}",
            headers={"Range": "bytes=16-47"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            check(resp.status == 206 and len(body) == 32, "影视流式 Range 透传",
                  f"status={resp.status} len={len(body)}")

        # 封面（原始字节透传）
        req = urllib.request.Request(f"{BASE}/api/v1/video/jf/image/mov1?token={MEDIA_KEY['v']}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            check(resp.status == 200 and resp.read() == JPEG, "影视封面字节透传")

        # 观影进度双写上游
        with JF.lock:
            JF.progress.clear()
        st, _, _ = call("POST", "/api/v1/video/progress", body={
            "source": "jellyfin", "key": "mov1", "position": 120, "duration": 7200})
        st2, _, _ = call("POST", "/api/v1/video/progress/stop", body={
            "source": "jellyfin", "key": "mov1", "position": 130, "duration": 7200})
        with JF.lock:
            prog = list(JF.progress)
        check(st == 200 and st2 == 200, "影视进度上报成功")
        check(prog == [("/Sessions/Playing/Progress", "mov1"), ("/Sessions/Playing/Stopped", "mov1")],
              "进度双写上游（Progress + Stopped）", str(prog))
        st, res, _ = call("GET", "/api/v1/video/resume")
        check(st == 200 and res["source"] == "jellyfin" and res["items"][0]["percent"] == 8,
              "继续观看（IsResumable + 百分比换算）", str(res)[:160])
        st, rec, _ = call("GET", "/api/v1/video/recent")
        check(st == 200 and len(rec["items"]) >= 1, "最近添加")
        kinds = [i["kind"] for i in rec["items"]]
        check("episode" not in kinds and "series" in kinds,
              "Jellyfin 最近添加：剧集以 Series 条目出现（不逐集刷屏）", str(rec["items"])[:160])

        print("== 2. 共享 NAS 扫描引擎 ==")
        (music_dir / "Track A.mp3").write_bytes(b"ID3-fake-a" * 100)
        (music_dir / "Track B.flac").write_bytes(b"fLaC-fake-b" * 100)
        call("PUT", "/api/v1/music/config", body={
            "enabled": True, "source": "nas", "nas_path": str(music_dir)})
        st, _, _ = call("POST", "/api/v1/music/scan")
        state = poll_scan("music")
        check(state.get("phase") == "done" and state.get("added") == 2 and state.get("total") == 2,
              "音乐首次扫描：全量入库 2 首", str(state))
        check(state.get("scanner_version") == 2, "扫描结果记录解析器版本", str(state))
        st, tr, _ = call("GET", "/api/v1/music/tracks")
        check(st == 200 and tr["total"] == 2, "曲目列表可见", str(tr)[:120])
        titles = {t["title"] for t in tr["items"]}
        check(titles == {"Track A", "Track B"}, "无标签文件回退文件名", str(titles))

        st, _, _ = call("POST", "/api/v1/music/scan")
        state = poll_scan("music")
        check(state.get("added") == 0 and state.get("updated") == 0 and state.get("removed") == 0,
              "增量扫描：mtime/size 未变全部跳过", str(state))

        time.sleep(1.1)  # 让 mtime 变化可辨
        (music_dir / "Track A.mp3").write_bytes(b"ID3-fake-a-changed" * 200)
        st, _, _ = call("POST", "/api/v1/music/scan")
        state = poll_scan("music")
        check(state.get("updated") == 1 and state.get("added") == 0, "变更文件被更新", str(state))

        (music_dir / "Track B.flac").unlink()
        st, _, _ = call("POST", "/api/v1/music/scan")
        state = poll_scan("music")
        check(state.get("removed") == 1, "删除的文件从库中移除", str(state))
        st, tr, _ = call("GET", "/api/v1/music/tracks")
        check(tr["total"] == 1, "曲目列表同步为 1")

        # 影视：sample/隐藏文件跳过、集号解析、状态键独立
        (video_dir / "Movie One (2019).mp4").write_bytes(b"mp4-fake" * 100)
        (video_dir / "Some Show S01E02.mkv").write_bytes(b"mkv-fake" * 100)
        (video_dir / "trailer.sample.mp4").write_bytes(b"sample" * 100)
        (video_dir / ".hidden.mp4").write_bytes(b"hidden" * 100)
        call("PUT", "/api/v1/video/config", body={
            "enabled": True, "source": "nas", "nas_path": str(video_dir)})
        st, _, _ = call("POST", "/api/v1/video/scan")
        vstate = poll_scan("video")
        check(vstate.get("phase") == "done" and vstate.get("total") == 2 and vstate.get("added") == 2,
              "影视扫描：sample/隐藏文件被跳过", str(vstate))
        mstate = call("GET", "/api/v1/music/scan/status")[1]
        check(mstate.get("total") == 1 and mstate.get("phase") == "done",
              "音乐/影视扫描状态键互不覆盖", f"music={mstate.get('total')}")
        st, mv, _ = call("GET", "/api/v1/video/nas/movies")
        check(st == 200 and mv["total"] == 1 and mv["items"][0]["title"] == "Movie One",
              "电影解析（年份剥离）", str(mv)[:160])
        st, sv, _ = call("GET", "/api/v1/video/nas/series")
        check(st == 200 and sv["items"][0]["series"] == "Some Show"
              and sv["items"][0]["seasons"] == [1], "剧集解析（SxxExx + 季）", str(sv)[:160])
        st, epv, _ = call("GET", "/api/v1/video/nas/episodes?series=Some%20Show")
        check(st == 200 and epv["items"][0]["episode"] == 2 and epv["items"][0]["season"] == 1,
              "分集列表（季/集号）", str(epv)[:160])
        st, vc, _ = call("GET", "/api/v1/video/config")
        check(vc.get("nas_video_count") == 2, "影视配置里的库计数", str(vc))

        # ---- 影视 NFO 元数据与海报/剧照探测 ----
        movie_dir = video_dir / "电影" / "华语电影" / "GAAMA 2160p"
        movie_dir.mkdir(parents=True)
        (movie_dir / "GAAMA 2160p.mp4").write_bytes(b"mp4-movie" * 100)
        (movie_dir / "GAAMA 2160p.nfo").write_text(MOVIE_NFO, encoding="utf-8")
        (movie_dir / "poster.jpg").write_bytes(b"POSTER-GENERIC" * 8)
        (movie_dir / "art-custom.jpg").write_bytes(b"POSTER-CUSTOM" * 8)
        (movie_dir / "fanart.jpg").write_bytes(b"FANART-ONLY" * 8)
        (movie_dir / "backdrop.jpg").write_bytes(b"FANART-SECOND" * 8)  # 本地多图：轮播列表第二张

        bad_dir = video_dir / "电影" / "Bad Ref (2020)"
        bad_dir.mkdir(parents=True)
        (bad_dir / "Bad Ref (2020).mp4").write_bytes(b"mp4-bad" * 100)
        (bad_dir / "Bad Ref (2020).nfo").write_text(BAD_NFO, encoding="utf-8")
        (tmp / "outside.jpg").write_bytes(b"SECRET-OUTSIDE" * 8)

        series_dir = video_dir / "电视剧" / "庆余年 (2019)"
        season_dir = series_dir / "Season 1"
        season_dir.mkdir(parents=True)
        (season_dir / "庆余年.S01E01.mkv").write_bytes(b"mkv-ep1" * 100)
        (season_dir / "庆余年.S01E01.nfo").write_text(EP_NFO, encoding="utf-8")
        (series_dir / "tvshow.nfo").write_text(SHOW_NFO, encoding="utf-8")
        (series_dir / "庆余年 (2019)-poster.jpg").write_bytes(b"POSTER-SERIES-A" * 8)
        (series_dir / "庆余年 (2019).jpg").write_bytes(b"POSTER-SERIES-B" * 8)
        (series_dir / "logo.png").write_bytes(b"LOCAL-LOGO-SERIES" * 8)

        call("POST", "/api/v1/video/scan")
        vstate = poll_scan("video")
        check(vstate.get("added") == 3 and vstate.get("updated") == 0,
              "NFO 素材入库（新增 3 条，老条目跳过）", str(vstate))

        st, mv2, _ = call("GET", "/api/v1/video/nas/movies?page_size=90")
        by_title = {m["title"]: m for m in mv2["items"]}
        gab = by_title.get("给阿嬷的情书")
        check(gab is not None and gab["year"] == 2026 and gab["rating"] == 8.7,
              "NFO 覆盖文件名解析（标题/年份/新版评分结构）", str(gab)[:180])
        check(gab is not None and gab["genres"] == ["剧情", "家庭"] and gab["duration"] == 118 * 60,
              "NFO 类型与时长（分钟 → 秒）", str(gab and gab.get("genres")))
        st, det, _ = call("GET", f"/api/v1/video/nas/detail/{gab['id']}")
        check(st == 200 and "潮汕" in det.get("plot", ""), "详情返回 NFO 剧情", str(det)[:120])
        check(det.get("directors") == ["蓝鸿春", "郑萱轩"], "导演去重", str(det.get("directors")))
        check(len(det.get("actors") or []) == 1 and det["actors"][0][0] == "李思潼",
              "演员表解析（姓名/角色/头像）", str(det.get("actors"))[:120])
        check(det.get("has_poster") is True and det.get("has_fanart") is True, "海报/剧照可用性探测")

        req = urllib.request.Request(f"{BASE}/api/v1/video/nas/poster/{gab['id']}?token={MEDIA_KEY['v']}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
        check(resp.status == 200 and body.startswith(b"POSTER-CUSTOM"),
              "NFO 声明海报优先于通用名", str(body[:16]))
        req = urllib.request.Request(f"{BASE}/api/v1/video/nas/fanart/{gab['id']}?token={MEDIA_KEY['v']}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
        check(resp.status == 200 and body.startswith(b"FANART-ONLY"), "剧照接口返回 fanart.jpg", str(body[:16]))

        bad = by_title.get("Bad Ref")
        try:
            req = urllib.request.Request(f"{BASE}/api/v1/video/nas/poster/{bad['id']}?token={MEDIA_KEY['v']}")
            urllib.request.urlopen(req, timeout=15)
            check(False, "NFO 海报引用越界被拦截", "竟然返回 200")
        except urllib.error.HTTPError as e:
            check(e.code == 404, "NFO 海报引用越界被拦截（404，不服务媒体根外文件）", str(e.code))

        st, sv2, _ = call("GET", f"/api/v1/video/nas/series?q={quote('庆余年')}")
        srow = (sv2.get("items") or [{}])[0]
        check(srow.get("rating") == 9.1 and srow.get("genres") == ["古装", "权谋"],
              "剧集级 NFO（评分/类型聚合）", str(srow)[:180])
        check("范闲" in srow.get("plot", ""), "剧集级 NFO 剧情", str(srow.get("plot"))[:60])
        st, epv2, _ = call("GET", f"/api/v1/video/nas/episodes?series={quote('庆余年')}")
        e1 = (epv2.get("items") or [{}])[0]
        check(e1.get("ep_title") == "初入京都" and e1.get("duration") == 45 * 60,
              "分集 NFO（标题/时长）", str(e1)[:180])
        req = urllib.request.Request(f"{BASE}/api/v1/video/nas/poster/{e1['id']}?token={MEDIA_KEY['v']}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
        check(resp.status == 200 and body.startswith(b"POSTER-SERIES-A"),
              "分集海报回探剧集目录（<剧名>-poster.jpg 优先于 <剧名>.jpg）", str(body[:18]))
        req = urllib.request.Request(f"{BASE}/api/v1/video/nas/logo/{e1['id']}?token={MEDIA_KEY['v']}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
        check(resp.status == 200 and body.startswith(b"LOCAL-LOGO-SERIES"),
              "分集 Logo 回探剧集目录（本地 logo.png 优先）", str(body[:18]))

        # NFO 重写（视频文件未动）→ 单条重解析；无变化 → 全量跳过
        (movie_dir / "GAAMA 2160p.nfo").write_text(
            MOVIE_NFO.replace("潮汕阿嬷叶淑柔", "重写后的剧情"), encoding="utf-8")
        call("POST", "/api/v1/video/scan")
        vstate2 = poll_scan("video")
        check(vstate2.get("updated") == 1 and vstate2.get("added") == 0,
              "NFO 重写触发单条重新解析", str(vstate2))
        st, det2, _ = call("GET", f"/api/v1/video/nas/detail/{gab['id']}")
        check("重写后的剧情" in det2.get("plot", ""), "详情读到重写后的 NFO 内容", str(det2.get("plot"))[:60])
        call("POST", "/api/v1/video/scan")
        vstate3 = poll_scan("video")
        check(vstate3.get("updated") == 0 and vstate3.get("added") == 0,
              "无变化扫描全量跳过（增量键含 NFO 签名）", str(vstate3))

        # ---- 在线补全（假 TMDB）：未配 Key 静默 / 配 Key 下载缓存 / 本地优先 / 非法编号拦截 ----
        print("== 2b. 在线补全（TMDB，假服务）==")
        tmdb_movie_dir = video_dir / "电影" / "TMDB 无封面片 (2021)"
        tmdb_movie_dir.mkdir(parents=True)
        (tmdb_movie_dir / "TMDB 无封面片 (2021).mp4").write_bytes(b"mp4-tmdb" * 100)
        (tmdb_movie_dir / "TMDB 无封面片 (2021).nfo").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n<movie><title>TMDB 无封面片</title>'
            "<year>2021</year><tmdbid>2021</tmdbid></movie>",
            encoding="utf-8",
        )
        evil_dir = video_dir / "电影" / "Evil (2020)"
        evil_dir.mkdir(parents=True)
        (evil_dir / "Evil (2020).mp4").write_bytes(b"mp4-evil" * 100)
        (evil_dir / "Evil (2020).nfo").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n<movie><title>Evil</title>'
            "<tmdbid>../evil?x=1</tmdbid></movie>",
            encoding="utf-8",
        )
        # 庆余年补第二集：让「最近添加按剧聚合」用例真正覆盖多集合并（同剧两集只出一条）
        (season_dir / "庆余年.S01E02.mkv").write_bytes(b"mkv-ep2" * 100)
        online_show = video_dir / "电视剧" / "Online Show (2022)"
        (online_show / "Season 1").mkdir(parents=True)
        (online_show / "Season 1" / "Online Show.S01E01.mkv").write_bytes(b"mkv-online" * 100)
        (online_show / "tvshow.nfo").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n<tvshow><title>Online Show</title>'
            "<plot>在线补全剧集</plot><rating>8.8</rating><tmdbid>3030</tmdbid></tvshow>",
            encoding="utf-8",
        )
        # GAAMA 的 NFO 补 tmdbid（本地已有海报：在线补全必须跳过它）
        (movie_dir / "GAAMA 2160p.nfo").write_text(
            MOVIE_NFO.replace("<runtime>118</runtime>", "<runtime>118</runtime><tmdbid>1001</tmdbid>"),
            encoding="utf-8",
        )
        # 指定假 TMDB 地址（接口与图片同一假服务）；先不配 Key
        call("PUT", "/api/v1/video/config", body={
            "enabled": True, "source": "nas",
            "tmdb_api_base": tmdb_base, "tmdb_image_base": tmdb_base,
        })
        call("POST", "/api/v1/video/scan")
        vstate_nokey = wait_video_scan(expected_art=0)
        check(vstate_nokey.get("scanner_version") == 2, "扫描状态记录解析器版本 2", str(vstate_nokey.get("scanner_version")))
        check(not TMDB_HITS, "未配置 Key 时不发起任何 TMDB 请求", str(TMDB_HITS[:3]))
        st, m_all, _ = call("GET", "/api/v1/video/nas/movies?page_size=90")
        tm_item = next(m for m in m_all["items"] if m["title"] == "TMDB 无封面片")
        st, det_nokey, _ = call("GET", f"/api/v1/video/nas/detail/{tm_item['id']}")
        check(det_nokey.get("has_poster") is False, "无 Key 时缺封面影片保持占位", str(det_nokey.get("has_poster")))

        # 配置 Key → 重新扫描 → 补全下载并落缓存
        call("PUT", "/api/v1/video/config", body={
            "enabled": True, "source": "nas", "tmdb_key": TMDB_KEY,
            "tmdb_api_base": tmdb_base, "tmdb_image_base": tmdb_base,
        })
        st, vcfg2, _ = call("GET", "/api/v1/video/config")
        check(vcfg2.get("tmdb_key_set") is True and vcfg2.get("tmdb_key") == TMDB_KEY,
              "配置回显 Key：管理员可核对真实值（掩码展示由前端负责）", str(vcfg2.get("tmdb_key_set")))
        call("POST", "/api/v1/video/scan")
        vstate_art = wait_video_scan(expected_art=2)
        check(vstate_art.get("art_total") == 3 and vstate_art.get("art_failed") == 0,
              "补全阶段：3 个目标全部成功（电影 + 剧集 + 仅缺 Logo 的条目）",
              f"art_total={vstate_art.get('art_total')} art_failed={vstate_art.get('art_failed')}")

        req = urllib.request.Request(f"{BASE}/api/v1/video/nas/poster/{tm_item['id']}?token={MEDIA_KEY['v']}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
        check(body.startswith(b"IMG:/t/p/w500/regr-poster-2021.jpg"),
              "电影海报来自 TMDB 缓存（w500）", str(body[:40]))
        req = urllib.request.Request(f"{BASE}/api/v1/video/nas/fanart/{tm_item['id']}?token={MEDIA_KEY['v']}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
        check(body.startswith(b"IMG:/t/p/w1280/regr-backdrop-2021.jpg"),
              "电影剧照来自 TMDB 缓存（w1280）", str(body[:44]))
        cache_dir = DATA_DIR / "ihub_media" / "video_covers"  # 2026-10-25 起 v2 目录布局
        check((cache_dir / "poster-movie-2021.jpg").is_file() and (cache_dir / "backdrop-movie-2021.jpg").is_file(),
              "缓存文件落盘 data/video_covers", str(sorted(p.name for p in cache_dir.glob("*"))[:4]))
        req = urllib.request.Request(f"{BASE}/api/v1/video/nas/logo/{tm_item['id']}?token={MEDIA_KEY['v']}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
        check(resp.status == 200 and body.startswith(b"IMG:/t/p/w500/regr-logo-2021.png"),
              "电影 Logo 来自 TMDB 缓存（中文 logo 优先）", str(body[:42]))
        check((cache_dir / "logo-movie-2021.png").is_file(), "Logo 缓存文件落盘")

        # ---- 多剧照（hero 轮播）：扩展图落缓存 + 索引接口 + 标记防重复 ----
        print("== 2d. 详情页多剧照（hero 轮播）==")
        check((cache_dir / "backdrop-movie-2021-2.jpg").is_file() and (cache_dir / "backdrop-movie-2021-3.jpg").is_file()
              and not (cache_dir / "backdrop-movie-2021-4.jpg").exists(),
              "扩展剧照落缓存（主图 + -2/-3，同主图条目已去重）",
              str(sorted(p.name for p in cache_dir.glob("backdrop-movie-2021*"))))
        check((cache_dir / "bd-tried-movie-2021").is_file(), "剧照补全标记落盘（防重复拉取）")
        shots = []
        for i in (0, 1, 2):
            req = urllib.request.Request(f"{BASE}/api/v1/video/nas/fanart/{tm_item['id']}?i={i}&token={MEDIA_KEY['v']}")
            with urllib.request.urlopen(req, timeout=15) as resp:
                shots.append(resp.read())
        check(shots[0].startswith(b"IMG:/t/p/w1280/regr-backdrop-2021.jpg")
              and shots[1].startswith(b"IMG:/t/p/w1280/regr-bd2-2021.jpg")
              and shots[2].startswith(b"IMG:/t/p/w1280/regr-bd3-2021.jpg"),
              "剧照索引 0/1/2 按序返回（主图 + 扩展图，无语言标记优先）", str([x[:38] for x in shots]))
        try:
            req = urllib.request.Request(f"{BASE}/api/v1/video/nas/fanart/{tm_item['id']}?i=3&token={MEDIA_KEY['v']}")
            urllib.request.urlopen(req, timeout=15)
            check(False, "剧照索引越界返回 404", "竟然返回 200")
        except urllib.error.HTTPError as e:
            check(e.code == 404, "剧照索引越界返回 404", str(e.code))
        try:
            req = urllib.request.Request(f"{BASE}/api/v1/video/nas/fanart/{tm_item['id']}?i=-1&token={MEDIA_KEY['v']}")
            urllib.request.urlopen(req, timeout=15)
            check(False, "剧照负索引返回 404", "竟然返回 200")
        except urllib.error.HTTPError as e:
            check(e.code == 404, "剧照负索引返回 404", str(e.code))
        st, det_art, _ = call("GET", f"/api/v1/video/nas/detail/{tm_item['id']}")
        check(det_art.get("fanart_count") == 3, "详情返回剧照张数（前端轮播用）", str(det_art.get("fanart_count")))
        req = urllib.request.Request(f"{BASE}/api/v1/video/nas/fanart/{gab['id']}?i=1&token={MEDIA_KEY['v']}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            body2 = resp.read()
        check(body2.startswith(b"FANART-SECOND"), "本地多剧照按序出图（i=1 为第二张）", str(body2[:16]))
        st, det_gab2, _ = call("GET", f"/api/v1/video/nas/detail/{gab['id']}")
        check(det_gab2.get("fanart_count") == 2, "本地多图计入剧照张数", str(det_gab2.get("fanart_count")))
        w1280_before = len([h for h in TMDB_HITS if "/t/p/w1280/" in h])
        call("POST", "/api/v1/video/scan")
        wait_video_scan(expected_art=0)
        check(len([h for h in TMDB_HITS if "/t/p/w1280/" in h]) == w1280_before,
              "bd-tried 标记生效：重复扫描不再拉取剧照", f"before={w1280_before}")

        # ---- 2e. 无编号兜底：标题+年份自动匹配（宁缺毋滥）----
        print("== 2e. 无编号兜底（标题自动匹配）==")
        noid_dir = video_dir / "电影" / "无编号电影 (2019)"
        noid_dir.mkdir(parents=True)
        (noid_dir / "无编号电影 (2019).mp4").write_bytes(b"mp4-noid" * 100)
        (noid_dir / "无编号电影 (2019).nfo").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n<movie><title>无编号电影</title><year>2019</year></movie>',
            encoding="utf-8",
        )
        amb_dir = video_dir / "电影" / "歧义片 (2019)"
        amb_dir.mkdir(parents=True)
        (amb_dir / "歧义片 (2019).mp4").write_bytes(b"mp4-amb" * 100)
        (amb_dir / "歧义片 (2019).nfo").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n<movie><title>歧义片</title><year>2019</year></movie>',
            encoding="utf-8",
        )
        noid_show = video_dir / "电视剧" / "无编号剧 (2023)"
        (noid_show / "Season 1").mkdir(parents=True)
        (noid_show / "Season 1" / "无编号剧.S01E01.mkv").write_bytes(b"mkv-noidshow" * 100)
        (noid_show / "tvshow.nfo").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n<tvshow><title>无编号剧</title><rating>7.9</rating></tvshow>',
            encoding="utf-8",
        )
        call("POST", "/api/v1/video/scan")
        wait_video_scan(expected_art=2)
        check(any("/3/search/movie" in h and quote("无编号电影") in h for h in TMDB_HITS),
              "无编号电影按标题发起 TMDB 搜索（query 已编码）",
              str([h for h in TMDB_HITS if "/3/search/" in h][:3]))
        st, m_noid, _ = call("GET", "/api/v1/video/nas/movies?page_size=90")
        noid = next(m for m in m_noid["items"] if m["title"] == "无编号电影")
        req = urllib.request.Request(f"{BASE}/api/v1/video/nas/poster/{noid['id']}?token={MEDIA_KEY['v']}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
        check(body.startswith(b"IMG:/t/p/w500/regr-poster-7777.jpg"),
              "标题匹配出的编号被用于补图（唯一候选+年份吻合）", str(body[:40]))
        st, det_noid, _ = call("GET", f"/api/v1/video/nas/detail/{noid['id']}")
        check(det_noid.get("has_poster") is True and det_noid.get("has_logo") is True,
              "无编号电影详情补全完成", str({k: det_noid.get(k) for k in ("has_poster", "has_logo")}))
        st, m_amb, _ = call("GET", "/api/v1/video/nas/movies?page_size=90")
        amb = next(m for m in m_amb["items"] if m["title"] == "歧义片")
        st, det_amb, _ = call("GET", f"/api/v1/video/nas/detail/{amb['id']}")
        check(det_amb.get("has_poster") is False and det_amb.get("has_fanart") is False,
              "同名多候选且年份无法区分：放弃匹配保持占位（宁缺毋滥）",
              str({k: det_amb.get(k) for k in ("has_poster", "has_fanart")}))
        check(not any("8801" in h or "8802" in h for h in TMDB_HITS), "歧义候选中任何一个都未被采用",
              str([h for h in TMDB_HITS if "880" in h][:2]))
        st, sv_noid, _ = call("GET", "/api/v1/video/nas/series?q=" + quote("无编号剧"))
        row_noid = (sv_noid.get("items") or [{}])[0]
        check(any("/3/search/tv" in h and quote("无编号剧") in h for h in TMDB_HITS),
              "无编号剧按剧名发起 TMDB 搜索", str([h for h in TMDB_HITS if "/3/search/tv" in h][:2]))
        req = urllib.request.Request(f"{BASE}/api/v1/video/nas/poster/{row_noid['cover_id']}?token={MEDIA_KEY['v']}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
        check(body.startswith(b"IMG:/t/p/w500/regr-tvposter-8888.jpg"),
              "剧集级标题匹配补图（全体分集共用编号）", str(body[:42]))
        cnt_before2 = len([h for h in TMDB_HITS if quote("无编号电影") in h])
        call("POST", "/api/v1/video/scan")
        wait_video_scan(expected_art=0)
        cnt_after2 = len([h for h in TMDB_HITS if quote("无编号电影") in h])
        check(cnt_after2 == cnt_before2,
              "匹配结果落库：重扫不再对已匹配条目重查", f"before={cnt_before2} after={cnt_after2}")

        # ---- 2f. 季级 nfo（<season>）：简介兜底 + 标题参与自动匹配 ----
        print("== 2f. 季级 nfo（season.nfo）==")
        pack = video_dir / "电视剧" / "NoIDPack 2023"
        season2 = pack / "Season 2"
        season2.mkdir(parents=True)
        (season2 / "NoIDPack.S02E01.mkv").write_bytes(b"mkv-pack" * 100)
        (season2 / "season.nfo").write_text("""<?xml version="1.0" encoding="utf-8"?>
<season>
  <plot>季级简介兜底文本</plot>
  <title>季名匹配剧</title>
  <year>2023</year>
  <seasonnumber>2</seasonnumber>
</season>""", encoding="utf-8")
        call("POST", "/api/v1/video/scan")
        wait_video_scan(expected_art=1)
        check(any("/3/search/tv" in h and quote("季名匹配剧") in h for h in TMDB_HITS),
              "季级 nfo 标题参与 TMDB 匹配", str([h for h in TMDB_HITS if quote("季名匹配剧") in h][:2]))
        check(not any(quote("NoIDPack") in h for h in TMDB_HITS),
              "季级 nfo 标题优先于目录名（目录名未参与搜索）",
              str([h for h in TMDB_HITS if "NoIDPack" in h][:2]))
        st, sv_pack, _ = call("GET", "/api/v1/video/nas/series?q=" + quote("NoIDPack"))
        row_pack = (sv_pack.get("items") or [{}])[0]
        check(row_pack.get("plot") == "季级简介兜底文本", "无 tvshow.nfo 时季简介兜底为剧集简介",
              str(row_pack.get("plot"))[:40])
        req = urllib.request.Request(f"{BASE}/api/v1/video/nas/poster/{row_pack['cover_id']}?token={MEDIA_KEY['v']}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
        check(body.startswith(b"IMG:/t/p/w500/regr-tvposter-9999.jpg"),
              "季标题匹配出的编号被用于补图", str(body[:40]))
        (season2 / "season.nfo").write_text("""<?xml version="1.0" encoding="utf-8"?>
<season>
  <plot>季级简介被重写后的文本</plot>
  <title>季名匹配剧</title>
  <year>2023</year>
</season>""", encoding="utf-8")
        call("POST", "/api/v1/video/scan")
        pol = poll_scan("video")
        check(pol.get("updated") == 1, "季级 nfo 重写触发单条重新解析", str(pol))
        st, sv_pack2, _ = call("GET", "/api/v1/video/nas/series?q=" + quote("NoIDPack"))
        check(((sv_pack2.get("items") or [{}])[0].get("plot") or "") == "季级简介被重写后的文本",
              "重写后的季简介生效", str((sv_pack2.get("items") or [{}])[0].get("plot"))[:40])

        st, m_all2, _ = call("GET", "/api/v1/video/nas/movies?page_size=90")
        gab3 = next(m for m in m_all2["items"] if m["title"] == "给阿嬷的情书")
        req = urllib.request.Request(f"{BASE}/api/v1/video/nas/poster/{gab3['id']}?token={MEDIA_KEY['v']}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
        check(body.startswith(b"POSTER-CUSTOM"),
              "本地已有海报时仍用本地图（本地优先）", str(body[:18]))
        check(any("/3/movie/1001" in h for h in TMDB_HITS)
              and not (cache_dir / "poster-movie-1001.jpg").exists()
              and not (cache_dir / "backdrop-movie-1001.jpg").exists()
              and (cache_dir / "logo-movie-1001.png").is_file(),
              "本地有海报/剧照时在线只补缺失的 Logo", str(sorted(p.name for p in cache_dir.glob("*1001*"))))
        # 恶意编号是「../evil?x=1」：检载荷本身（标题自动匹配会产生正常的 query=Evil 搜索请求）
        bad_hits = [h for h in TMDB_HITS if ".." in h or "evil?x=1" in h.lower() or "evil%3fx" in h.lower()]
        check(not bad_hits, "非法 TMDB 编号载荷未拼入上游请求（路径穿越/参数注入）", str(bad_hits[:3]))
        evil = next(m for m in m_all2["items"] if m["title"] == "Evil")
        st, det_evil, _ = call("GET", f"/api/v1/video/nas/detail/{evil['id']}")
        check(det_evil.get("has_poster") is False, "非法编号影片保持占位", str(det_evil.get("has_poster")))

        st, epv4, _ = call("GET", f"/api/v1/video/nas/episodes?series={quote('Online Show')}")
        e4 = (epv4.get("items") or [{}])[0]
        req = urllib.request.Request(f"{BASE}/api/v1/video/nas/poster/{e4['id']}?token={MEDIA_KEY['v']}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
        check(body.startswith(b"IMG:/t/p/w500/regr-tvposter-3030.jpg"),
              "剧集海报来自 TMDB 缓存（tvshow.nfo 编号，全剧共用）", str(body[:46]))

        shutil.rmtree(tmdb_movie_dir)
        call("POST", "/api/v1/video/scan")
        wait_video_scan(expected_art=0)
        check(not (cache_dir / "poster-movie-2021.jpg").exists()
              and not (cache_dir / "backdrop-movie-2021.jpg").exists()
              and not (cache_dir / "backdrop-movie-2021-2.jpg").exists()
              and not (cache_dir / "bd-tried-movie-2021").exists()
              and not (cache_dir / "logo-movie-2021.png").exists(),
              "条目删除后其缓存图（含扩展剧照/标记/Logo）被清理", str(sorted(p.name for p in cache_dir.glob("*"))[:4]))

        # ---- 最近添加：剧集按剧聚合为一条 + 剧集卡代表 id（cover_id）----
        print("== 2c. 首页聚合与剧集封面代表 id ==")
        # 让时间序确定：给 Online Show 补一集（新扫描入库），它应上浮到剧集条目最前
        (online_show / "Season 1" / "Online Show.S01E02.mkv").write_bytes(b"mkv-online2" * 100)
        call("POST", "/api/v1/video/scan")
        wait_video_scan(expected_art=0)
        st, rec, _ = call("GET", "/api/v1/video/recent")
        items = rec["items"]
        kinds = [(i["kind"], i.get("series") or i.get("title")) for i in items]
        check(not [k for k in kinds if k[0] == "episode"], "最近添加不含单集条目（剧集已聚合）", str(kinds)[:180])
        qy = next((i for i in items if i.get("series") == "庆余年"), None)
        check(qy is not None and qy["kind"] == "series" and qy["episode_count"] == 2,
              "剧集聚合为一条并带集数", str(qy)[:180])
        st, sv3, _ = call("GET", "/api/v1/video/nas/series")
        qy_row = next((s for s in sv3["items"] if s["series"] == "庆余年"), {})
        check(isinstance(qy_row.get("cover_id"), int) and qy_row["cover_id"] > 0,
              "剧集列表返回 cover_id（代表分集）", str(qy_row.get("cover_id")))
        req = urllib.request.Request(f"{BASE}/api/v1/video/nas/poster/{qy['id']}?token={MEDIA_KEY['v']}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
        check(resp.status == 200 and body.startswith(b"POSTER-SERIES-A"),
              "聚合剧集条目的封面可加载（代表 id 为真实分集）", str(body[:18]))
        names = [i["series"] for i in items if i["kind"] == "series"]
        check(bool(names) and names[0] == "Online Show",
              "聚合条目按最新一集入库时间排序（新集入库后上浮）", str(names))

        # NAS 剧集详情：写下进度后 resume 指向那一集（「播放」按钮记住上次看到第几集）
        st, epv5, _ = call("GET", f"/api/v1/video/nas/episodes?series={quote('庆余年')}")
        check(epv5.get("resume") is None, "无观影记录时 resume 为空（按钮显示「播放」）", str(epv5.get("resume")))
        first_ep = epv5["items"][0]
        st, _, _ = call("POST", "/api/v1/video/progress", body={
            "source": "nas", "key": str(first_ep["id"]), "position": 120, "duration": 2760})
        st, epv6, _ = call("GET", f"/api/v1/video/nas/episodes?series={quote('庆余年')}")
        res = epv6.get("resume") or {}
        item0 = (epv6.get("items") or [{}])[0]
        check(res.get("id") == first_ep["id"] and res.get("episode") == first_ep["episode"],
              "NAS 剧集 resume 指向最近观看的一集", str(res))
        check(item0.get("percent") == 4 and item0.get("position") == 120,
              "分集条目带观影进度（percent/position）", f"percent={item0.get('percent')}")

        print("== 3. 总览趋势（SQL 分桶）==")
        tz = ZoneInfo("Asia/Shanghai")
        now_local = datetime.now(tz)
        for days_ago in (0, 1, 3, 8):
            day = (now_local - timedelta(days=days_ago)).date()
            noon = datetime.combine(day, datetime.min.time(), tzinfo=tz).replace(hour=12)
            push_msg({"from": "10086", "msg": f"趋势回归 {days_ago} 天前",
                      "timestamp": int(noon.timestamp())}, int(time.time()))
        st, stats, _ = call("GET", "/api/v1/stats")
        trend = stats.get("trend", [])
        check(st == 200 and len(trend) == 7, "趋势返回 7 天", str(len(trend)))
        dates = [t["date"] for t in trend]
        check(dates == sorted(dates), "趋势按日期升序", str(dates))
        total_trend = sum(t["sms"] for t in trend)
        check(total_trend == 3, "窗口内 3 条计入、8 天前的不计入", str(trend))
        want_today = (now_local).date().isoformat()
        want_old = (now_local - timedelta(days=3)).date().isoformat()
        by_date = {t["date"]: t["sms"] for t in trend}
        check(by_date.get(want_today) == 1, "今天桶命中本地日界", f"{want_today}={by_date.get(want_today)}")
        check(by_date.get(want_old) == 1, "3 天前桶命中", f"{want_old}={by_date.get(want_old)}")
        check(stats.get("total", 0) >= 4, "总消息数含窗口外消息", str(stats.get("total")))
        check("hub" in stats, "总览 8 项统计存在")
    finally:
        srv.shutdown()
        tmdb_srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n通过 {PASSED} 项，失败 {FAILED} 项")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
