"""Docker Engine API 客户端（容器监控 + 受控写操作）。

通过部署时挂载的 Docker Socket（默认 /var/run/docker.sock，可用 IHUB_DOCKER_HOST 覆盖，
支持 unix:// 与 tcp://，后者用于 docker-socket-proxy 等受限网关）访问宿主机 Docker。
只读监控：容器列表+资源占用、日志、磁盘占用、事件流；
写操作（启停/重启/删除/拉镜像）由 API 层的「容器监控 + 容器控制」双开关门禁约束（均默认关）。
出站走标准库 http.client（项目惯例：venv 不引 httpx，也不引 docker SDK）。
"""

import concurrent.futures
import http.client
import json
import logging
import os
import re
import socket
import threading
import time
import urllib.parse
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DEFAULT_SOCKET_PATH = "/var/run/docker.sock"

# 镜像拉取可能很慢（大镜像 + 家宽），给足超时；nginx 反代的读超时可能更短，超长拉取会断流报错
_PULL_TIMEOUT = 600.0

# 容器列表短缓存：4 秒内的重复请求直接复用（页面轮询/手动刷新叠加时避免反复全量采样）
_LIST_CACHE_TTL = 4.0

# 网速采样的上次累计值（cid -> (时间戳, rx, tx)）；容器重启计数器归零由 max(delta,0) 兜底
_NET_PREV: dict[str, tuple[float, int, int]] = {}
_NET_LOCK = threading.Lock()
_LIST_CACHE_LOCK = threading.Lock()
_LIST_CACHE: list = [0.0, None]  # [缓存时间, 容器列表或 None]


class DockerUnavailable(Exception):
    """Docker 不可达（socket 未挂载 / 引擎未运行 / 响应异常）。"""


def docker_host() -> str:
    """Docker API 地址：unix:///path/to.sock 或 tcp://host:port。"""
    return os.getenv("IHUB_DOCKER_HOST", f"unix://{DEFAULT_SOCKET_PATH}").strip()


def host_display() -> str:
    return docker_host()


class _UnixHTTPConnection(http.client.HTTPConnection):
    """标准库未内置的 Unix Socket HTTP 连接（Docker API 的默认通道）。"""

    def __init__(self, path: str, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self._unix_path = path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._unix_path)
        self.sock = sock


def _connect(timeout: float) -> http.client.HTTPConnection:
    host = docker_host()
    if host.startswith("unix://"):
        return _UnixHTTPConnection(host.removeprefix("unix://"), timeout)
    parsed = urllib.parse.urlparse(host)
    if parsed.scheme != "tcp" or not parsed.hostname:
        raise DockerUnavailable(f"不支持的 IHUB_DOCKER_HOST：{host}")
    return http.client.HTTPConnection(parsed.hostname, parsed.port or 2375, timeout=timeout)


def _request(method: str, path: str, timeout: float = 8.0):
    """请求 Docker API 并解析 JSON；非 2xx 抛 DockerUnavailable。"""
    conn = _connect(timeout)
    try:
        conn.request(method, path)
        resp = conn.getresponse()
        data = resp.read()
        if resp.status >= 400:
            snippet = data[:200].decode("utf-8", "replace")
            raise DockerUnavailable(f"Docker API {resp.status}：{snippet}")
        if not data:
            return {}
        try:
            return json.loads(data.decode("utf-8", "replace"))
        except ValueError as exc:
            raise DockerUnavailable(f"Docker API 响应解析失败：{exc}")
    except OSError as exc:
        raise DockerUnavailable(f"无法连接 Docker（{docker_host()}）：{exc}")
    finally:
        conn.close()


def _request_bytes(method: str, path: str, timeout: float = 15.0, max_bytes: int = 2_000_000) -> bytes:
    conn = _connect(timeout)
    try:
        conn.request(method, path)
        resp = conn.getresponse()
        data = resp.read(max_bytes)
        if resp.status >= 400:
            raise DockerUnavailable(f"Docker API {resp.status}")
        return data
    except OSError as exc:
        raise DockerUnavailable(f"无法连接 Docker（{docker_host()}）：{exc}")
    finally:
        conn.close()


