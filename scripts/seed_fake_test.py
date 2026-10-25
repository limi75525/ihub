"""种子模块回归：内置假 qBittorrent / MoviePilot，不需要真实 NAS 服务。

用法：
  .venv/Scripts/python scripts/seed_fake_test.py

脚本会：
- 在随机端口起假 QB/MP HTTP 服务；
- 用临时数据目录起一个 uvicorn 实例；
- 注册管理员/普通用户，配置连接；
- 验证只读、权限、删除二次确认+密码、MP 搜索脱敏、事件进消息中心、系统来源隐藏；
- 退出码 0 = 全部通过。
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, ".seed-fake-data")
QB_TOKEN = "qb-test"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class QuietHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _send(self, status: int, body, *, content_type="application/json", headers=None):
        if isinstance(body, (dict, list)):
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            raw = body.encode("utf-8")
        else:
            raw = body or b""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)


class FakeQbState:
    torrents = [
        {
            "hash": "aaa111", "name": "下载中的种子", "state": "downloading",
            "progress": 0.42, "size": 10 * 1024 * 1024, "total_size": 10 * 1024 * 1024,
            "dlspeed": 1024 * 1024, "upspeed": 2048, "eta": 60, "ratio": 0.12,
            "category": "电影", "tags": "4K,测试", "added_on": 1000, "completion_on": 0,
            "save_path": "/downloads", "content_path": "/downloads/a", "tracker": "https://tracker/announce?passkey=SECRET",
            "num_seeds": 5, "num_leechs": 2, "amount_left": 5 * 1024 * 1024,
        },
        {
            "hash": "bbb222", "name": "已完成的种子", "state": "uploading",
            "progress": 1, "size": 2 * 1024 * 1024, "total_size": 2 * 1024 * 1024,
            "dlspeed": 0, "upspeed": 4096, "eta": 0, "ratio": 1.5,
            "category": "电影", "tags": "测试", "added_on": 900, "completion_on": 1000,
            "save_path": "/downloads", "content_path": "/downloads/b", "tracker": "https://tracker/announce?passkey=SECRET",
            "num_seeds": 3, "num_leechs": 0, "amount_left": 0,
        },
    ]
    deleted = None
    added = None
    last_location = None
    last_category = None
    last_tags = None
    actions: list[str] = []


class FakeMpState:
    notifications = [
        {
            "id": 1, "mtype": "其它", "ctype": "", "title": "旧通知",
            "text": "历史通知", "reg_time": "2026-10-21 10:00:00",
        }
    ]
    subscriptions = [
        {
            "id": 11, "name": "示例电影", "year": "2024", "type": "电影",
            "state": "R", "total_episode": 1, "lack_episode": 0,
            "poster": "https://img.example/poster.jpg", "last_update": "2026-10-21 10:00:00",
        },
        {
            "id": 12, "name": "示例剧集", "year": "2025", "type": "电视剧",
            "state": "R", "total_episode": 10, "lack_episode": 4,
            "poster": "https://img.example/tv.jpg", "last_update": "2026-10-21 10:00:00",
        },
        {
            "id": 13, "name": "示例专辑", "year": "2026", "type": "音乐",
            "state": "R", "total_tracks": 12, "completed_tracks": 3,
            "poster": "https://img.example/music.jpg", "last_update": "2026-10-21 10:00:00",
        },
    ]
    sites = [
        {"id": 1, "name": "馒头", "domain": "m-team.cc", "url": "https://m-team.cc", "is_active": True},
        {"id": 2, "name": "憨憨", "domain": "hhanclub.net", "url": "https://hhanclub.net", "is_active": True},
    ]
    site_stats = [
        {"site_id": 1, "upload": 1000, "download": 500, "ratio": 2.0, "user_level": "Elite"},
        {"site_id": 2, "upload": 2000, "download": 1000, "ratio": 2.0, "user_level": "Power User"},
    ]
    media = [
        {
            "media_id": "27205", "media_source": "tmdb", "title": "盗梦空间",
            "year": "2010", "type": "movie", "poster": "https://img.example/inception.jpg",
            "overview": "示例简介", "vote": 8.8,
        }
    ]
    torrents = [
        {
            # MP v3 实际返回的嵌套结构；后端必须能从这里取到标题/站点/大小
            "meta_info": {
                "name": "盗梦空间", "title": "盗梦空间.2010.2160p",
                "subtitle": "盗梦空间 / Inception",
                "type": "电影", "year": "2010", "resource_pix": "2160p",
                "resource_type": "WEB-DL", "resource_effect": "HDR",
                "video_encode": "H265", "audio_encode": "DDP 5.1",
                "media_source": "tmdb", "media_id": "27205",
            },
            "torrent_info": {
                "title": "盗梦空间.2010.2160p", "site_name": "馒头", "site": 1,
                "size": 20 * 1024 * 1024 * 1024, "seeders": 10, "peers": 2,
                "volume_factor": "Free", "pubdate": "2026-10-20",
                "page_url": "https://m-team.cc/t/1?passkey=SECRET",
                "description": "示例", "category": "电影", "hit_and_run": False,
                "freedate": "", "freedate_diff": "", "labels": [],
                # 下面字段必须被后端丢弃
                "enclosure": "https://site/download?passkey=SECRET",
                "site_cookie": "SECRET-COOKIE",
                "site_ua": "SECRET-UA",
                "site_proxy": True,
            },
        }
    ]
    history = [
        {
            "id": 1, "title": "示例电影", "year": "2024",
            "torrent_site": "馒头", "download_hash": "aaa111",
            "poster": "https://img.example/poster.jpg",
            "image": "https://img.example/backdrop.jpg",
        },
        {
            "id": 2, "title": "刷流任务", "year": "",
            "torrent_site": "", "download_hash": "ccc333",
            "poster": "", "image": "",
        },
    ]
    last_download = None
    last_subscribe = None
    last_discover = None
    last_recommend = None
    transfer_history = [
        {
            # 真实 MP 的整理历史结构：分页在 data.list；刷流种子可能没有 download_hash，
            # worker 必须能回退用 src 路径匹配 qB 的 save_path + name。
            "id": 7, "download_hash": "", "status": True,
            "src": "/media/下载/电影/已完成的种子/",
            "title": "已转媒体示例", "year": "2024",
            "image": "https://img.example/transferred.jpg",
            "media_id": "27205", "media_source": "themoviedb", "type": "电影",
        }
    ]
    brush = {
        "enabled": True,
        "summary": {
            "task_count": 1, "enabled_count": 1, "running_count": 0,
            "active_count": 3, "uploaded": 100, "downloaded": 20, "seeding_size": 50,
        },
        "tasks": [
            {
                "id": "t1", "name": "刷流任务", "enabled": True, "site_id": 1,
                "site_name": "馒头", "downloader": "qb", "state": "running",
                "last_error": "", "next_run_at": "2026-10-21 12:00", "last_run": None,
                "statistic": {"active": 3, "uploaded": 100, "downloaded": 20},
                "seeding_size": 50, "site_ratio": {},
            }
        ],
    }


class QbHandler(QuietHandler):
    def _authed(self) -> bool:
        return "SID=" in (self.headers.get("Cookie") or "")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        # 和真实 qB 一样：业务接口必须带登录后的 SID。
        # 这样测试才能捕获「业务请求绕过登录」的回归。
        if not self._authed():
            return self._send(403, "Forbidden", content_type="text/plain")
        if path == "/api/v2/app/version":
            return self._send(200, "v4.6.7", content_type="text/plain")
        if path == "/api/v2/app/webapiVersion":
            return self._send(200, "2.9.3", content_type="text/plain")
        if path == "/api/v2/transfer/info":
            return self._send(200, {
                "dl_info_speed": 1048576, "up_info_speed": 4096,
                "dl_info_data": 123456, "up_info_data": 654321,
            })
        if path == "/api/v2/sync/maindata":
            return self._send(200, {
                "server_state": {
                    "dl_info_speed": 1048576, "up_info_speed": 4096,
                    "dl_info_data": 123456, "up_info_data": 654321,
                    "free_space_on_disk": 1024 * 1024 * 1024, "connection_status": "connected",
                },
                "torrents": {t["hash"]: t for t in FakeQbState.torrents},
            })
        if path == "/api/v2/torrents/info":
            rows = list(FakeQbState.torrents)
            tag = (query.get("tag") or [""])[0]
            if tag:
                rows = [
                    row for row in rows
                    if tag in [x.strip() for x in str(row.get("tags") or "").split(",")]
                ]
            hashes = (query.get("hashes") or [""])[0]
            if hashes:
                wanted = {x.strip() for x in hashes.split("|") if x.strip()}
                rows = [row for row in rows if row.get("hash") in wanted]
            return self._send(200, rows)
        if path == "/api/v2/torrents/properties":
            wanted_hash = (query.get("hash") or ["aaa111"])[0]
            row = next(
                (x for x in FakeQbState.torrents if x.get("hash") == wanted_hash),
                FakeQbState.torrents[0],
            )
            return self._send(200, {
                **row,
                "share_ratio": row.get("ratio", 0),
                "pieces_num": 10,
                "pieces_have": 10,
            })
        if path == "/api/v2/torrents/files":
            return self._send(200, [{"name": "a.mkv", "size": 1024, "progress": 0.5, "priority": 1}])
        if path == "/api/v2/torrents/trackers":
            return self._send(200, [{"url": "https://tracker/announce?passkey=SECRET", "status": 2, "num_peers": 1, "num_seeds": 2}])
        if path == "/api/v2/torrents/peers":
            return self._send(200, {"peers": {}})
        if path == "/api/v2/torrents/categories":
            return self._send(200, {"电影": {"name": "电影", "savePath": "/downloads"}})
        if path == "/api/v2/torrents/tags":
            # 空标签模拟 qB 保留的全局标签定义：没有任何任务使用。
            return self._send(200, ["测试", "4K", "空标签"])
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        raw = self._body()
        try:
            form = urllib.parse.parse_qs(raw.decode("utf-8"))
        except (UnicodeDecodeError, AttributeError):
            form = {}
        if path == "/api/v2/auth/login":
            return self._send(
                200, "Ok.", content_type="text/plain",
                headers={"Set-Cookie": "SID=fake-qb; Path=/; HttpOnly"},
            )
        if not self._authed():
            return self._send(403, "Forbidden", content_type="text/plain")
        if path in ("/api/v2/torrents/pause", "/api/v2/torrents/resume",
                    "/api/v2/torrents/recheck", "/api/v2/torrents/reannounce"):
            FakeQbState.actions.append(path.rsplit("/", 1)[-1])
            return self._send(200, "Ok.", content_type="text/plain")
        if path == "/api/v2/torrents/delete":
            FakeQbState.deleted = self.path
            return self._send(200, "Ok.", content_type="text/plain")
        if path == "/api/v2/torrents/setLocation":
            location = (form.get("location") or [""])[0]
            FakeQbState.last_location = location
            wanted = set((form.get("hashes") or [""])[0].split("|"))
            for row in FakeQbState.torrents:
                if row.get("hash") in wanted:
                    row["save_path"] = location
            return self._send(200, "Ok.", content_type="text/plain")
        if path == "/api/v2/torrents/setCategory":
            FakeQbState.last_category = (form.get("category") or [""])[0]
            wanted = set((form.get("hashes") or [""])[0].split("|"))
            for row in FakeQbState.torrents:
                if row.get("hash") in wanted:
                    row["category"] = FakeQbState.last_category
            return self._send(200, "Ok.", content_type="text/plain")
        if path in ("/api/v2/torrents/addTags", "/api/v2/torrents/removeTags"):
            added = path.endswith("addTags")
            new_tags = [x.strip() for x in (form.get("tags") or [""])[0].split(",") if x.strip()]
            FakeQbState.last_tags = new_tags
            wanted = set((form.get("hashes") or [""])[0].split("|"))
            for row in FakeQbState.torrents:
                if row.get("hash") not in wanted:
                    continue
                current = [x.strip() for x in str(row.get("tags") or "").split(",") if x.strip()]
                if added:
                    current = list(dict.fromkeys(current + new_tags))
                else:
                    current = [x for x in current if x not in new_tags]
                row["tags"] = ",".join(current)
            return self._send(200, "Ok.", content_type="text/plain")
        if path == "/api/v2/torrents/add":
            FakeQbState.added = self.headers.get("Content-Type")
            return self._send(200, "Ok.", content_type="text/plain")
        return self._send(404, {"error": "not found"})


class MpHandler(QuietHandler):
    def _auth_ok(self) -> bool:
        return (self.headers.get("X-API-KEY") or "") == "test-token-1234567890"

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        if path == "/api/v1/login/access-token":
            return self._send(200, {"access_token": "jwt"})
        if not self._auth_ok():
            return self._send(401, {"detail": "bad token"})
        if path == "/api/v1/mcp/tools":
            return self._send(200, [{"name": "moviepilot_api"}])
        if path == "/api/v1/system/status":
            return self._send(200, {"version": "v3.1.4"})
        if path == "/api/v1/dashboard/storage":
            return self._send(200, {"total_storage": 8880464400384, "used_storage": 2870252269568})
        if path == "/api/v1/subscribe/":
            return self._send(200, FakeMpState.subscriptions)
        if path in ("/api/v1/site/agent", "/api/v1/site/"):
            return self._send(200, FakeMpState.sites)
        if path == "/api/v1/site/statistic":
            return self._send(200, FakeMpState.site_stats)
        if path == "/api/v1/search/title":
            return self._send(200, FakeMpState.torrents)
        if path == "/api/v1/media/search":
            return self._send(200, FakeMpState.media)
        if path.startswith("/api/v1/media/"):
            return self._send(200, {
                "success": True,
                "data": {
                    "title": "示例电影", "year": "2024", "type": "电影",
                    "media_id": "27205", "media_source": "themoviedb",
                    "poster_path": "https://image.tmdb.org/t/p/original/poster.jpg",
                    "backdrop_path": "https://image.tmdb.org/t/p/original/backdrop.jpg",
                    "overview": "示例简介",
                    "original_title": "Example Movie",
                    "runtime": 118, "release_date": "2024-04-30",
                    "status": "Released", "original_language": "zh",
                    "genres": ["剧情", "家庭"], "production_countries": ["中国大陆"],
                    "production_companies": ["示例影业"],
                    "douban_id": "37116446", "imdb_id": "tt1234567",
                    "actors": [
                        {"name": "演员一", "character": "饰 主角", "profile_path": "https://img.example/p1.jpg"},
                        {"name": "演员二", "character": "饰 配角", "profile_path": ""},
                    ],
                    "seasons": [
                        {"name": "第 1 季", "season_number": 1, "episode_count": 12, "air_date": "2024-04-30"},
                        {"name": "第 2 季", "season_number": 2, "episode_count": 10, "air_date": "2025-04-30"},
                    ],
                },
            })
        if path.startswith("/api/v1/search/media/"):
            return self._send(200, FakeMpState.torrents)
        if path.startswith("/api/v1/recommend/"):
            FakeMpState.last_recommend = (path, query)
            return self._send(200, FakeMpState.media)
        if path.startswith("/api/v1/discover/") or path in (
            "/api/v1/anilist/discover", "/api/v1/music/explore"
        ):
            FakeMpState.last_discover = (path, query)
            return self._send(200, FakeMpState.media)
        if path == "/api/v1/history/download":
            return self._send(200, {
                "success": True,
                "data": {"list": FakeMpState.history, "total": len(FakeMpState.history)},
            })
        if path == "/api/v1/history/transfer":
            return self._send(200, {
                "success": True,
                "data": {"list": FakeMpState.transfer_history, "total": len(FakeMpState.transfer_history)},
            })
        if path == "/api/v1/message/notification":
            return self._send(200, sorted(FakeMpState.notifications, key=lambda x: x["id"], reverse=True))
        if path == "/api/v1/plugin/BrushFlow/status":
            return self._send(200, FakeMpState.brush)
        if path.startswith("/api/v1/plugin/BrushFlow/tasks/"):
            return self._send(200, {"task": FakeMpState.brush["tasks"][0], "summary": {}, "runs": [], "torrents": {}})
        if path == "/api/v1/plugin/":
            return self._send(200, [{"id": "BrushFlow", "plugin_name": "站点刷流"}])
        return self._send(404, {"detail": "not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        body = self._body()
        try:
            payload = json.loads(body or b"{}")
        except (TypeError, ValueError):
            payload = {}
        if path == "/api/v1/login/access-token":
            return self._send(200, {"access_token": "jwt"})
        if not self._auth_ok():
            return self._send(401, {"detail": "bad token"})
        if path == "/api/v1/mcp/tools/call":
            return self._send(200, {"success": True, "data": {"result": "{}"}})
        if path == "/api/v1/download/":
            FakeMpState.last_download = payload
            return self._send(200, {"success": True, "data": {"download_id": "fake-dl-1"}})
        if path == "/api/v1/subscribe/":
            FakeMpState.last_subscribe = payload
            return self._send(200, {"success": True, "data": {"id": 99}})
        return self._send(404, {"detail": "not found"})


def _request(base: str, method: str, path: str, token: str | None = None, body=None):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    safe_path = urllib.parse.quote(path, safe="/?&=:%#")
    req = urllib.request.Request(base + safe_path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = raw.decode("utf-8", "replace")
        return e.code, payload


def _wait_health(base: str, timeout: float = 25.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            status, _ = _request(base, "GET", "/api/health")
            if status == 200:
                return
        except Exception:
            pass
        time.sleep(0.4)
    raise RuntimeError("后端未在超时内就绪")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if os.path.isdir(DATA_DIR):
        shutil.rmtree(DATA_DIR, ignore_errors=True)
    qb_port, mp_port, api_port = _free_port(), _free_port(), _free_port()
    qb_server = ThreadingHTTPServer(("127.0.0.1", qb_port), QbHandler)
    mp_server = ThreadingHTTPServer(("127.0.0.1", mp_port), MpHandler)
    for server in (qb_server, mp_server):
        threading.Thread(target=server.serve_forever, daemon=True).start()

    log_path = os.path.join(ROOT, ".seed-fake-backend.log")
    log_file = open(log_path, "w", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "IHUB_DATA_DIR": DATA_DIR,
            "IHUB_SECRET_KEY": "seed-fake-test-secret",
            "IHUB_SEED_QB_INTERVAL": "2",
            "IHUB_SEED_MP_INTERVAL": "2",
            "IHUB_SEED_LOOP_SECONDS": "1",
        }
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(api_port), "--no-proxy-headers"],
        cwd=ROOT,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{api_port}"
    passed: list[str] = []
    failed: list[str] = []

    def check(name: str, cond: bool, detail=""):
        (passed if cond else failed).append(name if cond else f"{name}: {detail}")

    try:
        _wait_health(base)
        status, reg = _request(
            base, "POST", "/api/v1/auth/register",
            body={"username": "seedadmin", "password": "seed-pass-123"},
        )
        check("注册管理员", status == 200, reg)
        admin = reg["access_token"]
        status, reg2 = _request(
            base, "POST", "/api/v1/auth/register",
            body={"username": "seeduser", "password": "seed-pass-456"},
        )
        check("注册普通用户", status == 200, reg2)
        user = reg2["access_token"]

        status, conn = _request(
            base, "POST", "/api/v1/seeds/connections", admin,
            {
                "kind": "qbittorrent", "name": "测试 QB",
                "base_url": f"http://127.0.0.1:{qb_port}",
                "username": "admin", "secret": "qb-pass", "auth_mode": "password",
                "verify_tls": True, "enabled": True,
            },
        )
        check("创建 QB 连接", status == 201, conn)
        qb_id = conn["id"] if isinstance(conn, dict) else 0
        status, test = _request(base, "POST", f"/api/v1/seeds/connections/{qb_id}/test", admin)
        check("QB 连接测试", status == 200 and test.get("version") == "v4.6.7", test)
        # 保存连接会丢弃该连接的客户端；下一次业务请求必须能自动重新登录。
        # 如果 _json/_post_form 绕过 _api（直接用 _request），这里会 403。
        status, saved = _request(
            base, "PATCH", f"/api/v1/seeds/connections/{qb_id}", admin, {"name": "测试 QB"}
        )
        check("保存 QB 连接", status == 200, saved)
        status, summary = _request(base, "GET", "/api/v1/seeds/qb/summary", admin)
        check("保存连接后 QB 自动重新登录", status == 200 and summary.get("downloading") == 1, summary)

        status, mp_conn = _request(
            base, "POST", "/api/v1/seeds/connections", admin,
            {
                "kind": "moviepilot", "name": "测试 MP",
                "base_url": f"http://127.0.0.1:{mp_port}",
                "secret": "test-token-1234567890", "auth_mode": "api_token",
                "verify_tls": True, "enabled": True,
            },
        )
        check("创建 MP 连接", status == 201, mp_conn)
        mp_id = mp_conn["id"] if isinstance(mp_conn, dict) else 0
        status, test = _request(base, "POST", f"/api/v1/seeds/connections/{mp_id}/test", admin)
        check("MP 连接测试", status == 200 and test.get("version") == "v3.1.4", test)
        status, overview = _request(base, "GET", "/api/v1/seeds/overview", admin)
        storage = (overview.get("mp") or {}).get("storage") or {}
        check(
            "概览使用 MP 真实存储统计",
            status == 200 and storage.get("total") == 8880464400384
            and storage.get("used") == 2870252269568,
            overview,
        )

        status, summary = _request(base, "GET", "/api/v1/seeds/qb/summary", user)
        check("普通用户读 QB 摘要", status == 200 and summary.get("downloading") == 1, summary)
        status, traffic = _request(base, "GET", "/api/v1/seeds/qb/traffic", user)
        check(
            "普通用户读流量曲线",
            status == 200 and bool(traffic.get("items")) and traffic.get("interval") == 1.5,
            traffic,
        )
        status, torrents = _request(base, "GET", "/api/v1/seeds/qb/torrents", user)
        check("普通用户读种子列表", status == 200 and torrents.get("total") == 2, torrents)
        check("种子列表不含 tracker passkey", "SECRET" not in json.dumps(torrents, ensure_ascii=False), torrents)
        by_hash = {x.get("hash"): x for x in torrents.get("items", [])}
        status, tag_options = _request(base, "GET", "/api/v1/seeds/qb/tags", user)
        check(
            "标签筛选隐藏零使用标签",
            status == 200
            and "空标签" not in (tag_options or [])
            and "测试" in (tag_options or []),
            tag_options,
        )
        check(
            "qB 任务按 hash 补 MP 海报",
            by_hash.get("aaa111", {}).get("media_poster") == "https://img.example/poster.jpg"
            and by_hash.get("aaa111", {}).get("media_title") == "示例电影"
            and by_hash.get("aaa111", {}).get("media_site") == "馒头",
            by_hash.get("aaa111"),
        )
        check(
            "没有 MP 历史的任务不伪造封面",
            not by_hash.get("bbb222", {}).get("media_poster"),
            by_hash.get("bbb222"),
        )
        status, sorted_torrents = _request(base, "GET", "/api/v1/seeds/qb/torrents?sort=name", user)
        names = [t.get("name") for t in sorted_torrents.get("items", [])]
        check("按名称排序", status == 200 and names == sorted(names), names)
        status, asc = _request(base, "GET", "/api/v1/seeds/qb/torrents?sort=size", user)
        asc_hashes = [t.get("hash") for t in asc.get("items", [])]
        status2, desc = _request(base, "GET", "/api/v1/seeds/qb/torrents?sort=-size", user)
        desc_hashes = [t.get("hash") for t in desc.get("items", [])]
        check(
            "按大小正序/倒序",
            status == 200 and status2 == 200
            and asc_hashes == ["bbb222", "aaa111"]
            and desc_hashes == ["aaa111", "bbb222"],
            (asc_hashes, desc_hashes),
        )
        status, detail = _request(base, "GET", "/api/v1/seeds/qb/torrents/aaa111", user)
        check("普通用户读种子详情", status == 200 and detail.get("files"), detail)
        check("种子详情不含 tracker passkey", "SECRET" not in json.dumps(detail, ensure_ascii=False), detail)
        status, _ = _request(
            base, "POST", "/api/v1/seeds/qb/torrents/aaa111/action", user, {"action": "pause"}
        )
        check("普通用户不能操作种子", status == 403, status)
        status, _ = _request(
            base, "POST", "/api/v1/seeds/qb/torrents/aaa111/delete", admin,
            {"password": "seed-pass-123", "delete_files": False, "confirm": False},
        )
        check("删除需先确认", status == 400, status)
        status, _ = _request(
            base, "POST", "/api/v1/seeds/qb/torrents/aaa111/delete", admin,
            {"password": "wrong", "delete_files": False, "confirm": True},
        )
        check("删除密码错误被拒", status == 403, status)
        status, _ = _request(
            base, "POST", "/api/v1/seeds/qb/torrents/aaa111/delete", admin,
            {"password": "seed-pass-123", "delete_files": True, "confirm": True},
        )
        check("管理员密码删除成功", status == 200 and FakeQbState.deleted is not None, status)
        status, _ = _request(
            base, "POST", "/api/v1/seeds/qb/torrents", admin,
            {"url": "magnet:?xt=urn:btih:test", "category": "电影", "paused": True},
        )
        check("管理员添加种子", status == 200 and FakeQbState.added, status)
        status, nonbrush_convert = _request(
            base, "POST", "/api/v1/seeds/qb/torrents/bbb222/convert", admin, {"target": "movie"}
        )
        check(
            "非刷流种子不能转媒体",
            status == 400 and "刷流" in str(nonbrush_convert.get("detail") or ""),
            nonbrush_convert,
        )
        # 转媒体只接受带刷流标签的种子；测试前给 bbb222 打上刷流任务标签。
        next(x for x in FakeQbState.torrents if x.get("hash") == "bbb222")["tags"] = "刷流-测试"
        status, denied_convert = _request(
            base, "POST", "/api/v1/seeds/qb/torrents/bbb222/convert", user, {"target": "movie"}
        )
        check("普通用户不能转媒体", status == 403, denied_convert)
        status, incomplete_convert = _request(
            base, "POST", "/api/v1/seeds/qb/torrents/aaa111/convert", admin, {"target": "tv"}
        )
        check("未完成种子不能转媒体", status == 400, incomplete_convert)
        status, converted = _request(
            base, "POST", "/api/v1/seeds/qb/torrents/bbb222/convert", admin, {"target": "movie"}
        )
        converted_row = next((x for x in FakeQbState.torrents if x.get("hash") == "bbb222"), {})
        converted_tags = {x.strip() for x in str(converted_row.get("tags") or "").split(",") if x.strip()}
        check(
            "转媒体改保存位置并重置标签分类",
            status == 200
            and FakeQbState.last_location == "/media/下载/电影"
            and str(converted_row.get("save_path")) == "/media/下载/电影"
            and converted_row.get("category") == ""
            and converted_tags == {"MOVIEPILOT", "转媒体"},
            (converted, converted_row, FakeQbState.last_location),
        )
        # 真实 MP 整理成功后不一定追加 已整理；worker 应只凭 MP 整理历史
        # （status=true，download_hash 为空时按 src 路径）确认并改标签。
        done = False
        for _ in range(20):
            time.sleep(0.5)
            if "已转媒体" in str(converted_row.get("tags") or ""):
                done = True
                break
        check(
            "转媒体 worker 确认整理成功并改标签",
            done and "转媒体" not in {x.strip() for x in str(converted_row.get("tags") or "").split(",")},
            converted_row.get("tags"),
        )
        status, scan_pending = _request(base, "POST", "/api/v1/seeds/transfer/scan", admin)
        check(
            "转媒体完成后扫描无待处理任务",
            status == 200 and scan_pending.get("pending", 0) == 0,
            scan_pending,
        )
        status, transfer_list = _request(base, "GET", "/api/v1/seeds/qb/torrents", admin)
        transfer_row = next(
            (x for x in transfer_list.get("items", []) if x.get("hash") == "bbb222"), {}
        )
        check(
            "转媒体后从 MP 整理历史补封面",
            status == 200 and transfer_row.get("media_poster") == "https://img.example/transferred.jpg",
            transfer_row,
        )
        status, detail_resp = _request(
            base, "GET", "/api/v1/seeds/qb/torrents/bbb222", admin
        )
        media = detail_resp.get("media") or {}
        check(
            "种子详情返回媒体标题/封面/宽幅背景",
            status == 200
            and media.get("title") == "示例电影"
            and "/api/v1/seeds/cover?url=" in str(media.get("poster"))
            and "w500" in str(media.get("poster"))
            and media.get("backdrops")
            and "w1280" in str(media.get("backdrops", [""])[0]),
            media,
        )
        FakeQbState.actions.clear()
        status, bulk_result = _request(
            base, "POST", "/api/v1/seeds/qb/torrents/bulk/action", admin,
            {"hashes": ["aaa111", "bbb222"], "action": "pause"},
        )
        check(
            "批量暂停种子",
            status == 200 and "pause" in FakeQbState.actions,
            (status, bulk_result, FakeQbState.actions),
        )
        status, bulk_result = _request(
            base, "POST", "/api/v1/seeds/qb/torrents/bulk/delete", admin,
            {"hashes": ["bbb222"], "password": "seed-pass-123", "delete_files": False, "confirm": True},
        )
        check("批量删除种子", status == 200, (status, bulk_result))

        status, subs = _request(base, "GET", "/api/v1/seeds/mp/subscriptions?type=all", user)
        check("订阅列表", status == 200 and len(subs.get("items", [])) == 3, subs)
        status, subs_tv = _request(base, "GET", "/api/v1/seeds/mp/subscriptions?type=tv", user)
        check("订阅按类型筛选", status == 200 and len(subs_tv.get("items", [])) == 1, subs_tv)
        status, sites = _request(base, "GET", "/api/v1/seeds/mp/sites", admin)
        check("站点列表含账号数据", status == 200 and sites[0].get("ratio") == 2.0, sites)
        status, sites_user = _request(base, "GET", "/api/v1/seeds/mp/sites", user)
        check("全部可见时普通用户可见站点账号数据", status == 200 and sites_user[0].get("ratio") == 2.0, sites_user)
        status, search = _request(base, "GET", "/api/v1/seeds/mp/search?q=盗梦", user)
        item = (search.get("items") or [{}])[0]
        check("资源搜索", status == 200 and item.get("title"), search)
        check(
            "搜索结果不含 passkey",
            "enclosure" not in item and "site_cookie" not in item and "site_ua" not in item,
            item,
        )
        check(
            "搜索结果页面地址中的 passkey 已脱敏",
            "SECRET" not in json.dumps(search, ensure_ascii=False),
            search,
        )
        check("普通用户搜索结果不带操作引用", not item.get("op_id"), item)
        status, admin_search = _request(base, "GET", "/api/v1/seeds/mp/search?q=盗梦", admin)
        admin_item = (admin_search.get("items") or [{}])[0]
        op_id = admin_item.get("op_id") or ""
        check("管理员搜索结果带操作引用", bool(op_id), admin_search)
        check(
            "管理员搜索结果同样不含站点凭据",
            "SECRET" not in json.dumps(admin_search, ensure_ascii=False),
            admin_search,
        )
        status, missing = _request(
            base, "POST", "/api/v1/seeds/mp/download", admin, {"op_id": "x" * 24}
        )
        check("过期操作引用返回 404", status == 404, missing)
        status, denied = _request(
            base, "POST", "/api/v1/seeds/mp/download", user, {"op_id": op_id}
        )
        check("普通用户不能从搜索添加下载", status in (401, 403), denied)
        status, download = _request(
            base, "POST", "/api/v1/seeds/mp/download", admin, {"op_id": op_id}
        )
        check(
            "从搜索添加下载",
            status == 200 and download.get("download_id") == "fake-dl-1",
            download,
        )
        sent_download = FakeMpState.last_download or {}
        check(
            "下载请求保留原始种子信息",
            (sent_download.get("torrent_in") or {}).get("enclosure", "").endswith("passkey=SECRET"),
            sent_download,
        )
        check(
            "下载请求补齐媒体身份",
            (sent_download.get("media_in") or {}).get("title") == "盗梦空间"
            and (sent_download.get("media_in") or {}).get("media_source") == "themoviedb"
            and (sent_download.get("media_in") or {}).get("media_id") == "27205",
            sent_download.get("media_in"),
        )
        status, subscribe = _request(
            base, "POST", "/api/v1/seeds/mp/subscribe", admin, {"op_id": op_id}
        )
        check(
            "从搜索添加订阅",
            status == 200 and subscribe.get("subscribe_id") == 99,
            subscribe,
        )
        sent_subscribe = FakeMpState.last_subscribe or {}
        check(
            "订阅请求字段正确",
            sent_subscribe.get("name") == "盗梦空间"
            and sent_subscribe.get("type") == "电影"
            and sent_subscribe.get("media_source") == "themoviedb"
            and sent_subscribe.get("media_id") == "27205",
            sent_subscribe,
        )
        check(
            "订阅/下载响应不回传站点凭据",
            "SECRET" not in json.dumps([download, subscribe], ensure_ascii=False),
            [download, subscribe],
        )
        status, media = _request(base, "GET", "/api/v1/seeds/mp/media?q=盗梦", user)
        check("影视搜索", status == 200 and media.get("items"), media)
        status, tlist = _request(
            base, "GET", "/api/v1/seeds/mp/torrents?media_id=27205&media_source=tmdb", user
        )
        check("按媒体搜种子", status == 200 and tlist.get("items"), tlist)
        status, discover = _request(base, "GET", "/api/v1/seeds/mp/discover?source=tmdb_movies", user)
        check("影视探索", status == 200 and discover.get("items"), discover)
        status, recommend = _request(base, "GET", "/api/v1/seeds/mp/recommend", user)
        check("影视推荐", status == 200 and recommend.get("items"), recommend)
        status, ani = _request(
            base, "GET",
            "/api/v1/seeds/mp/discover?source=anilist&sort=TRENDING_DESC&format=TV&genre=Action&page=1&count=5",
            user,
        )
        check(
            "探索 AniList 来源与筛选参数",
            status == 200
            and ani.get("items")
            and FakeMpState.last_discover
            and FakeMpState.last_discover[0] == "/api/v1/anilist/discover"
            and FakeMpState.last_discover[1].get("sort") == ["TRENDING_DESC"],
            ani,
        )
        status, douban_music = _request(
            base, "GET",
            "/api/v1/seeds/mp/discover?source=douban_music&tags=%E6%B5%81%E8%A1%8C,%E5%8D%8E%E8%AF%AD&douban_sort=U&with_cover=all&page=1&count=5",
            user,
        )
        check(
            "探索豆瓣音乐复用 music/explore 且封面参数转布尔",
            status == 200
            and douban_music.get("items")
            and FakeMpState.last_discover
            and FakeMpState.last_discover[0] == "/api/v1/music/explore"
            and FakeMpState.last_discover[1].get("media_source") == ["doubanmusic"]
            and str(FakeMpState.last_discover[1].get("with_cover", [""])[0]).lower() == "false",
            douban_music,
        )
        status, musicbrainz = _request(
            base, "GET",
            "/api/v1/seeds/mp/discover?source=musicbrainz&mode=chart&entity=album&range_name=this_month&sort_by=listen_count.desc&with_cover=with_cover&page=1&count=5",
            user,
        )
        check(
            "探索 MusicBrainz 筛选与封面参数",
            status == 200
            and musicbrainz.get("items")
            and FakeMpState.last_discover
            and FakeMpState.last_discover[0] == "/api/v1/music/explore"
            and FakeMpState.last_discover[1].get("media_source") == ["musicbrainz"]
            and str(FakeMpState.last_discover[1].get("with_cover", [""])[0]).lower() == "true",
            musicbrainz,
        )
        status, section = _request(
            base, "GET",
            "/api/v1/seeds/mp/recommend?source=recommend/tmdb_trending&page=1&count=5",
            user,
        )
        check(
            "推荐页板块走 MP recommend 板块路径",
            status == 200
            and section.get("items")
            and FakeMpState.last_recommend
            and FakeMpState.last_recommend[0] == "/api/v1/recommend/tmdb_trending",
            section,
        )
        status, brush = _request(base, "GET", "/api/v1/seeds/mp/brush", user)
        check("刷流只读", status == 200 and brush.get("available") and brush.get("tasks"), brush)

        # 事件：先让 worker 建立水位，再追加新完成种子/新通知
        time.sleep(2.5)
        FakeQbState.torrents.append({
            "hash": "ccc333", "name": "刚完成的种子", "state": "uploading",
            "progress": 1, "size": 1024, "total_size": 1024, "dlspeed": 0, "upspeed": 0,
            "eta": 0, "ratio": 0, "category": "电影", "tags": "", "added_on": 1200,
            "completion_on": int(time.time()), "save_path": "/downloads", "content_path": "",
            "tracker": "", "num_seeds": 0, "num_leechs": 0, "amount_left": 0,
        })
        FakeQbState.torrents.append({
            "hash": "ddd444", "name": "刷流完成的种子", "state": "uploading",
            "progress": 1, "size": 2048, "total_size": 2048, "dlspeed": 0, "upspeed": 0,
            "eta": 0, "ratio": 0, "category": "刷流", "tags": "刷流-憨憨",
            "added_on": 1300, "completion_on": int(time.time()) + 1, "save_path": "/downloads",
            "content_path": "", "tracker": "", "num_seeds": 0, "num_leechs": 0, "amount_left": 0,
        })
        FakeMpState.notifications.append({
            "id": 2, "mtype": "订阅", "ctype": "subscribeComplete",
            "title": "订阅完成", "text": "示例剧集已全部下载完成",
            "reg_time": "2026-10-21 11:00:00",
        })
        FakeMpState.notifications.append({
            "id": 3, "mtype": "站点", "ctype": "",
            "title": "【站点自动签到】",
            "text": "本次签到数量: 2\n登录或访问失败: 1\n【憨憨】登录失败",
            "reg_time": "2026-10-21 11:01:00",
        })
        time.sleep(5)
        status, msgs = _request(base, "GET", "/api/v1/messages?page_size=50&order=time", admin)
        titles = [m.get("title") for m in (msgs.get("items") or [])]
        check("下载完成事件进消息中心", "种子下载完成" in titles, titles)
        download_msgs = [m for m in (msgs.get("items") or []) if m.get("title") == "种子下载完成"]
        check("刷流种子不发完成通知", len(download_msgs) == 1, download_msgs)
        check("订阅完成事件进消息中心", "订阅完成" in titles, titles)
        check("签到失败事件进消息中心", "站点签到失败" in titles, titles)

        status, admin_sources = _request(base, "GET", "/api/v1/sources", admin)
        status, user_sources = _request(base, "GET", "/api/v1/sources", user)
        check("管理员可见系统来源", any(s.get("is_system") for s in (admin_sources or [])), admin_sources)
        check("普通用户看不到系统来源", not any(s.get("is_system") for s in (user_sources or [])), user_sources)

        status, _ = _request(base, "PATCH", "/api/v1/settings/system-sources", admin, {"hidden": True})
        status, admin_sources2 = _request(base, "GET", "/api/v1/sources", admin)
        check("隐藏系统来源开关生效", status == 200 and not any(s.get("is_system") for s in (admin_sources2 or [])), admin_sources2)

        status, _ = _request(base, "PATCH", "/api/v1/seeds/settings", admin, {"visibility": "admin_only"})
        status, st = _request(base, "GET", "/api/v1/seeds/status", user)
        check("仅管理员可见范围", status == 200 and st.get("visible") is False, st)
        status, _ = _request(base, "GET", "/api/v1/seeds/qb/torrents", user)
        check("不可见时普通用户读接口 403", status == 403, status)
        status, _ = _request(base, "PATCH", "/api/v1/seeds/settings", admin, {"visibility": "standard"})
        status, sites_std = _request(base, "GET", "/api/v1/seeds/mp/sites", user)
        check("常规可见隐藏站点账号数据", status == 200 and "ratio" not in sites_std[0], sites_std)
        status, _ = _request(base, "PATCH", "/api/v1/seeds/settings", admin, {"visibility": "all"})

    except Exception as exc:
        failed.append(f"异常：{type(exc).__name__}: {exc}")
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        log_file.close()
        qb_server.shutdown()
        mp_server.shutdown()
        if failed:
            print("--- backend log tail ---")
            try:
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                print("".join(lines[-40:]))
            except Exception:
                pass

    print(f"通过 {len(passed)} 项，失败 {len(failed)} 项")
    for name in passed:
        print(f"  OK  {name}")
    for name in failed:
        print(f"  FAIL {name}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
