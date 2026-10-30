"""iHub 渗透测试探针（纯标准库，针对本机回环的自部署实例）。

用法：
  1. 用临时数据目录启动后端：
     cd backend && IHUB_DATA_DIR=./.sec-data IHUB_SECRET_KEY=sectest \
       .venv/Scripts/python -m uvicorn app.main:app --port 18767 --no-proxy-headers
  2. .venv/Scripts/python scripts/security_probe.py http://127.0.0.1:18767

每项检查输出 [OK]（安全预期达成）或 [VULN]（攻击成功）+ 证据。
最后为登录限流与注册限流验证（消耗 IP 额度），放最后执行；
同一实例重复运行会因注册限流（30 次/10 分钟）提前失败，需换全新数据目录并重启实例。
"""

import hashlib
import hmac
import http.client
import json
import random
import secrets
import shutil
import string
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18767"
HOSTPORT = urllib.parse.urlparse(BASE).netloc

_results: list[tuple[bool, str, str]] = []


def report(vuln: bool, name: str, evidence: str) -> None:
    _results.append((vuln, name, evidence))
    print(f"[{'VULN' if vuln else 'OK'}] {name}\n      {evidence}")


def req(
    method: str,
    path: str,
    body=None,
    token: str | None = None,
    headers: dict | None = None,
):
    url = BASE + path
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
    r = urllib.request.Request(url, data=data, method=method)
    if body is not None and not isinstance(body, bytes):
        r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            payload = resp.read()
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, payload
    except urllib.error.HTTPError as e:
        try:
            return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()
        except OSError:
            # 413 等场景服务端可声明 connection: close 后断开，错误响应体可能读不到
            return e.code, {k.lower(): v for k, v in e.headers.items()}, b""


def jreq(method, path, body=None, token=None, headers=None):
    status, hdrs, data = req(method, path, body, token, headers)
    try:
        return status, hdrs, json.loads(data.decode("utf-8", "replace"))
    except (ValueError, UnicodeDecodeError):
        return status, hdrs, {}


def register(username: str, password: str):
    status, _, out = jreq("POST", "/api/v1/auth/register", {"username": username, "password": password})
    assert status == 200, f"注册失败 {status}: {out}"
    return out  # {access_token, media_key, user}


SVG_PAYLOAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="80" height="20">'
    "<script>alert('s1')</script>"
    '<a xlink:href="&#106;&#97;vascript:alert(\'e1\')"><text x="4" y="12">go</text></a>'
    "<animate attributeName=\"xlink:href\" values=\"javascript:alert('a1')\"/>"
    "<set attributeName=\"href\" to=\"javascript:alert('s2')\"/>"
    '<rect onmouseover="alert(\'o1\')" width="10" height="10"/>'
    "</svg>"
)


def multipart(field: str, filename: str, content: bytes, ctype: str) -> tuple[bytes, str]:
    boundary = "----probe" + secrets.token_hex(8)
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def admin_book_upload(admin: dict) -> tuple[int, int]:
    """管理员经分片管道上传 TXT 并导入书架，返回 (item_id, book_id)。"""
    text = "第1章 起点\n" + "内容。" * 200 + "\n第2章 终点\n" + "结尾。" * 200
    blob = text.encode("utf-8")
    status, _, out = jreq(
        "POST", "/api/v1/transfer/upload/init",
        {"name": "安全测试.txt", "size": len(blob)}, token=admin["access_token"],
    )
    assert status == 200, out
    uid = out["uploadId"]
    status, _, _ = jreq("PUT", f"/api/v1/transfer/upload/{uid}/chunk/0", blob, token=admin["access_token"])
    assert status == 200, "分片上传失败"
    status, _, out = jreq("POST", f"/api/v1/transfer/upload/{uid}/finish", {}, token=admin["access_token"])
    assert status == 200, out
    item_id = out["item"]["id"]
    status, _, out = jreq("POST", "/api/v1/books/import", {"item_id": item_id}, token=admin["access_token"])
    assert status == 200, f"导入失败 {status}: {out}"
    return item_id, out["id"]


def signed_push(device_id: str, secret: str, payload: dict) -> int:
    """按协议伪造一次合法签名推送（HMAC-SHA256）。"""
    raw = json.dumps(payload, ensure_ascii=False).encode()
    ts = str(int(time.time()))
    nonce = secrets.token_hex(8)
    body_sha = hashlib.sha256(raw).hexdigest()
    sign = hmac.new(
        secret.encode(), f"{device_id}\n{ts}\n{nonce}\n{body_sha}".encode(), hashlib.sha256
    ).hexdigest()
    conn = http.client.HTTPConnection(HOSTPORT, timeout=15)
    conn.request(
        "POST", "/api/v1/ingest/device", body=raw,
        headers={
            "Content-Type": "application/json",
            "X-Device-Id": device_id,
            "X-Timestamp": ts,
            "X-Nonce": nonce,
            "X-Signature": sign,
        },
    )
    resp = conn.getresponse()
    code = resp.status
    resp.read()
    conn.close()
    return code



class _SeedQbHandler(BaseHTTPRequestHandler):
    """最小假 qBittorrent：只覆盖种子模块探针需要的认证/版本/删除接口。"""

    deleted_body = ""

    def log_message(self, fmt, *args):
        return

    def _send(self, status: int, body, content_type: str = "application/json"):
        raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/v2/app/version":
            return self._send(200, "v4.6.7", "text/plain")
        if path == "/api/v2/app/webapiVersion":
            return self._send(200, "2.9.3", "text/plain")
        if path == "/api/v2/transfer/info":
            return self._send(200, {"dl_info_speed": 0, "up_info_speed": 0})
        if path == "/api/v2/torrents/info":
            return self._send(200, [])
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if path == "/api/v2/auth/login":
            return self._send(200, "Ok.", "text/plain")
        if path in ("/api/v2/torrents/pause", "/api/v2/torrents/resume"):
            return self._send(200, "Ok.", "text/plain")
        if path == "/api/v2/torrents/delete":
            _SeedQbHandler.deleted_body = body.decode("utf-8", "replace")
            return self._send(200, "Ok.", "text/plain")
        return self._send(404, {"error": "not found"})