def available() -> tuple[bool, str]:
    """探测 Docker 是否可用；返回 (是否可用, 不可用原因)。"""
    host = docker_host()
    if host.startswith("unix://") and not os.path.exists(host.removeprefix("unix://")):
        return False, f"未找到 Docker Socket（{host.removeprefix('unix://')}）"
    try:
        # /_ping 返回纯文本 "OK"，不能用 _request（JSON 解析会失败）
        _request_bytes("GET", "/_ping", timeout=4.0)
        return True, ""
    except DockerUnavailable as exc:
        return False, str(exc)


def version_info() -> dict:
    try:
        info = _request("GET", "/version", timeout=5.0)
    except DockerUnavailable:
        return {}
    return {
        "version": info.get("Version", ""),
        "api_version": info.get("ApiVersion", ""),
        "os": info.get("Os", ""),
        "arch": info.get("Arch", ""),
        "hostname": info.get("Name", ""),
    }


def _fmt_ports(ports: list) -> list[str]:
    out: list[str] = []
    for p in ports:
        private = p.get("PrivatePort")
        public = p.get("PublicPort")
        ptype = p.get("Type") or "tcp"
        ip = p.get("IP") or ""
        if public:
            host_part = f"{ip}:{public}" if ip and ip != "0.0.0.0" else str(public)
            out.append(f"{host_part}→{private}/{ptype}")
        elif private:
            out.append(f"{private}/{ptype}")
    # 去重且保持顺序，最多展示 4 条避免过长
    seen: set[str] = set()
    uniq = [x for x in out if not (x in seen or seen.add(x))]
    return uniq[:4]


def _fill_stats(item: dict, cid: str) -> None:
    """补 CPU% / 内存占用（单次采样自带 precpu，可直接算差值；失败静默跳过）。"""
    try:
        st = _request("GET", f"/containers/{cid}/stats?stream=false", timeout=6.0)
    except (DockerUnavailable, OSError, ValueError):
        return
    if not isinstance(st, dict):
        # socket-proxy / 老版本引擎可能返回异常形状，整表 500 比缺两个指标严重得多
        return
    cpu = st.get("cpu_stats") or {}
    pre = st.get("precpu_stats") or {}
    cpu_delta = (cpu.get("cpu_usage") or {}).get("total_usage", 0) - (
        pre.get("cpu_usage") or {}
    ).get("total_usage", 0)
    sys_delta = (cpu.get("system_cpu_usage") or 0) - (pre.get("system_cpu_usage") or 0)
    online = cpu.get("online_cpus") or len((cpu.get("cpu_usage") or {}).get("percpu_usage") or []) or 1
    if sys_delta > 0 and cpu_delta >= 0:
        item["cpu_percent"] = round(cpu_delta / sys_delta * online * 100, 1)
    mem = st.get("memory_stats") or {}
    usage, limit = mem.get("usage"), mem.get("limit")
    if isinstance(usage, (int, float)) and isinstance(limit, (int, float)) and limit > 0:
        # cgroup v1 用 cache、v2 用 inactive_file 排除页缓存，与 docker stats 口径一致
        stats = mem.get("stats") or {}
        cache = stats.get("cache", stats.get("inactive_file", 0)) or 0
        used = max(usage - cache, 0)
        item["mem_used_mb"] = round(used / 1048576, 1)
        item["mem_limit_mb"] = round(limit / 1048576, 1)
        item["mem_percent"] = round(used / limit * 100, 1)
    # 网速：networks 里是启动以来累计字节，与本进程上次采样求区间均值
    nets = st.get("networks") or {}
    if isinstance(nets, dict) and nets:
        try:
            rx = sum(int(v.get("rx_bytes") or 0) for v in nets.values() if isinstance(v, dict))
            tx = sum(int(v.get("tx_bytes") or 0) for v in nets.values() if isinstance(v, dict))
            now = time.time()
            with _NET_LOCK:
                prev = _NET_PREV.get(cid)
                _NET_PREV[cid] = (now, rx, tx)
            if prev is not None and now - prev[0] > 0.5:
                item["net_rx_Bps"] = round(max(rx - prev[1], 0) / (now - prev[0]))
                item["net_tx_Bps"] = round(max(tx - prev[2], 0) / (now - prev[0]))
        except (TypeError, ValueError):
            pass


