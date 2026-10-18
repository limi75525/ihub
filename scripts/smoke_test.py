"""iHub 后端冒烟自测：无需第三方依赖（标准库 urllib + sqlite3），针对本机运行中的实例。

用法：
    # 终端 1：用临时数据目录起服务（勿连真实 data/）
    IHUB_DATA_DIR=./.smoke-data IHUB_SECRET_KEY=smoketest \
        .venv/Scripts/python -m uvicorn app.main:app --port 18766
    # 终端 2：
    .venv/Scripts/python scripts/smoke_test.py http://127.0.0.1:18766

覆盖：注册/登录、口令长度策略、设备签名推送（含重放与异常时间戳）、
消息列表对脏数据的容忍、邮箱拉取失败回报、昵称/头像权限、限流不采信伪造头。
"""
import hashlib
import hmac
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18766").rstrip("/")
DB = os.environ.get("IHUB_SMOKE_DB", ".smoke-data/ihub.db")
CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

passed = failed = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  [ok]   {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} {detail}")


def call(method: str, path: str, body=None, token: str | None = None, headers=None):
    """返回 (status, 解析后的 JSON 或原始文本)"""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        status = e.code
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw


def sign(device_id: str, secret: str, ts: int, nonce: str, body: bytes,
         sha_upper: bool = False) -> str:
    body_sha = hashlib.sha256(body).hexdigest()
    if sha_upper:
        body_sha = body_sha.upper()      # LuatOS 的 crypto.sha256() 就是大写
    return hmac.new(
        secret.encode(), f"{device_id}\n{ts}\n{nonce}\n{body_sha}".encode(), hashlib.sha256
    ).hexdigest()