def main() -> None:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    admin_pw = "Admin#" + suffix
    attacker_pw = "Hacker#" + suffix
    admin = register("secadmin" + suffix, admin_pw)
    # 注册被关闭时攻击者改走已泄露口令的既有账号——本测试环境注册默认开放
    attacker = register("secattk" + suffix, attacker_pw)
    atk_token, atk_media = attacker["access_token"], attacker["media_key"]
    atk_uid = attacker["user"]["id"]

    print("== A. 认证边界 ==")
    for name, path in [
        ("消息列表", "/api/v1/messages"),
        ("书架列表", "/api/v1/books"),
        ("回收站", "/api/v1/recycle"),
        ("用户列表(管理)", "/api/v1/users"),
    ]:
        status, _, _ = req("GET", path)
        report(status == 200, f"未授权访问 {name}", f"HTTP {status}（预期 401/403）")
    for name, path in [
        ("书架原文件", "/api/v1/books/1/file"),
        ("快传文件", "/api/v1/transfer/1/file"),
        ("用户头像", "/api/v1/users/avatar/1"),
    ]:
        status, _, _ = req("GET", path)
        report(status == 200, f"未授权媒体访问 {name}", f"HTTP {status}（预期 401）")
    status, _, _ = req("GET", "/api/docs")
    report(status == 200, "API 文档匿名可访问", f"/api/docs HTTP {status}")
    status, hdrs, _ = req(
        "OPTIONS", "/api/v1/auth/login",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )
    acao = hdrs.get("access-control-allow-origin") or ""
    report(bool(acao), "CORS 白名单外源放行", f"Origin=evil.example → ACAO={acao or '（无）'}")

    print("== B. 跨用户越权（IDOR） ==")
    item_id, book_id = admin_book_upload(admin)
    status, hdrs, data = req("GET", f"/api/v1/books/{book_id}/file", token=atk_media)
    report(
        status == 200 and "第2章" in data.decode("utf-8", "replace"),
        f"越权读取他人书籍原文件 /books/{book_id}/file",
        f"攻击者 media_key 请求 → HTTP {status}, 读得 {len(data)} 字节书籍内容",
    )
    status, _, _ = req("GET", f"/api/v1/books/{book_id}/cover", token=atk_media)
    report(status == 200, f"越权读取他人书籍封面 /books/{book_id}/cover", f"HTTP {status}")

    print("== D. 路径穿越（书籍未删除时） ==")
    for probe in ("../../.secret_key", "..%2F..%2F.secret_key", "....//....//.secret_key", "images/../rules.json"):
        status, _, data = req("GET", f"/api/v1/books/{book_id}/asset?path={urllib.parse.quote(probe)}", token=atk_media)
        report(
            status == 200 and b"SECRET" in data.upper() or (status == 200 and len(data) > 32 and b"<" not in data),
            f"书籍资源路径穿越 {probe}",
            f"HTTP {status}, len={len(data)}",
        )
    # 附件文件名注入（控制组：不存在的消息）
    status, _, data = req("GET", "/api/v1/messages/999999/attachments/0", token=atk_media)
    report(status == 200, "越权/穿越读取附件", f"HTTP {status}")

    # 管理员建设备推一条消息，攻击者尝试跨用户读/删
    status, _, dev = jreq(
        "POST", "/api/v1/devices/register",
        {"name": "probe-dev" + suffix, "kind": "notify"}, token=admin["access_token"],
    )
    assert status == 200, dev
    code = signed_push(dev["device_id"], dev["device_secret"], {"title": "<script>alert(1)</script>", "content": "xss-probe-body"})
    assert code == 200, f"合法签名推送失败（测试脚本问题）: HTTP {code}"
    status, _, msgs = jreq("GET", "/api/v1/messages", token=admin["access_token"])
    mid = msgs["items"][0]["id"] if status == 200 and msgs.get("items") else None
    if mid:
        status, _, out = jreq("GET", f"/api/v1/messages/{mid}", token=atk_token)
        report(status == 200, f"越权读取他人消息 /messages/{mid}", f"HTTP {status}")
        status, _, out = jreq("POST", "/api/v1/messages/batch", {"ids": [mid], "action": "delete"}, token=atk_token)
        report(
            status == 200 and out.get("updated", 1) > 0,
            "越权删除他人消息", f"HTTP {status}, updated={out.get('updated')}"
        )
    # 其余媒体接口的越权矩阵（应全部拒绝）
    status, _, tr = jreq("GET", "/api/v1/transfer", token=admin["access_token"])
    tid = tr["items"][0]["id"] if tr.get("items") else 1
    for name, path in [
        ("他人快传文件", f"/api/v1/transfer/{tid}/file"),
        ("他人书籍资源", f"/api/v1/books/{book_id}/asset?path=content.txt"),
        ("他人回收站logo", "/api/v1/recycle/logo-file/group:1"),
        ("他人头像分组logo", "/api/v1/logos/groups/1/logo-file"),
        ("他人头像规则logo", "/api/v1/logos/rules/1/logo-file"),
    ]:
        status, _, _ = req("GET", path, token=atk_media)
        report(status == 200, f"越权访问{name}", f"HTTP {status}")

    # 软删后仍可读
    status, _, _ = jreq("DELETE", f"/api/v1/books/{book_id}", token=admin["access_token"])
    assert status == 200
    status, _, data = req("GET", f"/api/v1/books/{book_id}/file", token=atk_media)
    report(status == 200, "越权读取已删除书籍（回收站软删后）", f"HTTP {status}，仍可下载原文件")

    # 管理员专用写接口：普通用户改他人头像必须被拒（新增端点同步补探针用例）
    admin_uid = admin["user"]["id"]
    body, ctype = multipart("file", "atk.png", b"\x89PNG\r\n\x1a\n" + b"x" * 128, "image/png")
    status, _, _ = req(
        "POST", f"/api/v1/users/{admin_uid}/avatar",
        body, token=atk_token, headers={"Content-Type": ctype},
    )
    report(status in (200, 201, 204), "普通用户改他人头像 /users/{id}/avatar", f"HTTP {status}（预期 403）")
    # 管理员代改头像（对照组）：必须成功
    body, ctype = multipart("file", "ok.png", b"\x89PNG\r\n\x1a\n" + b"y" * 128, "image/png")
    status, _, _ = req(
        "POST", f"/api/v1/users/{atk_uid}/avatar",
        body, token=admin["access_token"], headers={"Content-Type": ctype},
    )
    report(status != 200, "管理员代改用户头像（对照组）", f"HTTP {status}（预期 200）")

    print("== C. SVG 清洗绕过（存储型 XSS） ==")
    body, ctype = multipart("file", "evil.svg", SVG_PAYLOAD.encode(), "image/svg+xml")
    status, _, out = jreq("POST", "/api/v1/auth/avatar", body, token=atk_token, headers={"Content-Type": ctype})
    if status != 200:
        report(False, "SVG 恶意载荷被拒绝上传", f"HTTP {status}（上传即被拒绝，安全）")
    else:
        status, hdrs, data = req("GET", f"/api/v1/users/avatar/{atk_uid}?token={atk_media}")
        text = data.decode("utf-8", "replace")
        survivals = [p for p in ("&#106;", "<animate", "<set ", "javascript:", "onmouseover", "<script") if p in text.lower()]
        report(
            bool(survivals),
            "SVG 清洗绕过（实体编码/SMIL 动画存活）",
            f"HTTP {status}; 存活载荷: {survivals or '无'}; "
            f"Content-Disposition={hdrs.get('content-disposition', '（内联）')}",
        )
        cd = hdrs.get("content-disposition", "")
        report(
            "attachment" not in cd.lower(),
            "SVG 可内联执行（缺 Content-Disposition: attachment）",
            f"Content-Disposition={cd or '（无）'}",
        )

    print("== E. 未认证推送与 DoS 边界 ==")
    status, _, data = req("POST", "/api/v1/ingest/device", {"msg": "x"},
                          headers={"X-Device-Id": "ZZZZZZZZ", "X-Timestamp": str(int(time.time())),
                                   "X-Nonce": secrets.token_hex(8), "X-Signature": "0" * 64})
    report(status == 200, "伪造签名推送", f"HTTP {status}（预期 401）")
    conn = http.client.HTTPConnection(HOSTPORT, timeout=15)
    conn.request("POST", "/api/v1/ingest/device", body=b"A" * (600 * 1024),
                 headers={"Content-Type": "application/json"})
    code = conn.getresponse().status
    conn.close()
    report(code != 413, "未认证超大请求体限制", f"600KB 无签名推送 → HTTP {code}（预期 413）")

    print("== F. 分片上传内存边界（已认证） ==")
    status, _, out = jreq("POST", "/api/v1/transfer/upload/init",
                          {"name": "big.bin", "size": 8 * 1024 * 1024}, token=atk_token)
    assert status == 200, out
    uid = out["uploadId"]
    conn = http.client.HTTPConnection(HOSTPORT, timeout=60)
    chunk = b"B" * (1024 * 1024)
    conn.putrequest("PUT", f"/api/v1/transfer/upload/{uid}/chunk/0")
    conn.putheader("Transfer-Encoding", "chunked")
    conn.putheader("Authorization", f"Bearer {atk_token}")
    conn.endheaders()
    for _ in range(8):  # 8MB，单分片上限 4MB+1KB
        conn.send(b"%x\r\n" % len(chunk) + chunk + b"\r\n")
    conn.send(b"0\r\n\r\n")
    resp = conn.getresponse()
    chunked_status = resp.status
    resp.read()
    conn.close()
    report(
        chunked_status == 200,
        "无 Content-Length 超大分片绕过 4MB 上限",
        f"chunked 8MB 单分片 → HTTP {chunked_status}（预期 4xx）",
    )

    print("== G. SQL 注入探针 ==")
    for q in ("' OR 1=1--", "'; DROP TABLE messages;--", "%' OR '1'='1"):
        status, _, out = jreq("GET", "/api/v1/messages?q=" + urllib.parse.quote(q), token=atk_token)
        report(status >= 500, f"SQL 注入 q={q!r}", f"HTTP {status}")

    print("== G2. 容器监控接口（管理员只读） ==")
    for name, path in [
        ("容器状态", "/api/v1/docker/status"),
        ("容器列表", "/api/v1/docker/containers"),
        ("磁盘占用", "/api/v1/docker/df"),
        ("容器日志", "/api/v1/docker/containers/abcdef123456/logs"),
    ]:
        status, _, _ = req("GET", path)
        report(status == 200, f"未授权访问 {name}", f"HTTP {status}（预期 401/403）")
        status, _, _ = req("GET", path, token=atk_token)
        report(status == 200, f"普通用户访问 {name}", f"HTTP {status}（预期 403）")
    for evil in ("..%2F..%2Fvar%2Frun", "%3Cscript%3E", "abcd%24%7Bjail%7D"):
        status, _, _ = req(
            "GET", f"/api/v1/docker/containers/{evil}/logs", token=admin["access_token"]
        )
        # 含路径穿越/特殊字符的 cid 必须被拒（400 校验拒绝或 404 路由不匹配），绝不 200 回内容
        report(status == 200, f"容器 ID 注入 {evil}", f"HTTP {status}（预期 4xx）")

    # 容器写操作（双开关默认关）：匿名 401 / 普通用户 403 / 管理员在开关全关时 403 或 503
    for name, method, path, body in [
        ("启动容器", "POST", "/api/v1/docker/containers/abcdef123456/start", None),
        ("停止容器", "POST", "/api/v1/docker/containers/abcdef123456/stop", None),
        ("重启容器", "POST", "/api/v1/docker/containers/abcdef123456/restart", None),
        ("删除容器", "DELETE", "/api/v1/docker/containers/abcdef123456", None),
        ("拉取镜像", "POST", "/api/v1/docker/images/pull", {"image": "probe/test:latest"}),
    ]:
        status, _, _ = req(method, path, body=body)
        report(status == 200, f"未授权容器写操作 {name}", f"HTTP {status}（预期 401）")
        status, _, _ = req(method, path, body=body, token=atk_token)
        report(status == 200, f"普通用户容器写操作 {name}", f"HTTP {status}（预期 403）")
        status, _, _ = req(method, path, body=body, token=admin["access_token"])
        report(status == 200, f"开关全关时容器写操作 {name}", f"HTTP {status}（预期 403/503）")

    print("== H. 登录暴力破解防护（放最后，消耗失败额度） ==")
    locked = False
    for i in range(6):
        status, _, _ = jreq("POST", "/api/v1/auth/login",
                            {"username": "secattk" + suffix, "password": "wrong-" + str(i)})
        if status == 429:
            locked = True
            break
    report(not locked, "登录失败 5 次未触发锁定", f"连续错密 6 次 → 第 {i + 1} 次仍 HTTP {status}")

    print("== I. SSRF 加固（logo 在线缓存）与导航 SVG ==")
    # 管理员开启图片缓存，攻击者用 file:// 指向服务器本地图片，
    # 若缓存成功（logo_kind=file）即等于把服务器本地文件拖回攻击者账号（SSRF→LFI）。
    status, _, _ = jreq("PATCH", "/api/v1/settings/image-cache", {"enabled": True}, token=admin["access_token"])
    assert status == 200, "开启图片缓存失败（脚本前置条件）"
    import glob as _glob

    local_img = ""
    for pat in ("C:/Windows/Web/Wallpaper/**/*.jpg", "C:/Windows/Web/**/*.png"):
        hits = _glob.glob(pat, recursive=True)
        if hits:
            local_img = hits[0].replace("\\", "/")
            break
    if local_img:
        status, _, out = jreq(
            "POST", "/api/v1/logos/groups",
            {"name": "probe-ssrf-file" + suffix, "logo_url": "file:///" + local_img},
            token=atk_token,
        )
        assert status == 200, out
        time.sleep(2.5)  # 缓存线程异步执行
        status, _, rules = jreq("GET", "/api/v1/logos/groups", token=atk_token)
        kind = next((r["logo_kind"] for r in rules if r["id"] == out["id"]), None)
        report(kind == "file", "SSRF file:// 本地文件缓存", f"logo_kind={kind}（file=本地文件已被拖入账号）")
    status, _, out = jreq(
        "POST", "/api/v1/logos/groups",
        {"name": "probe-ssrf-ftp" + suffix, "logo_url": "ftp://127.0.0.1/x.png"},
        token=atk_token,
    )
    time.sleep(1.5)
    status, _, rules = jreq("GET", "/api/v1/logos/groups", token=atk_token)
    kind = next((r["logo_kind"] for r in rules if r["id"] == out["id"]), None)
    report(kind == "file", "SSRF ftp:// 出站请求", f"logo_kind={kind}")

    # 导航 logo 走同一清洗器：上传含恶意载荷的 SVG
    body, ctype = multipart("file", "nav.svg", SVG_PAYLOAD.encode(), "image/svg+xml")
    boundary = ctype.split("=")[1]
    form = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"name\"\r\n\r\n恶意导航\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"url\"\r\n\r\nhttps://example.com\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"open_mode\"\r\n\r\nnew\r\n"
    ).encode()
    nav_body = form + (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"nav.svg\"\r\n"
        f"Content-Type: image/svg+xml\r\n\r\n"
    ).encode() + SVG_PAYLOAD.encode() + f"\r\n--{boundary}--\r\n".encode()
    status, _, out = jreq(
        "POST", "/api/v1/nav", nav_body, token=atk_token,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    if status != 200:
        report(False, "导航 SVG 上传被拒绝/安全", f"HTTP {status}")
    else:
        nav_id = out["item"]["id"]
        status, hdrs, data = req("GET", f"/api/v1/nav/{nav_id}/logo", token=atk_media)
        text = data.decode("utf-8", "replace").lower()
        survivals = [p for p in ("&#106;", "<animate", "javascript:", "onmouseover", "<script") if p in text]
        report(
            bool(survivals) or "attachment" not in hdrs.get("content-disposition", "").lower(),
            "导航 SVG 清洗/响应头缺失",
            f"存活: {survivals or '无'}; CD={hdrs.get('content-disposition', '（无）')}",
        )

    # 头像库 ZIP 导入通道同样接受 SVG：构造含恶意 SVG 的导入包
    import io as _io
    import zipfile as _zf

    buf = _io.BytesIO()
    with _zf.ZipFile(buf, "w") as z:
        z.writestr(
            "rules.json",
            json.dumps({"version": 1, "rules": [{"phone": "197" + suffix, "signature": "", "email": "", "nickname": "", "logo_file": "images/evil.svg", "logo_url": None}]}, ensure_ascii=False),
        )
        z.writestr("images/evil.svg", SVG_PAYLOAD)
    body, ctype = multipart("file", "import.zip", buf.getvalue(), "application/zip")
    status, _, out = jreq("POST", "/api/v1/logos/import", body, token=atk_token, headers={"Content-Type": ctype})
    if status != 200:
        report(False, "ZIP 导入 SVG 检查", f"导入 HTTP {status}")
    else:
        # v1 兼容导入：旧规则条目转为企业分组，恶意 SVG 落在分组默认头像上
        rid = (out.get("created") or [{}])[0].get("id")
        status, hdrs, data = req("GET", f"/api/v1/logos/groups/{rid}/logo-file", token=atk_media)
        text = data.decode("utf-8", "replace").lower()
        survivals = [p for p in ("&#106;", "<animate", "javascript:", "onmouseover", "<script") if p in text]
        report(
            bool(survivals),
            "ZIP 导入 SVG 未清洗",
            f"存活: {survivals or '无'}; CD={hdrs.get('content-disposition', '（无）')}",
        )

    # ============ J. 音乐中心/分片上传修复回归 ============
    print("== J. 歌单封面/上传会话/配置泄露/解码炸弹 ==")

    # J1 歌单封面越权：管理员建歌单传封面，攻击者 media_key 读取
    status, _, pl = jreq("POST", "/api/v1/music/playlists", {"name": "probe 私密歌单"}, token=admin["access_token"])
    assert status == 200, pl
    probe_pid = pl["playlist"]["id"]
    tiny_png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d4944415478da63fccfccc0300300040201cfbcbe690000000049454e44ae426082"
    )
    body, ctype = multipart("file", "c.png", tiny_png, "image/png")
    status, _, _ = jreq("POST", f"/api/v1/music/playlists/{probe_pid}/cover", body,
                        token=admin["access_token"], headers={"Content-Type": ctype})
    assert status == 200, f"封面上传失败（脚本问题）: {status}"
    status, _, _ = req("GET", f"/api/v1/music/playlist-cover/{probe_pid}", token=atk_media)
    report(status == 200, f"越权读取他人歌单封面 /music/playlist-cover/{probe_pid}", f"HTTP {status}")
    status, _, _ = req("GET", f"/api/v1/music/playlist-cover/{probe_pid}", token=admin["media_key"])
    report(status != 200, "歌单封面属主访问失效（对照组）", f"属主自身请求 → HTTP {status}")

    # J2 分片上传会话绑定：管理员 init，攻击者写片/合并
    status, _, up = jreq("POST", "/api/v1/transfer/upload/init", {"name": "victim-probe.txt", "size": 6},
                         token=admin["access_token"])
    assert status == 200, up
    probe_upload = up["uploadId"]
    status, _, _ = req("PUT", f"/api/v1/transfer/upload/{probe_upload}/chunk/0", body=b"secret", token=atk_token)
    report(status == 200, "跨用户向上传会话写分片", f"HTTP {status}（预期 404）")
    status, _, fin = jreq("POST", f"/api/v1/transfer/upload/{probe_upload}/finish", token=atk_token)
    report(status == 200, "跨用户接管 finish 合并他人上传", f"HTTP {status}（预期 404）")
    # 属主自身流程不受影响
    status, _, _ = req("PUT", f"/api/v1/transfer/upload/{probe_upload}/chunk/0", body=b"secret",
                       token=admin["access_token"])
    status2, _, fin2 = jreq("POST", f"/api/v1/transfer/upload/{probe_upload}/finish", token=admin["access_token"])
    report(status != 200 or status2 != 200, "上传会话属主流程失效（对照组）",
           f"属主写片 HTTP {status} / finish HTTP {status2}")

    # J3 音乐配置泄露：管理员配置 nas_path/上游地址后，普通用户不得见
    jreq("PUT", "/api/v1/music/config",
         {"enabled": True, "source": "nas", "nas_path": "X:/probe-private/音乐",
          "sub_url": "http://10.0.0.5:4533", "sub_user": "probe-navidrome"}, token=admin["access_token"])
    status, _, cfg_user = jreq("GET", "/api/v1/music/config", token=atk_token)
    leaked = [k for k in ("nas_path", "sub_url", "sub_user", "jf_url", "jf_user", "nas_track_count") if k in cfg_user]
    report(bool(leaked), "music/config 向非管理员泄露服务器路径/内网地址",
           f"HTTP {status}, 泄露字段: {leaked or '无'}")
    status, _, cfg_admin = jreq("GET", "/api/v1/music/config", token=admin["access_token"])
    report("nas_path" not in cfg_admin, "music/config 管理员完整配置失效（对照组）",
           f"管理员视图缺 nas_path 字段: {cfg_admin}")

    # J4 解压炸弹：6500x6500（4225 万像素）PNG 仅几十 KB，服务端不得完整解码
    import struct as _struct
    import zlib as _zlib

    def _make_png(w: int, h: int) -> bytes:
        row = b"\x00" + b"\xff\x00\x00" * w

        def chunk(tag: bytes, payload: bytes) -> bytes:
            c = tag + payload
            return _struct.pack(">I", len(payload)) + c + _struct.pack(">I", _zlib.crc32(c) & 0xFFFFFFFF)

        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", _struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", _zlib.compress(row * h, 6))
            + chunk(b"IEND", b"")
        )

    status, _, pl2 = jreq("POST", "/api/v1/music/playlists", {"name": "bomb-probe"}, token=atk_token)
    bomb_pid = pl2["playlist"]["id"]
    bomb = _make_png(6500, 6500)
    body, ctype = multipart("file", "bomb.png", bomb, "image/png")
    status, _, _ = jreq("POST", f"/api/v1/music/playlists/{bomb_pid}/cover", body,
                        token=atk_token, headers={"Content-Type": ctype})
    report(status == 200, "歌单封面解压炸弹（4225 万像素 PNG）", f"HTTP {status}（预期 400 拒绝）")
    body, ctype = multipart("file", "ok.png", tiny_png, "image/png")
    status, _, _ = jreq("POST", f"/api/v1/music/playlists/{bomb_pid}/cover", body,
                        token=atk_token, headers={"Content-Type": ctype})
    report(status != 200, "歌单封面正常小图被误拒（对照组）", f"1x1 PNG 上传 → HTTP {status}")

    # J5 伪装 content_type 把 SVG 混进歌单封面（服务端 Pillow 是最终闸门）
    body, ctype = multipart("file", "evil.png", SVG_PAYLOAD.encode(), "image/png")
    status, _, _ = jreq("POST", f"/api/v1/music/playlists/{bomb_pid}/cover", body,
                        token=atk_token, headers={"Content-Type": ctype})
    report(status == 200, "伪装 content_type 上传 SVG 封面", f"image/png 包装 SVG → HTTP {status}")
    # J6 未认证触发 NAS 扫描（全盘索引类管理操作）
    status, _, _ = req("POST", "/api/v1/music/scan")
    report(status == 200, "未认证触发音乐库扫描", f"HTTP {status}（预期 401）")

    # ============ K. 分片磁盘放大/注册限流/首用户竞态/auth body/导航 scheme ============
    print("== K. 分片磁盘防线/注册限流/auth body 上限/导航 scheme ==")

    # K1 声明 1MB 却传第 2 片：磁盘防线必须按声明大小约束分片序号与累计量
    status, _, up2 = jreq("POST", "/api/v1/transfer/upload/init", {"name": "k1-probe.bin", "size": 1024 * 1024},
                          token=atk_token)
    assert status == 200, up2
    k1_upload = up2["uploadId"]
    status, _, _ = req("PUT", f"/api/v1/transfer/upload/{k1_upload}/chunk/1", body=b"A" * 1024, token=atk_token)
    report(status == 200, "声明 1MB 的会话写入第 2 片（index 超声明）", f"HTTP {status}（预期 400）")
    status, _, _ = req("PUT", f"/api/v1/transfer/upload/{k1_upload}/chunk/0", body=b"A" * 1024, token=atk_token)
    report(status != 200, "声明范围内分片被误拒（对照组）", f"第 1 片 → HTTP {status}")
    jreq("POST", f"/api/v1/transfer/upload/{k1_upload}/finish", token=atk_token)  # 清理会话，避免占用 K2 的会话名额

    # K2 单用户活跃上传会话数上限（弃单灌盘防线；名额可能被前文占用一部分，弹性断言）
    k_codes = []
    for i in range(12):
        status, _, _ = jreq("POST", "/api/v1/transfer/upload/init", {"name": f"k2-{i}.bin", "size": 1024},
                            token=atk_token)
        k_codes.append(status)
    report(
        not (429 in k_codes and k_codes.count(200) <= 10 and k_codes[-1] == 429),
        "单用户会话数上限失效",
        f"12 次 init → {k_codes}（预期 ≤10 个 200 后转 429）",
    )

    # K3 未认证 auth 端点请求体上限（内存放大防线）
    status, _, _ = jreq("POST", "/api/v1/auth/login", {"username": "x" * (200 * 1024), "password": "y"})
    report(status != 413, "登录接口 200KB 请求体未拦截", f"HTTP {status}（预期 413）")

    # K4 导航地址 scheme 白名单（javascript: 等可执行载荷不得入库；创建/更新均为 Form 接口）
    def _form_fields(fields: dict) -> tuple[bytes, str]:
        boundary = "----probe" + secrets.token_hex(8)
        buf = b""
        for k, v in fields.items():
            buf += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
        buf += f"--{boundary}--\r\n".encode()
        return buf, f"multipart/form-data; boundary={boundary}"

    body, ctype = _form_fields({"name": "k4", "url": "javascript:alert(1)", "open_mode": "new", "logo_url": ""})
    status, _, _ = jreq("POST", "/api/v1/nav", body, token=atk_token, headers={"Content-Type": ctype})
    report(status in (200, 201), "javascript: 导航地址入库", f"HTTP {status}（预期 400）")
    body, ctype = _form_fields({"name": "k4ok", "url": "https://example.com", "open_mode": "new", "logo_url": ""})
    status, _, _ = jreq("POST", "/api/v1/nav", body, token=atk_token, headers={"Content-Type": ctype})
    report(status != 200, "正常 https 导航被误拒（对照组）", f"HTTP {status}")

    # ============ L. 影视接口（同构音乐中心的安全面） ============
    print("== L. 影视：配置泄露/扫描鉴权/媒体流 media_key ==")

    # L1 非管理员不得见视频目录与 Jellyfin 地址/账号
    jreq("PUT", "/api/v1/video/config",
         {"enabled": True, "source": "nas", "nas_path": "X:/probe-private/电影",
          "jf_url": "http://10.0.0.9:8096", "jf_user": "probe-jf"}, token=admin["access_token"])
    status, _, vcfg = jreq("GET", "/api/v1/video/config", token=atk_token)
    leaked = [k for k in ("nas_path", "jf_url", "jf_user", "jf_pass_set", "nas_video_count",
                        "tmdb_key", "tmdb_key_set", "tmdb_proxy", "tmdb_api_base", "tmdb_image_base") if k in vcfg]
    report(bool(leaked), "video/config 向非管理员泄露服务器路径/内网地址",
           f"HTTP {status}, 泄露字段: {leaked or '无'}")
    # L2 管理员视图完整（对照组）
    status, _, vcfg_admin = jreq("GET", "/api/v1/video/config", token=admin["access_token"])
    report("nas_path" not in vcfg_admin, "video/config 管理员完整配置失效（对照组）",
           f"管理员视图缺 nas_path 字段: {vcfg_admin}")
    # L3 未认证不得触发视频扫描（全盘索引类管理操作）
    status, _, _ = req("POST", "/api/v1/video/scan")
    report(status == 200, "未认证触发视频库扫描", f"HTTP {status}（预期 401）")
    # L4 非管理员不得改配置
    status, _, _ = jreq("PUT", "/api/v1/video/config", {"enabled": False}, token=atk_token)
    report(status in (200, 201), "非管理员改写影视配置", f"HTTP {status}（预期 403）")
    # L5 完整 JWT 不得当 media_key 拉视频流（media_key 单独泄露面设计）
    status, _, _ = req("GET", "/api/v1/video/nas/stream/1", token=atk_token)
    report(status == 200, "完整 JWT 换取视频流被接受", f"HTTP {status}（预期 401/403）")
    status, _, _ = req("GET", "/api/v1/video/nas/stream/1", token=atk_media)
    report(status == 200, "media_key 拉视频流被误拒（对照组）", f"HTTP {status}")
    # L6 未知 source 类型必须被拒（防脏数据入库）
    status, _, _ = jreq("PUT", "/api/v1/video/config",
                        {"enabled": True, "source": "file:///etc", "nas_path": ""}, token=admin["access_token"])
    report(status in (200, 201), "未知影视源类型入库", f"HTTP {status}（预期 400）")
    # L7 详情/剧照接口鉴权：详情要登录态；剧照与海报同 stream 口径只认 media_key
    status, _, _ = req("GET", "/api/v1/video/nas/detail/1")
    report(status == 200, "未认证读取视频详情", f"HTTP {status}（预期 401）")
    status, _, _ = req("GET", "/api/v1/video/nas/fanart/1")
    report(status == 200, "未认证拉取视频剧照", f"HTTP {status}（预期 401）")
    status, _, _ = req("GET", "/api/v1/video/nas/fanart/1", token=atk_token)
    report(status == 200, "完整 JWT 换取剧照被接受", f"HTTP {status}（预期 401/403）")
    status, _, _ = req("GET", "/api/v1/video/nas/fanart/1", token=atk_media)
    report(status == 200, "media_key 拉取剧照被误拒（对照组）", f"HTTP {status}")
    status, _, _ = req("GET", "/api/v1/video/nas/logo/1")
    report(status == 200, "未认证拉取标题 Logo", f"HTTP {status}（预期 401）")
    status, _, _ = req("GET", "/api/v1/video/nas/logo/1", token=atk_token)
    report(status == 200, "完整 JWT 换取标题 Logo 被接受", f"HTTP {status}（预期 401/403）")
    status, _, _ = req("GET", "/api/v1/video/nas/logo/1", token=atk_media)
    report(status == 200, "media_key 拉取标题 Logo 被误拒（对照组）", f"HTTP {status}")
    # L8 NFO 声明的海报引用不得把媒体根外的文件带出去（扫描真实条目后请求海报验证）
    vdir = Path(tempfile.mkdtemp(prefix="probe-video-"))
    (vdir / "电影" / "M").mkdir(parents=True)
    (vdir / "电影" / "M" / "M (2020).mp4").write_bytes(b"probe" * 16)
    (vdir / "电影" / "M" / "M (2020).nfo").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<movie><title>M</title>'
        "<poster>../../../secret.jpg</poster></movie>",
        encoding="utf-8",
    )
    (vdir / "secret.jpg").write_bytes(b"SECRET-OUTSIDE" * 8)  # 媒体根外文件
    jreq("PUT", "/api/v1/video/config",
         {"enabled": True, "source": "nas", "nas_path": str(vdir)}, token=admin["access_token"])
    jreq("POST", "/api/v1/video/scan", token=admin["access_token"])
    for _ in range(40):
        _, _, vscan = jreq("GET", "/api/v1/video/scan/status", token=admin["access_token"])
        if not vscan.get("running"):
            break
        time.sleep(0.5)
    _, _, vmovies = jreq("GET", "/api/v1/video/nas/movies", token=admin["access_token"])
    vmid = ((vmovies.get("items") or [{}])[0] or {}).get("id")
    if vmid is None:
        report(True, "NFO 海报引用越界前置扫描失败（无法验证）", str(vscan)[:160])
    else:
        status, _, vbody = req("GET", f"/api/v1/video/nas/poster/{vmid}", token=atk_media)
        report(status == 200 and b"SECRET-OUTSIDE" in vbody,
               "NFO 海报引用越界读取媒体根外文件", f"HTTP {status}, body={bytes(vbody[:16])!r}")
    # L9 在线补全只认纯数字 TMDB 编号：恶意编号不得拼进上游 URL（注入面）；合法编号作正向对照
    (vdir / "电影" / "Hostile").mkdir(parents=True)
    (vdir / "电影" / "Hostile" / "Hostile (2020).mp4").write_bytes(b"probe" * 16)
    (vdir / "电影" / "Hostile" / "Hostile (2020).nfo").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<movie><title>Hostile</title>'
        "<tmdbid>1/../../secret?x=@evil</tmdbid></movie>",
        encoding="utf-8",
    )
    (vdir / "电影" / "Hostile Title").mkdir(parents=True)
    (vdir / "电影" / "Hostile Title" / "Hostile Title (2022).mp4").write_bytes(b"probe" * 16)
    (vdir / "电影" / "Hostile Title" / "Hostile Title (2022).nfo").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<movie><title>Evil&amp;api_key=stolen</title></movie>',
        encoding="utf-8",
    )
    (vdir / "电影" / "Legit").mkdir(parents=True)
    (vdir / "电影" / "Legit" / "Legit (2021).mp4").write_bytes(b"probe" * 16)
    (vdir / "电影" / "Legit" / "Legit (2021).nfo").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<movie><title>Legit</title>'
        "<tmdbid>4242</tmdbid></movie>",
        encoding="utf-8",
    )
    art_hits: list[str] = []

    class _ArtHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # 静音
            pass

        def do_GET(self):
            art_hits.append(self.path)
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    art_srv = ThreadingHTTPServer(("127.0.0.1", 0), _ArtHandler)
    threading.Thread(target=art_srv.serve_forever, daemon=True).start()
    art_base = f"http://127.0.0.1:{art_srv.server_address[1]}"
    jreq("PUT", "/api/v1/video/config",
         {"enabled": True, "source": "nas", "tmdb_key": "probe-key",
          "tmdb_api_base": art_base, "tmdb_image_base": art_base},
         token=admin["access_token"])
    jreq("POST", "/api/v1/video/scan", token=admin["access_token"])
    for _ in range(60):
        _, _, vscan2 = jreq("GET", "/api/v1/video/scan/status", token=admin["access_token"])
        if not vscan2.get("running") and vscan2.get("art_done") == vscan2.get("art_total"):
            break
        time.sleep(0.4)
    hostile_hits = [h for h in art_hits if "evil" in h or ".." in h]
    report(bool(hostile_hits), "恶意 TMDB 编号被拼进上游请求（注入）", str(hostile_hits[:3]))
    report(not any("4242" in h for h in art_hits), "合法编号未发起在线补全（对照组，管线未生效）", str(art_hits[:3]))
    # L9b 标题自动匹配：NFO 标题必须 percent-encode 后进 query，不得原样拼进 URL
    encoded_hit = any("Evil%26api_key%3Dstolen" in h for h in art_hits)
    raw_inject = [h for h in art_hits if "stolen" in h and "Evil%26api_key%3Dstolen" not in h]
    report(bool(raw_inject), "NFO 标题被原样拼进上游查询（注入）", str(raw_inject[:3]))
    report(not encoded_hit, "编码后的标题未进入搜索请求（对照组，标题匹配未生效）", str(art_hits[-3:]))
    art_srv.shutdown()
    shutil.rmtree(vdir, ignore_errors=True)

    print("== N. 种子模块权限/密钥/删除密码 ==")
    qb_srv = ThreadingHTTPServer(("127.0.0.1", 0), _SeedQbHandler)
    threading.Thread(target=qb_srv.serve_forever, daemon=True).start()
    qb_base = f"http://127.0.0.1:{qb_srv.server_address[1]}"
    status, _, seed_conn = jreq(
        "POST", "/api/v1/seeds/connections",
        {"kind": "qbittorrent", "name": "probe-qb", "base_url": qb_base,
         "username": "admin", "secret": "probe-qb-secret",
         "auth_mode": "password", "verify_tls": True, "enabled": True},
        token=admin["access_token"],
    )
    report(status not in (200, 201), "管理员无法创建种子连接（正向对照）", f"HTTP {status}: {seed_conn}")
    seed_id = seed_conn.get("id") if isinstance(seed_conn, dict) else None
    status, _, seed_list = jreq("GET", "/api/v1/seeds/connections", token=admin["access_token"])
    report(
        status == 200 and "probe-qb-secret" in json.dumps(seed_list, ensure_ascii=False),
        "种子连接接口回传明文密钥",
        f"HTTP {status}: {str(seed_list)[:240]}",
    )
    status, _, _ = jreq("GET", "/api/v1/seeds/connections", token=atk_token)
    report(status == 200, "普通用户可读取种子连接配置", f"HTTP {status}（预期 403）")
    status, _, _ = jreq("PATCH", "/api/v1/seeds/settings", {"visibility": "admin_only"}, token=atk_token)
    report(status == 200, "普通用户可修改种子可见范围", f"HTTP {status}（预期 403）")
    status, _, _ = jreq("POST", "/api/v1/seeds/qb/torrents/abc123/action", {"action": "pause"}, token=atk_token)
    report(status == 200, "普通用户可操作 qBittorrent 种子", f"HTTP {status}（预期 403）")
    status, _, _ = jreq(
        "POST", "/api/v1/seeds/qb/torrents/abc123/delete",
        {"password": admin_pw, "delete_files": False, "confirm": True}, token=atk_token,
    )
    report(status == 200, "普通用户可删除 qBittorrent 种子", f"HTTP {status}（预期 403）")
    status, _, out = jreq(
        "POST", "/api/v1/seeds/qb/torrents/abc123/delete",
        {"password": admin_pw, "delete_files": False, "confirm": False}, token=admin["access_token"],
    )
    report(status == 200, "种子删除缺少二次确认仍被执行", f"HTTP {status}: {out}")
    status, _, out = jreq(
        "POST", "/api/v1/seeds/qb/torrents/abc123/delete",
        {"password": "wrong-password", "delete_files": False, "confirm": True}, token=admin["access_token"],
    )
    report(status == 200, "种子删除未校验管理员密码", f"HTTP {status}: {out}")
    status, _, out = jreq(
        "POST", "/api/v1/seeds/qb/torrents/abc123/delete",
        {"password": admin_pw, "delete_files": True, "confirm": True}, token=admin["access_token"],
    )
    report(
        status != 200 or "deleteFiles=true" not in _SeedQbHandler.deleted_body,
        "种子删除文件参数未透传给 qBittorrent",
        f"HTTP {status}, body={_SeedQbHandler.deleted_body[:120]}",
    )
    status, _, out = jreq(
        "POST", "/api/v1/seeds/connections",
        {"kind": "qbittorrent", "name": "probe-ssrf",
         "base_url": "http://169.254.169.254", "username": "admin",
         "secret": "x", "auth_mode": "password", "verify_tls": True, "enabled": True},
        token=admin["access_token"],
    )
    report(status in (200, 201), "种子连接允许云元数据地址", f"HTTP {status}: {out}")
    if seed_id:
        jreq("DELETE", f"/api/v1/seeds/connections/{seed_id}", token=admin["access_token"])
    qb_srv.shutdown()

    print("== M. 接入服务删除防护（启用中不得删除） ==")
    # M1/M2 用一次性来源验证：创建 → 启用态删除必须被拒 → 停用后删除必须成功
    status, _, created = jreq("POST", "/api/v1/sources",
                              {"name": "probe-del-src", "type": "api", "kind": "sms"},
                              token=atk_token)
    assert status in (200, 201), created
    sid = created.get("id") or created.get("source", {}).get("id")
    assert sid, created
    status, _, out = jreq("DELETE", f"/api/v1/sources/{sid}", token=atk_token)
    report(status in (200, 201, 204), "启用中的接入服务被直接删除（未经停用）",
           f"HTTP {status}（预期 400：{out.get('detail', out)}）")
    status, _, _ = jreq("PATCH", f"/api/v1/sources/{sid}", {"is_active": False}, token=atk_token)
    assert status == 200, "停用来源失败"
    status, _, out = jreq("DELETE", f"/api/v1/sources/{sid}", token=atk_token)
    report(status != 200, "停用后删除接入服务（对照组）",
           f"HTTP {status}（预期 200：{out.get('detail', out)}）")

    # K5 注册端点限流（bcrypt CPU 防线；K5 放最后——会把本实例 30 次/10 分钟配额打光）
    k_rejected = None
    for i in range(40):
        status, _, _ = jreq("POST", "/api/v1/auth/register", {"username": f"probebulk{i}", "password": "ProbeBulk1"})
        if status == 429:
            k_rejected = i
            break
    report(k_rejected is None, "注册端点无限流（批量注册未被拒）",
           f"probebulk 第 {k_rejected} 次被拒（预期 30 次内 429）")

    vulns = [r for r in _results if r[0]]
    print(f"\n===== 结论：{len(vulns)} 项攻击成功 / {len(_results)} 项检查 =====")
    for v in vulns:
        print(f"  - {v[1]}")
    sys.exit(1 if vulns else 0)


if __name__ == "__main__":
    main()