def count_containers() -> int:
    """只取容器数量：单次 /containers/json，不做逐容器 inspect/stats 采样。

    /stats 首页聚合专用——总览用户卡只需个数，逐容器采样（每台约 1-2s）会把
    仪表盘接口拖慢到秒级。
    """
    rows = _request("GET", "/containers/json?all=1", timeout=6.0)
    if not isinstance(rows, list):
        raise DockerUnavailable("Docker API 响应格式异常")
    return len(rows)


def list_containers() -> list[dict]:
    # 短缓存：页面 10s 轮询 + SSE 触发 + 手动刷新会叠加，4s 内直接复用上一次结果
    now = time.time()
    with _LIST_CACHE_LOCK:
        cached_ts, cached_items = _LIST_CACHE
        if cached_items is not None and now - cached_ts < _LIST_CACHE_TTL:
            return cached_items

    rows = _request("GET", "/containers/json?all=1", timeout=10.0)
    if not isinstance(rows, list):
        raise DockerUnavailable("Docker API 响应格式异常")
    items: list[dict] = []
    running: list[tuple[dict, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        names = [str(n).lstrip("/") for n in row.get("Names") or []]
        cid = str(row.get("Id") or "")
        state = str(row.get("State") or "unknown")
        created = row.get("Created")
        item = {
            "id": cid[:12],
            "name": names[0] if names else cid[:12],
            "image": str(row.get("Image") or ""),
            "state": state,
            "status": str(row.get("Status") or ""),
            "created_at": (
                datetime.fromtimestamp(int(created), tz=timezone.utc).isoformat()
                if isinstance(created, (int, float))
                else None
            ),
            "uptime_s": int(now - created) if state == "running" and isinstance(created, (int, float)) else None,
            "ports": _fmt_ports(row.get("Ports") or []),
            "project": str((row.get("Labels") or {}).get("com.docker.compose.project") or ""),
        }
        items.append(item)
        if state == "running":
            running.append((item, cid))

    # stats 接口每次采样约阻塞 1s：并发抓取把总耗时从 N 秒压到约 1 秒
    if running:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(running))) as pool:
            futures = [pool.submit(_fill_stats, item, cid) for item, cid in running]
            for f in futures:
                f.result()

    items.sort(key=lambda x: (x["state"] != "running", x["name"]))
    with _LIST_CACHE_LOCK:
        _LIST_CACHE[0] = now
        _LIST_CACHE[1] = items
    return items


def _demux_logs(raw: bytes) -> str:
    """非 TTY 日志是多路复用流：8 字节头（流类型 1B + 3B 填充 + 4B 大端长度）+ 载荷。"""
    out: list[str] = []
    i = 0
    while i + 8 <= len(raw):
        size = int.from_bytes(raw[i + 4 : i + 8], "big")
        if raw[i] not in (0, 1, 2):
            return raw.decode("utf-8", "replace")  # 头部不像复用帧：按 TTY 原文处理
        if i + 8 + size > len(raw):
            break  # 末尾帧被读取上限截断：丢弃残帧，保留此前完整内容（勿整段按 TTY 解码带出二进制头）
        out.append(raw[i + 8 : i + 8 + size].decode("utf-8", "replace"))
        i += 8 + size
    return "".join(out)


