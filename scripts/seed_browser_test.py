"""浏览器实测种子数据：注册管理员、造 12 条导航、注册设备推 3 条消息。

用法：先起后端（临时数据目录），再 `python scripts/seed_browser_test.py http://127.0.0.1:18765`
仅供本地联调，不属于任何回归套件。
"""

import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18765").rstrip("/")


def call(method, path, body=None, token=None, form=None):
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        req = urllib.request.Request(BASE + path, data=data, method=method)
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    else:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(BASE + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


def main() -> int:
    user, pwd = "browsertest", "test-pass-123"
    st, body = call("POST", "/api/v1/auth/register", {"username": user, "password": pwd})
    if st != 200:
        print("register:", st, body)
        return 1
    token = body["access_token"]

    # 12 条导航：桌面端第 1 页 9 个 + 第 2 页 3 个 + 添加卡
    for i in range(1, 13):
        st, r = call(
            "POST", "/api/v1/nav",
            form={"name": f"测试导航{i:02d}", "url": f"https://example.com/{i}", "open_mode": "new"},
            token=token,
        )
        if st not in (200, 201):
            print("nav create:", st, r)
            return 1

    # 接入源 + 设备 + 3 条消息
    st, src = call("POST", "/api/v1/sources", {"name": "测试通知", "type": "api"}, token=token)
    st, dev = call(
        "POST", "/api/v1/devices/register",
        {"name": "测试设备", "kind": "notify", "source_id": src["id"]}, token=token,
    )
    did, dsecret = dev["device_id"], dev["device_secret"]

    def push(title, content):
        raw = json.dumps({"title": title, "content": content}).encode()
        ts, nonce = int(time.time()), f"n{time.time_ns()}"
        sig = hmac.new(dsecret.encode(), f"{did}\n{ts}\n{nonce}\n{hashlib.sha256(raw).hexdigest()}".encode(), hashlib.sha256).hexdigest()
        req = urllib.request.Request(BASE + "/api/v1/ingest/device", data=raw, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Device-Id", did)
        req.add_header("X-Timestamp", str(ts))
        req.add_header("X-Nonce", nonce)
        req.add_header("X-Signature", sig)
        with urllib.request.urlopen(req) as resp:
            return resp.status

    for i in range(1, 4):
        push(f"测试消息{i}", f"这是第 {i} 条测试消息的正文内容。")

    print("seed ok: user=browsertest pwd=test-pass-123 navs=12 messages=3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
