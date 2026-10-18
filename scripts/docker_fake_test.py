"""容器监控/控制联调脚本：内置假 Docker Engine API（TCP），全链路验证，无需真实 Docker。

用法：
  cd backend && .venv/Scripts/python scripts/docker_fake_test.py

覆盖：
  - docker_service 直连：available / version / 容器列表+stats / 日志解复用 / df / 事件流 / 写操作映射
  - 监控总开关（默认关）：关闭时 /docker/* 全部 503 或 disabled 形状、事件线程不启动；
    开启后只读接口恢复，事件线程运行
  - 控制开关（默认关）：关闭时写接口 403；开启后 start/stop/restart/remove/pull 全链路
    （含 304 已是目标状态、404 容器不存在、409 运行中删除冲突）
  - SSE：docker.event 只投递管理员（audience=admins 通道）
Unix Socket 通道与 TCP 共用同一套代码路径（仅 connect 一行之差），Windows 上用本脚本回归即可。
"""

import http.client
import http.server
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

HOST, PORT = "127.0.0.1", 18799
CID_A = "a" * 64
CID_B = "b" * 64

# 可变假容器状态：写操作直接改这里，list_containers 立即反映
CONTAINERS = [
    {
        "Id": CID_A,
        "Names": ["/ihub-backend"],
        "Image": "ihub-backend:latest",
        "State": "running",
        "Status": "Up 2 hours",
        "Created": int(time.time()) - 7200,
        "Ports": [{"IP": "0.0.0.0", "PrivatePort": 8000, "PublicPort": 18766, "Type": "tcp"}],
        "Labels": {"com.docker.compose.project": "ihub"},
    },
    {
        "Id": CID_B,
        "Names": ["/stopped-one"],
        "Image": "hello-world:latest",
        "State": "exited",
        "Status": "Exited (0) 3 days ago",
        "Created": int(time.time()) - 300000,
        "Ports": [],
        "Labels": {},
    },
]

STATS = {
    "cpu_stats": {
        "cpu_usage": {"total_usage": 2_000_000_000},
        "system_cpu_usage": 10_000_000_000,
        "online_cpus": 4,
    },
    "precpu_stats": {"cpu_usage": {"total_usage": 1_500_000_000}, "system_cpu_usage": 9_000_000_000},
    "memory_stats": {
        "usage": 300 * 1048576,
        "limit": 8 * 1024 * 1048576,
        "stats": {"inactive_file": 50 * 1048576},
    },
}


def _frame(text: str) -> bytes:
    payload = text.encode()
    return b"\x01" + b"\x00" * 3 + len(payload).to_bytes(4, "big") + payload