# ANSI 转义序列（uvicorn 等程序写进 stdout 的彩色控制符，如 \x1b[32m…\x1b[0m）。
# 终端里是颜色，网页上无法渲染就成了「[32mINFO:[0m」这类乱码，返回前端前统一剥离。
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"  # CSI：颜色 / 光标控制（\x1b[32m、\x1b[0m、\x1b[2J 等）
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?"  # OSC：窗口标题等（\x1b]0;title\x07）
    r"|\x1b[@-Z\\-_]"  # 其余单字符转义
)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def container_logs(cid: str, tail: int = 300) -> dict:
    tail = max(1, min(int(tail), 1000))
    info = _request("GET", f"/containers/{cid}/json", timeout=8.0)
    tty = bool((info.get("Config") or {}).get("Tty"))
    raw = _request_bytes(
        "GET", f"/containers/{cid}/logs?stdout=1&stderr=1&tail={tail}", timeout=15.0
    )
    text = raw.decode("utf-8", "replace") if tty else _demux_logs(raw)
    text = _strip_ansi(text)
    return {
        "id": str(info.get("Id") or cid)[:12],
        "name": str(info.get("Name") or "").lstrip("/"),
        "image": str((info.get("Config") or {}).get("Image") or ""),
        "state": str((info.get("State") or {}).get("Status") or ""),
        "logs": text[-200_000:],  # 保险：最多回传 20 万字符
        "truncated_head": len(text) > 200_000,
    }


def system_df() -> dict:
    data = _request("GET", "/system/df", timeout=30.0)

    def _sum(entries, size_key="Size") -> dict:
        total = 0
        for e in entries or []:
            if not isinstance(e, dict):
                continue
            v = e.get(size_key)
            if v is None and size_key == "Size":
                v = (e.get("UsageData") or {}).get("Size")
            if isinstance(v, (int, float)):
                total += v
        return {"count": len(entries or []), "size_mb": round(total / 1048576, 1)}

    return {
        "images": _sum(data.get("Images") or []),
        "containers": _sum(data.get("Containers") or []),
        "volumes": _sum(data.get("Volumes") or []),
        "build_cache": _sum(data.get("BuildCache") or []),
    }


# ---- 后台事件监听：容器启停/退出等事件 → SSE 广播（仅管理员） ----

# 每次启动工作线程都新建 Event：关闭后再开启不会撞上旧线程的置位状态
_stop = threading.Event()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()  # 并发切换开关/与启动流程并发时防止双线程
_gen = 0  # 事件线程代际：关闭后 90s 内重开时，旧线程的残留事件不再投递
_retry_thread: threading.Thread | None = None


def stream_events(stop: threading.Event, on_event) -> None:
    """阻塞跟随容器事件流；断线自动重连，stop 置位后退出。"""
    path = "/events?filters=" + urllib.parse.quote(json.dumps({"type": ["container"]}))
    while not stop.is_set():
        try:
            # 读超时给足：事件稀疏时连接会长时间空闲；超时后走重连，不影响正确性
            conn = _connect(timeout=90.0)
            try:
                conn.request("GET", path)
                resp = conn.getresponse()
                if resp.status >= 400:
                    raise DockerUnavailable(f"Docker 事件流 {resp.status}")
                while not stop.is_set():
                    line = resp.readline()
                    if not line:
                        break
                    # stop 置位后 readline 返回的残留事件不再投递
                    # （关闭窗口内不该再产生新事件，docstring 承诺的行为）
                    if stop.is_set():
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line.decode("utf-8", "replace"))
                    except ValueError:
                        continue
                    if ev.get("Type") and ev.get("Type") != "container":
                        continue
                    attrs = (ev.get("Actor") or {}).get("Attributes") or {}
                    try:
                        on_event(
                            {
                                "action": str(ev.get("Action") or ev.get("status") or ""),
                                "id": str(ev.get("id") or "")[:12],
                                "name": str(attrs.get("name") or ""),
                            }
                        )
                    except Exception:
                        # on_event（broker.publish）抛其他异常不能带崩整个事件线程：
                        # 外层 except 只捕 (DockerUnavailable, OSError, ValueError)，
                        # 漏一个意外异常事件推送就永久停摆且无人重启
                        logger.exception("容器事件回调失败")
            finally:
                conn.close()
        except (DockerUnavailable, OSError, ValueError) as exc:
            logger.debug("Docker 事件流断开：%s", exc)
        stop.wait(5.0)


