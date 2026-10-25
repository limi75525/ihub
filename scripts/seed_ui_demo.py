"""本地假 QB/MP + 已配置连接，供浏览器/UI 联调使用（仅开发）。

运行：
  .venv/Scripts/python scripts/seed_ui_demo.py

会打印访问地址与管理员账号，进程保持运行；Ctrl+C 退出并清理临时数据目录。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from seed_fake_test import (  # noqa: E402
    FakeMpState,
    FakeQbState,
    MpHandler,
    QbHandler,
    _free_port,
    _request,
    _wait_health,
)

DATA_DIR = os.path.join(ROOT, ".seed-ui-data")
API_PORT = 18770
QB_PORT = 18771
MP_PORT = 18772


def main() -> int:
    if os.path.isdir(DATA_DIR):
        shutil.rmtree(DATA_DIR, ignore_errors=True)
    qb_server = ThreadingHTTPServer(("127.0.0.1", QB_PORT), QbHandler)
    mp_server = ThreadingHTTPServer(("127.0.0.1", MP_PORT), MpHandler)
    for server in (qb_server, mp_server):
        threading.Thread(target=server.serve_forever, daemon=True).start()

    log = open(os.path.join(ROOT, ".seed-ui-backend.log"), "w", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "IHUB_DATA_DIR": DATA_DIR,
            "IHUB_SECRET_KEY": "seed-ui-demo-secret",
            "IHUB_SEED_QB_INTERVAL": "2",
            "IHUB_SEED_MP_INTERVAL": "2",
            "IHUB_SEED_LOOP_SECONDS": "1",
        }
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(API_PORT), "--no-proxy-headers"],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{API_PORT}"
    try:
        _wait_health(base)
        status, reg = _request(
            base, "POST", "/api/v1/auth/register",
            body={"username": "uiadmin", "password": "ui-pass-123"},
        )
        if status != 200:
            print("register failed", reg)
            return 1
        token = reg["access_token"]
        # 普通用户：用于查看只读权限与可见范围
        _request(
            base, "POST", "/api/v1/auth/register",
            body={"username": "uinormal", "password": "ui-pass-456"},
        )
        _request(
            base, "POST", "/api/v1/seeds/connections", token,
            {
                "kind": "qbittorrent", "name": "测试 qBittorrent",
                "base_url": f"http://127.0.0.1:{QB_PORT}",
                "username": "admin", "secret": "qb-pass", "auth_mode": "password",
                "verify_tls": True, "enabled": True,
            },
        )
        _request(
            base, "POST", "/api/v1/seeds/connections", token,
            {
                "kind": "moviepilot", "name": "测试 MoviePilot",
                "base_url": f"http://127.0.0.1:{MP_PORT}",
                "secret": "test-token-1234567890", "auth_mode": "api_token",
                "verify_tls": True, "enabled": True,
            },
        )
        # 触发一次概览，建立客户端会话并启动种子事件线程
        _request(base, "GET", "/api/v1/seeds/overview", token=token)
        # 让事件线程先建立水位，再追加一条完成种子/两条通知，便于 UI 看到消息事件
        time.sleep(2)
        FakeQbState.torrents.append(
            {
                "hash": "ddd444", "name": "刚完成的示例种子", "state": "uploading",
                "progress": 1, "size": 1024 * 1024, "total_size": 1024 * 1024,
                "dlspeed": 0, "upspeed": 0, "eta": 0, "ratio": 0, "category": "电影",
                "tags": "示例", "added_on": 1300, "completion_on": int(time.time()),
                "save_path": "/downloads", "content_path": "", "tracker": "",
                "num_seeds": 0, "num_leechs": 0, "amount_left": 0,
            }
        )
        FakeMpState.notifications.append(
            {
                "id": 2, "mtype": "订阅", "ctype": "subscribeComplete",
                "title": "订阅完成", "text": "示例剧集已全部下载完成",
                "reg_time": "2026-10-21 11:00:00",
            }
        )
        FakeMpState.notifications.append(
            {
                "id": 3, "mtype": "站点", "ctype": "",
                "title": "【站点自动签到】",
                "text": "本次签到数量: 2\n登录或访问失败: 1\n【憨憨】登录失败",
                "reg_time": "2026-10-21 11:01:00",
            }
        )
        print(f"iHub UI: {base}/", flush=True)
        print("管理员: uiadmin / ui-pass-123", flush=True)
        print("普通用户: uinormal / ui-pass-456", flush=True)
        print("qB/MP 均为假服务，端口", QB_PORT, MP_PORT, flush=True)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        log.close()
        qb_server.shutdown()
        mp_server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