def main() -> int:
    suffix = str(int(time.time()))
    user = f"smoke{suffix}"
    pwd = "smoke-pass-123"

    print("== 健康检查 ==")
    st, body = call("GET", "/api/health")
    check("GET /api/health", st == 200 and body.get("ok") is True, str(body))

    # 端到端反代头检查：应用声明「不采信代理头」时，回显的 client_ip 就不能来自请求头。
    # uvicorn 默认开启 --proxy-headers 且信任 127.0.0.1，本机代理场景下会抢在应用之前
    # 用 X-Forwarded-For 改写客户端地址（启动命令必须带 --no-proxy-headers）。
    spoof = "203.0.113.77"
    st, body = call("GET", "/api/health", headers={"X-Forwarded-For": spoof, "X-Real-IP": spoof})
    check(
        "伪造代理头不影响限流维度（需 --no-proxy-headers 启动）",
        body.get("trust_proxy_headers") is True or body.get("client_ip") != spoof,
        f"client_ip={body.get('client_ip')} trust={body.get('trust_proxy_headers')}",
    )

    print("== 口令策略（bcrypt 72 字节上限，超长应 4xx 而非 500）==")
    st, _ = call("POST", "/api/v1/auth/register", {"username": user, "password": "a" * 100})
    check("超长口令注册返回 4xx", 400 <= st < 500, f"status={st}")
    st, body = call("POST", "/api/v1/auth/register", {"username": user, "password": pwd})
    check("正常注册成功", st == 200 and "access_token" in body, f"status={st} {body}")
    if st != 200:
        return 1
    token = body["access_token"]
    media_key = body["media_key"]

    print("== 用户/接入源/设备 ==")
    st, me = call("GET", "/api/v1/auth/me", token=token)
    check("GET /auth/me", st == 200 and me["username"] == user, f"status={st} {me}")
    st, src = call("POST", "/api/v1/sources", {"name": "冒烟 API", "type": "api"}, token=token)
    check("创建 API 接入源", st in (200, 201) and src.get("id"), f"status={st} {src}")
    st, dev = call(
        "POST", "/api/v1/devices/register",
        {"name": "冒烟设备", "kind": "notify", "source_id": src["id"]}, token=token,
    )
    check("注册设备", st == 200 and dev.get("device_id"), f"status={st} {dev}")
    did, dsecret = dev["device_id"], dev["device_secret"]

    print("== 签名推送 ==")

    def _push(raw: bytes, ts: int, nonce: str, sha_upper: bool = False):
        req = urllib.request.Request(BASE + "/api/v1/ingest/device", data=raw, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Device-Id", did)
        req.add_header("X-Timestamp", str(ts))
        req.add_header("X-Nonce", nonce)
        req.add_header("X-Signature", sign(did, dsecret, ts, nonce, raw, sha_upper))
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    st, body = _push(json.dumps({"title": "冒烟", "content": "推送正文"}).encode(), int(time.time()), f"n{time.time_ns()}")
    check("正常推送落消息", st == 200 and body.get("ok") and not body.get("duplicate"), f"{st} {body}")

    # 异常时间戳（超大值）应正常入库（忽略上报时间）而不是 500
    raw = json.dumps({"title": "异常时间", "content": "时间戳超大", "timestamp": 99999999999999}).encode()
    st, body = _push(raw, int(time.time()), f"n{time.time_ns()}")
    check("异常时间戳不 500", st == 200 and body.get("ok"), f"{st} {body}")

    # 兼容性：设备端把 sha256 写成大写时也应通过（LuatOS 默认行为）
    raw = json.dumps({"title": "大写哈希", "content": "LuatOS 风格签名"}).encode()
    st, body = _push(raw, int(time.time()), f"up{time.time_ns()}", sha_upper=True)
    check("sha256 大写哈希也能通过（兼容 LuatOS）", st == 200 and body.get("ok"), f"{st} {body}")

    # 重放同一 nonce 应被拒
    raw = json.dumps({"title": "重放", "content": "重放测试"}).encode()
    ts, nonce = int(time.time()), f"replay{time.time_ns()}"
    _push(raw, ts, nonce)
    st, _ = _push(raw, ts, nonce)
    check("nonce 重放被拒（401）", st == 401, f"status={st}")

    print("== 消息读取与脏数据容忍 ==")
    st, lst = call("GET", "/api/v1/messages?page_size=5", token=token)
    check("消息列表可用", st == 200 and len(lst.get("items", [])) >= 2, f"status={st}")
    msg_id = lst["items"][0]["id"] if lst.get("items") else None

    if msg_id and os.path.exists(DB):
        con = sqlite3.connect(DB)
        con.execute(
            "UPDATE messages SET extra='{坏 JSON', attachments='{\"a\":1}' WHERE id=?", (msg_id,)
        )
        con.commit()
        con.close()
        st, _ = call("GET", "/api/v1/messages?page_size=5", token=token)
        check("脏 extra/attachments 不致命（列表）", st == 200, f"status={st}")
        st, _ = call("GET", f"/api/v1/messages/{msg_id}", token=token)
        check("脏 extra/attachments 不致命（详情）", st == 200, f"status={st}")
        st, _ = call(
            "GET", f"/api/v1/messages/{msg_id}/attachments/0?token={media_key}"
        )
        check("脏 attachments 取附件返回 404", st == 404, f"status={st}")

    print("== 邮箱拉取失败回报 ==")
    # 创建接口会先测连接，无法用它造出「连不上」的来源：直接写库
    import datetime as _dt

    con = sqlite3.connect(DB)
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
    plain_id = con.execute(
        "INSERT INTO sources (user_id, name, type, token, imap_host, imap_port, imap_ssl,"
        " email_account, email_password, poll_interval, folder, last_uid, uidvalidity,"
        " is_active, is_deleted, created_at, sort_order) VALUES (?,?,'email',?,?,?,1,?,?,120,'INBOX',0,0,1,0,?,?)",
        (me["id"], "冒烟邮箱-明文", f"tok{suffix}a", "127.0.0.1", 1, "nobody@example.com", "plain", now, 0),
    ).lastrowid
    broken_id = con.execute(
        "INSERT INTO sources (user_id, name, type, token, imap_host, imap_port, imap_ssl,"
        " email_account, email_password, poll_interval, folder, last_uid, uidvalidity,"
        " is_active, is_deleted, created_at, sort_order) VALUES (?,?,'email',?,?,?,1,?,?,120,'INBOX',0,0,1,0,?,?)",
        (me["id"], "冒烟邮箱-密文", f"tok{suffix}b", "127.0.0.1", 1,
         "nobody@example.com", "gAAAAA" + "x" * 100, now, 0),
    ).lastrowid
    con.commit()
    con.close()

    st, body = call("POST", f"/api/v1/sources/{plain_id}/poll", token=token)
    check("单源拉取回报失败原因", st == 200 and body.get("ok") is False and body.get("error"),
          f"{st} {body}")
    st, body = call("POST", "/api/v1/sources/poll-all", token=token)
    check("poll-all 聚合 ok 反映失败", st == 200 and body.get("ok") is False, f"{st} {body}")

    print("== 权限与限流 ==")
    st, _ = call("PATCH", f"/api/v1/users/{me['id']}", {"password": "b" * 100}, token=token)
    check("管理员改密超长口令被拒（4xx）", 400 <= st < 500, f"status={st}")
    st, _ = call("GET", f"/api/v1/users/avatar/{me['id']}?token={media_key}")
    check("本人头像可读", st in (200, 404), f"status={st}")

    # 伪造 X-Real-IP 不能绕过账号锁定（默认不采信代理头）
    victim = f"victim{suffix}"
    for i in range(5):
        call("POST", "/api/v1/auth/login", {"username": victim, "password": "wrong"},
             headers={"X-Real-IP": f"203.0.113.{i + 1}"})
    st, body = call("POST", "/api/v1/auth/login", {"username": victim, "password": "wrong"},
                    headers={"X-Real-IP": "203.0.113.99"})
    check("伪造 X-Real-IP 无法绕过锁定（429）", st == 429, f"status={st} {body}")

    st, _ = call("POST", "/api/v1/auth/login", {"username": user, "password": "wrong"})
    check("错误口令返回 401", st == 401, f"status={st}")
    st, _ = call("POST", "/api/v1/auth/login", {"username": user, "password": pwd})
    check("正确口令登录成功", st == 200, f"status={st}")

    print("== 进程内直接校验 ==")
    os.environ["IHUB_DATA_DIR"] = os.path.dirname(os.path.abspath(DB))
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from pathlib import Path

    from app.core.config import settings as app_settings
    from app.db.session import SessionLocal
    from app.models.message import Message
    from app.models.system_setting import set_setting
    from app.services.imap_service import last_error, poll_source
    from app.services.retention import run_retention_cleanup

    # 密文解不开时必须直接报错，而不是把密文当密码去登录邮箱
    n = poll_source(broken_id, limit=1)
    check("密文授权码不尝试登录且明确报错",
          n == 0 and "授权码无法解密" in (last_error(broken_id) or ""),
          f"n={n} err={last_error(broken_id)}")

    # 代理头解析：开启 TRUST_PROXY_HEADERS 后必须取 X-Forwarded-For 的最右侧可信值，
    # 客户端伪造在左侧的地址不能生效（Go/nginx/Caddy 反代都把真实客户端追加在末尾）
    from app.core.netutil import client_ip as resolve_ip
    from starlette.requests import Request as _Req

    def mk(headers: list[tuple[str, str]], peer: str = "192.168.1.3"):
        raw = [(k.encode(), v.encode()) for k, v in headers]
        return _Req({
            "type": "http", "method": "GET", "path": "/", "query_string": b"",
            "headers": raw, "client": (peer, 4321),
        })

    app_settings.TRUST_PROXY_HEADERS = False
    check("默认不采信代理头",
          resolve_ip(mk([("x-real-ip", "9.9.9.9")])) == "192.168.1.3",
          resolve_ip(mk([("x-real-ip", "9.9.9.9")])))

    app_settings.TRUST_PROXY_HEADERS = True
    app_settings.TRUSTED_PROXY_HOPS = 1
    check("取 XFF 最右侧（反代追加的真实地址）",
          resolve_ip(mk([("x-forwarded-for", "1.2.3.4, 203.0.113.7")])) == "203.0.113.7",
          resolve_ip(mk([("x-forwarded-for", "1.2.3.4, 203.0.113.7")])))
    check("客户端伪造的 XFF/X-Real-IP 不能覆盖真实地址",
          resolve_ip(mk([("x-forwarded-for", "1.2.3.4, 203.0.113.7"), ("x-real-ip", "9.9.9.9")]))
          == "203.0.113.7",
          resolve_ip(mk([("x-forwarded-for", "1.2.3.4, 203.0.113.7"), ("x-real-ip", "9.9.9.9")])))
    check("无 XFF 时回退 X-Real-IP",
          resolve_ip(mk([("x-real-ip", "203.0.113.9")])) == "203.0.113.9",
          resolve_ip(mk([("x-real-ip", "203.0.113.9")])))
    check("非法/垃圾头回退 TCP 对端",
          resolve_ip(mk([("x-forwarded-for", "unknown"), ("x-real-ip", "not-an-ip")])) == "192.168.1.3",
          resolve_ip(mk([("x-forwarded-for", "unknown")])))
    app_settings.TRUSTED_PROXY_HOPS = 2
    check("HOPS=2 时取右起第二个（CDN + 本机反代）",
          resolve_ip(mk([("x-forwarded-for", "1.2.3.4, 203.0.113.7, 198.51.100.9")])) == "203.0.113.7",
          resolve_ip(mk([("x-forwarded-for", "1.2.3.4, 203.0.113.7, 198.51.100.9")])))
    check("带端口的 IPv4/IPv6 能正确解析",
          resolve_ip(mk([("x-real-ip", "203.0.113.9:5555")])) == "203.0.113.9"
          and resolve_ip(mk([("x-real-ip", "[2001:db8::1]:443")])) == "2001:db8::1",
          resolve_ip(mk([("x-real-ip", "[2001:db8::1]:443")])))
    app_settings.TRUST_PROXY_HEADERS = False
    app_settings.TRUSTED_PROXY_HOPS = 1

    # 保留期清理：过期消息的附件文件必须一并回收（否则磁盘只增不减）
    data_root = Path(app_settings.DATA_DIR).resolve()
    att_dir = data_root / "attachments" / str(src["id"]) / "smokeattach"
    att_dir.mkdir(parents=True, exist_ok=True)
    att_file = att_dir / "smoke.txt"
    att_file.write_text("x", encoding="utf-8")
    old = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=10)
    db = SessionLocal()
    m = Message(
        user_id=me["id"], source_id=src["id"], channel="api", sender="s",
        content_text="过期消息", dedup_hash=f"smoke{suffix}",
        attachments=json.dumps([{
            "filename": "smoke.txt", "size": 1, "content_type": "text/plain",
            "path": str(att_file.relative_to(data_root)),
        }], ensure_ascii=False),
        received_at=old, created_at=old,
    )
    db.add(m)
    db.commit()
    msg_id = m.id
    db.close()

    set_setting("retention_days", "1")
    deleted = run_retention_cleanup()
    set_setting("retention_days", "0")
    db = SessionLocal()
    still_there = db.get(Message, msg_id) is not None
    db.close()
    check("保留期清理删除附件文件与行",
          deleted >= 1 and not att_file.exists() and not att_dir.exists() and not still_there,
          f"deleted={deleted} file={att_file.exists()} dir={att_dir.exists()} row={still_there}")

    print(f"\n通过 {passed} 项，失败 {failed} 项")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