def sync_events_worker(broker, enabled: bool) -> None:
    """按「容器监控」开关同步事件线程：关=停止且不再访问 Docker；开=确保在跑。

    设置页切换开关时也调用本函数（settings API），无需重启后端。
    关闭后旧线程最多再存活一个读超时周期（≤90s）；期间重新开启时靠代际号
    屏蔽旧线程的残留事件，不会出现新旧两线程同时推送。
    """
    global _worker, _stop, _gen
    with _worker_lock:
        if not enabled:
            if _worker is not None:
                _stop.set()
                logger.info("容器监控已关闭：Docker 事件监听停止")
            _worker = None
            return
        if _worker is not None and _worker.is_alive() and not _stop.is_set():
            return
        ok, _ = available()
        if not ok:
            logger.info("Docker 不可用，容器监控事件监听暂未启动（后台每 60s 自动重试）")
            _schedule_retry(broker)
            return
        _gen += 1
        mygen = _gen
        _stop = threading.Event()
        stop = _stop

        def _run():
            def _on_event(ev: dict):
                if mygen != _gen:
                    # 本线程已被新一代替代（关闭后立刻重开的窗口）：不再投递
                    return
                # audience=admins：SSE 端点只投递给管理员账号
                broker.publish({"type": "docker.event", "audience": "admins", **ev})

            stream_events(stop, _on_event)

        _worker = threading.Thread(target=_run, name="docker-events", daemon=True)
        _worker.start()
    logger.info("Docker 事件监听已启动（%s）", host_display())


def _schedule_retry(broker) -> None:
    """启动时 Docker 未就绪（socket 晚挂载/引擎慢启动）时后台定时重试。

    不重试的话事件监听永远不启动，直到管理员手动切一次开关。
    """
    global _retry_thread
    if _retry_thread is not None and _retry_thread.is_alive():
        return

    def _loop():
        while True:
            time.sleep(60.0)
            with _worker_lock:
                alive = _worker is not None and _worker.is_alive() and not _stop.is_set()
            if alive:
                return  # 已被其他路径启动
            # 开关可能已被关闭：关闭状态下不再触碰 Docker，由下一次手动开启接管
            from app.db.session import SessionLocal
            from app.models.system_setting import get_setting_db

            db = SessionLocal()
            try:
                enabled = get_setting_db(db, "docker_monitor_enabled", "false") == "true"
            finally:
                db.close()
            if not enabled:
                return
            sync_events_worker(broker, True)
            with _worker_lock:
                alive = _worker is not None and _worker.is_alive() and not _stop.is_set()
            if alive:
                return

    _retry_thread = threading.Thread(target=_loop, name="docker-events-retry", daemon=True)
    _retry_thread.start()


def stop_events_worker() -> None:
    """进程退出时的兜底停止（lifespan shutdown）。"""
    _stop.set()


def invalidate_list_cache() -> None:
    """写操作（启停/删除）成功后调用：让下一次列表立即反映最新状态。"""
    with _LIST_CACHE_LOCK:
        _LIST_CACHE[0] = 0.0
        _LIST_CACHE[1] = None


# ---- 写操作（容器控制；门禁与审计在 API 层，本层只与 Docker 通信） ----


class DockerError(Exception):
    """Docker 写操作失败（携带 HTTP 状态码与中文原因，API 层映射为响应）。"""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _write_request(method: str, path: str, timeout: float = 60.0, max_bytes: int = 2_000_000) -> tuple[int, bytes]:
    """写请求：返回 (状态码, 响应体)。状态码交给调用方映射（写接口多为 204 空响应）。"""
    conn = _connect(timeout)
    try:
        conn.request(method, path)
        resp = conn.getresponse()
        return resp.status, resp.read(max_bytes)
    except OSError as exc:
        raise DockerUnavailable(f"无法连接 Docker（{docker_host()}）：{exc}")
    finally:
        conn.close()