class FakeDocker(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静默访问日志
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _empty(self, status=204):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _error(self, status, message):
        self._json({"message": message}, status)

    def _find(self, cid: str):
        for c in CONTAINERS:
            if c["Id"].startswith(cid):
                return c
        return None

    def do_GET(self):
        path = self.path
        if path.startswith("/_ping"):
            body = b"OK"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path.startswith("/version"):
            self._json(
                {"Version": "24.0.7", "ApiVersion": "1.43", "Os": "linux", "Arch": "x86_64", "Name": "fake-nas"}
            )
        elif path.startswith("/containers/json"):
            self._json(CONTAINERS)
        elif "/stats" in path:
            self._json(STATS)
        elif f"/containers/{CID_A}/json" in path:
            c = self._find(CID_A)
            self._json(
                {
                    "Id": CID_A,
                    "Name": "/ihub-backend",
                    "Config": {"Tty": False, "Image": c["Image"]},
                    "State": {"Status": c["State"]},
                }
            )
        elif "/logs" in path:
            # 帧 1 带 ANSI 颜色转义序列：验证 container_logs 会剥离（网页端渲染为乱码）
            body = _frame("\x1b[32mINFO:\x1b[0m 2026-09-17 10:00:00 first line\n") + _frame("second line 中文\n")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path.startswith("/system/df"):
            self._json(
                {
                    "Images": [{"Size": 100 * 1048576}, {"Size": 200 * 1048576}],
                    "Containers": [{"Size": 5 * 1048576}],
                    "Volumes": [{"UsageData": {"Size": 1024 * 1048576}}],
                    "BuildCache": [{"Size": 30 * 1048576}],
                }
            )
        elif path.startswith("/events"):
            # 每次连接推一条容器事件后保持片刻（工作线程断线 5s 后会重连）
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            ev = {
                "Type": "container",
                "Action": "start",
                "id": CID_A,
                "Actor": {"Attributes": {"name": "ihub-backend"}},
            }
            try:
                self.wfile.write((json.dumps(ev) + "\n").encode())
                self.wfile.flush()
                time.sleep(3)
            except OSError:
                pass
        else:
            self.send_error(404)

    def _container_action(self, action: str):
        cid = self.path.split("/")[2].split("?")[0]
        c = self._find(cid)
        if c is None:
            return self._error(404, f"No such container: {cid}")
        if action in ("stop", "restart") and "?t=" in self.path:
            pass  # 优雅退出超时参数：假服务直接忽略
        if action == "start":
            if c["State"] == "running":
                return self._empty(304)
            c["State"] = "running"
            c["Status"] = "Up 0 seconds"
            return self._empty(204)
        if action == "stop":
            if c["State"] != "running":
                return self._empty(304)
            c["State"] = "exited"
            c["Status"] = "Exited (0) just now"
            return self._empty(204)
        # restart：stopped 容器也会被拉起
        c["State"] = "running"
        c["Status"] = "Up 0 seconds"
        return self._empty(204)

    def do_POST(self):
        path = self.path
        m = re.match(r"^/containers/([A-Za-z0-9]+)/(start|stop|restart)", path)
        if m:
            return self._container_action(m.group(2))
        if path.startswith("/images/create"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
            name = (q.get("fromImage") or [""])[0]
            tag = (q.get("tag") or ["latest"])[0]
            if not name:
                return self._error(400, "fromImage required")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            for line in (
                {"status": f"Pulling from library/{name}"},
                {"status": "Download complete", "id": "layer1"},
                {"status": f"Status: Downloaded newer image for {name}:{tag}"},
            ):
                try:
                    self.wfile.write((json.dumps(line) + "\n").encode())
                    self.wfile.flush()
                except OSError:
                    return
            return
        self.send_error(404)

    def do_DELETE(self):
        m = re.match(r"^/containers/([A-Za-z0-9]+)", self.path)
        if not m:
            return self.send_error(404)
        c = self._find(m.group(1))
        if c is None:
            return self._error(404, f"No such container: {m.group(1)}")
        if c["State"] == "running":
            return self._error(409, "You cannot remove a running container")
        CONTAINERS.remove(c)
        return self._empty(204)


def api(method: str, path: str, token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(f"http://{HOST}:{PORT}{path}", method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace"))
        except ValueError:
            return e.code, {}


def main() -> int:
    server = http.server.ThreadingHTTPServer((HOST, 0), FakeDocker)
    fake_port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ["IHUB_DOCKER_HOST"] = f"tcp://{HOST}:{fake_port}"
    print(f"[1] 假 Docker API：tcp://{HOST}:{fake_port}")

    # ---- 直连服务层（不受 API 门禁影响；写映射也在此验证） ----
    from app.services import docker_service as docker

    ok, err = docker.available()
    assert ok, f"available 失败：{err}"
    assert docker.version_info()["version"] == "24.0.7"
    items = docker.list_containers()
    assert len(items) == 2 and items[0]["state"] == "running"
    running = items[0]
    # cpu: delta 0.5e9 / 1.0e9 * 4 核 = 200%
    assert running.get("cpu_percent") == 200.0, running.get("cpu_percent")
    # mem: (300-50)MB used, 上限 8GB
    assert running.get("mem_used_mb") == 250.0 and running.get("mem_limit_mb") == 8192.0
    assert running["ports"] == ["18766→8000/tcp"] and running["project"] == "ihub"
    logs = docker.container_logs(CID_A, tail=100)
    assert "first line" in logs["logs"] and "中文" in logs["logs"], logs["logs"]
    # ANSI 颜色转义序列必须被剥离（\x1b[32mINFO:\x1b[0m → INFO:），否则网页日志是乱码
    assert "\x1b" not in logs["logs"] and "INFO:" in logs["logs"], logs["logs"]
    df = docker.system_df()
    assert df["images"]["count"] == 2 and df["volumes"]["size_mb"] == 1024.0
    # 写操作服务层：304 / 404 / 409 映射
    docker.invalidate_list_cache()
    out = docker.container_action(CID_A, "start")
    assert out["ok"] and out["message"] == "容器已在运行"  # 304
    try:
        docker.container_action("fff" + "0" * 9, "start")
        raise AssertionError("404 未抛出")
    except docker.DockerError as exc:
        assert exc.status == 404 and "不存在" in exc.message
    try:
        docker.remove_container(CID_A)  # 运行中删除 → 409
        raise AssertionError("409 未抛出")
    except docker.DockerError as exc:
        assert exc.status == 409 and "冲突" in exc.message
    evs: list[dict] = []
    stop = threading.Event()
    t = threading.Thread(target=docker.stream_events, args=(stop, evs.append), daemon=True)
    t.start()
    for _ in range(40):
        if evs:
            break
        time.sleep(0.2)
    stop.set()
    assert evs and evs[0]["name"] == "ihub-backend" and evs[0]["action"] == "start"
    print("[1] 服务层直连（列表/统计/日志/df/事件流/写映射）通过")

    # ---- 起后端：门禁与写链路 ----
    data_dir = tempfile.mkdtemp(prefix="ihub-docker-test-")
    os.environ["IHUB_DATA_DIR"] = data_dir
    os.environ["IHUB_SECRET_KEY"] = "dockertest"

    import uvicorn

    from app.main import app

    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning", proxy_headers=False)
    srv = uvicorn.Server(config)
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://{HOST}:{PORT}/api/health", timeout=2) as r:
                if r.status == 200:
                    break
        except OSError:
            time.sleep(0.3)
    print("[2] 后端已启动（监控/控制开关均默认关）")

    _, admin = api("POST", "/api/v1/auth/register", body={"username": "docker_admin", "password": "admin123"})
    _, plain = api("POST", "/api/v1/auth/register", body={"username": "docker_user", "password": "user12345"})
    at, pt = admin["access_token"], plain["access_token"]

    # ---- 监控总开关：默认关 → 全部 503 / disabled，事件线程未启动 ----
    from app.services import docker_service as ds

    assert ds._worker is None, "监控关闭时事件线程不应启动"
    status, out = api("GET", "/api/v1/docker/status", token=at)
    assert status == 200 and out["available"] is False and out["disabled"] is True
    status, out = api("GET", "/api/v1/docker/containers", token=at)
    assert status == 503 and "未开启" in out.get("detail", ""), (status, out)
    status, _ = api("GET", "/api/v1/docker/df", token=at)
    assert status == 503
    status, _ = api("GET", f"/api/v1/docker/containers/{CID_A}/logs", token=at)
    assert status == 503
    status, _ = api("POST", f"/api/v1/docker/containers/{CID_A}/stop", token=at)
    assert status == 503, f"监控关闭时写操作应为 503，实际 {status}"
    status, _ = api("POST", f"/api/v1/docker/containers/{CID_A}/stop")  # 匿名
    assert status == 401
    status, _ = api("POST", f"/api/v1/docker/containers/{CID_A}/stop", token=pt)
    assert status == 403
    status, body = api("GET", "/api/v1/settings/docker", token=at)
    assert status == 200 and isinstance(body, dict)
    print("[2] 监控总开关默认关：503/disabled 拦截 + 匿名 401 + 普通用户 403 通过")

    # ---- 开启监控：只读接口恢复，事件线程启动 ----
    status, out = api("PATCH", "/api/v1/settings/docker", token=at, body={"monitor_enabled": True})
    assert status == 200 and out["monitor_enabled"] is True
    status, out = api("GET", "/api/v1/docker/status", token=at)
    assert status == 200 and out["available"] is True and out["disabled"] is False
    assert out["control_enabled"] is False
    status, out = api("GET", "/api/v1/docker/containers", token=at)
    assert status == 200 and out["summary"]["total"] == 2
    status, _ = api("GET", "/api/v1/docker/df", token=at)
    assert status == 200
    assert ds._worker is not None and ds._worker.is_alive(), "开启监控后事件线程应启动"
    print("[2] 开启监控：只读接口恢复 + 事件线程启动 通过")

    # ---- 控制开关：默认关 → 写接口 403 ----
    status, out = api("POST", f"/api/v1/docker/containers/{CID_A}/stop", token=at)
    assert status == 403 and "未开启" in out.get("detail", ""), (status, out)
    status, out = api("POST", "/api/v1/docker/images/pull", token=at, body={"image": "nginx"})
    assert status == 403
    print("[2] 控制开关默认关：写接口 403 通过")

    # ---- 开启控制：写链路全矩阵 ----
    status, out = api("PATCH", "/api/v1/settings/docker", token=at, body={"control_enabled": True})
    assert status == 200 and out["control_enabled"] is True
    status, out = api("GET", "/api/v1/docker/status", token=at)
    assert out["control_enabled"] is True

    status, out = api("POST", f"/api/v1/docker/containers/{CID_A}/stop?t=5", token=at)
    assert status == 200 and out["message"] == "已停止", (status, out)
    status, out = api("GET", "/api/v1/docker/containers", token=at)
    states = {i["id"]: i["state"] for i in out["items"]}
    assert states[CID_A[:12]] == "exited", f"停止后列表未反映：{states}"  # 缓存已失效，立即反映

    status, out = api("POST", f"/api/v1/docker/containers/{CID_A}/start", token=at)
    assert status == 200 and out["message"] == "已启动"
    status, out = api("POST", f"/api/v1/docker/containers/{CID_A}/start", token=at)
    assert status == 200 and out["message"] == "容器已在运行"  # 304 分支
    status, out = api("POST", f"/api/v1/docker/containers/{CID_A}/restart?t=5", token=at)
    assert status == 200 and out["message"] == "已重启"

    status, out = api("POST", "/api/v1/docker/containers/fff000111222/start", token=at)
    assert status == 404 and "不存在" in out.get("detail", ""), (status, out)

    status, out = api("DELETE", f"/api/v1/docker/containers/{CID_A}", token=at)
    assert status == 409 and "冲突" in out.get("detail", ""), (status, out)  # 运行中删除
    status, out = api("DELETE", f"/api/v1/docker/containers/{CID_B}", token=at)
    assert status == 200 and out["message"] == "容器已删除", (status, out)
    status, out = api("DELETE", f"/api/v1/docker/containers/{CID_B}", token=at)
    assert status == 404
    status, out = api("GET", "/api/v1/docker/containers", token=at)
    assert out["summary"]["total"] == 1

    status, out = api("POST", "/api/v1/docker/images/pull", token=at, body={"image": "nginx"})
    assert status == 200 and "重建容器" in out["message"], (status, out)
    status, out = api("POST", "/api/v1/docker/images/pull", token=at, body={"image": "nginx:1.25"})
    assert status == 200
    status, out = api("POST", "/api/v1/docker/images/pull", token=at, body={"image": "bad name!"})
    assert status == 400, (status, out)
    print("[2] 控制开关开启：stop/start/restart/remove/pull 成功 + 304/404/409 分支全部通过")

    # SSE：docker.event 只投递管理员（事件流断线重连周期 ~5s，给足等待窗口）
    conn = http.client.HTTPConnection(HOST, PORT, timeout=30)
    conn.request("GET", "/api/v1/events", headers={"Authorization": f"Bearer {at}"})
    resp = conn.getresponse()
    got = None
    deadline = time.time() + 20
    while time.time() < deadline:
        line = resp.readline()
        if not line:
            break
        text = line.decode("utf-8", "replace").strip()
        if text.startswith("data:"):
            evt = json.loads(text[5:].strip())
            if evt.get("type") == "docker.event":
                got = evt
                break
    conn.close()
    assert got, "管理员 SSE 未收到 docker.event"
    assert got.get("audience") == "admins" and got.get("name") == "ihub-backend"
    print("[3] SSE docker.event 仅投递管理员：通过")

    # ---- 再关掉监控：恢复 503，事件线程同步停止 ----
    status, out = api("PATCH", "/api/v1/settings/docker", token=at, body={"monitor_enabled": False})
    assert status == 200 and out["monitor_enabled"] is False
    status, out = api("GET", "/api/v1/docker/containers", token=at)
    assert status == 503
    status, out = api("GET", "/api/v1/docker/status", token=at)
    assert out["disabled"] is True
    for _ in range(20):
        if ds._worker is None:
            break
        time.sleep(0.1)
    assert ds._worker is None, "关闭监控后事件线程应停止"
    print("[4] 再次关闭监控：503 + 事件线程停止 通过")

    srv.should_exit = True
    server.shutdown()
    shutil.rmtree(data_dir, ignore_errors=True)
    print("\n全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