def _map_write_error(status: int, body: bytes) -> DockerError:
    """Docker 错误 → 中文提示：409 状态冲突、404 不存在、304 已是目标状态、其余透传。"""
    snippet = body[:200].decode("utf-8", "replace").strip()
    if status == 404:
        return DockerError(404, "容器不存在（可能已被删除）")
    if status == 409:
        return DockerError(409, "容器状态冲突（如仍在运行，请先停止再删除）")
    if status == 304:
        return DockerError(304, "已是目标状态")
    return DockerError(status, f"Docker 返回 {status}：{snippet or '无详情'}")


_ACTION_LABEL = {"start": "已启动", "stop": "已停止", "restart": "已重启"}
_ACTION_ALREADY = {"start": "容器已在运行", "stop": "容器已停止"}


def container_action(cid: str, action: str, timeout_s: int | None = None) -> dict:
    """启动 / 停止 / 重启容器。返回 {ok, message}；失败抛 DockerError。"""
    if action not in _ACTION_LABEL:
        raise ValueError(f"未知操作：{action}")
    path = f"/containers/{cid}/{action}"
    if timeout_s is not None and action in ("stop", "restart"):
        path += f"?t={int(timeout_s)}"
    # stop/restart 的 t 是给容器的优雅退出时间，本地等待要更宽
    status, body = _write_request("POST", path, timeout=max(60.0, (timeout_s or 0) + 30.0))
    if status in (200, 204):
        return {"ok": True, "message": _ACTION_LABEL[action]}
    err = _map_write_error(status, body)
    if err.status == 304:
        return {"ok": True, "message": _ACTION_ALREADY.get(action, _ACTION_LABEL[action])}
    raise err


def remove_container(cid: str) -> dict:
    """删除容器本体：不带 v=1（绝不连带删卷），运行中的容器由 Docker 返回 409。"""
    status, body = _write_request("DELETE", f"/containers/{cid}?v=0", timeout=60.0)
    if status in (200, 204):
        return {"ok": True, "message": "容器已删除"}
    raise _map_write_error(status, body)


def _split_image_tag(image: str) -> tuple[str, str]:
    """拆 镜像名:标签；无标签默认 latest；拒绝 digest 引用与空白/特殊字符。"""
    image = image.strip()
    if not image or "@" in image or any(c.isspace() for c in image):
        raise DockerError(400, "镜像名不合法（暂不支持按摘要拉取）")
    if not re.fullmatch(r"[A-Za-z0-9._/\-:]+", image):
        raise DockerError(400, "镜像名包含不支持的字符")
    name, tag = image, "latest"
    i = image.rfind(":")
    if i > image.rfind("/"):  # 冒号在最后一个斜杠之后才是 tag（registry 带端口的情况）
        name, tag = image[:i], image[i + 1:] or "latest"
    if not name or not tag:
        raise DockerError(400, "镜像名不合法")
    return name, tag


def pull_image(image: str) -> dict:
    """拉取镜像（默认 latest tag）。v1 只拉取，不自动重建容器。"""
    name, tag = _split_image_tag(image)
    path = (
        "/images/create?fromImage=" + urllib.parse.quote(name, safe="")
        + "&tag=" + urllib.parse.quote(tag, safe="")
    )
    status, body = _write_request("POST", path, timeout=_PULL_TIMEOUT, max_bytes=4_000_000)
    if status in (200, 204):
        return {
            "ok": True,
            "image": f"{name}:{tag}",
            "message": f"镜像 {name}:{tag} 已更新，请在 NAS 的 Docker 界面重建容器以应用新镜像",
        }
    try:
        detail = str(json.loads(body.decode("utf-8", "replace")).get("message") or "")
    except ValueError:
        detail = ""
    if status == 404:
        raise DockerError(404, f"镜像或仓库不存在：{detail or name + ':' + tag}")
    raise DockerError(status, detail or f"Docker 返回 {status}")
