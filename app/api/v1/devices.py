"""设备注册与管理 + HMAC 签名推送通道（统一入口）。

协议：
- 注册：POST /devices/register（需 Web 登录）→ 返回 {device_id(8位码), device_secret}（仅此一次明文）
- 密钥找回：POST /devices/{code}/reveal（验证当前用户密码）→ 重新显示密钥
- 密钥重置：POST /devices/{code}/regenerate → 旧密钥立即失效，返回新密钥
- 推送：POST /ingest/device （统一入口，按设备 kind 分流）
  Headers:
    X-Device-Id    8 位设备码
    X-Timestamp    Unix 秒
    X-Nonce        随机串（防重放，5 分钟内不重复）
    X-Signature    hex(hmac_sha256(secret, sign_string))
  sign_string = f"{device_code}\\n{timestamp}\\n{nonce}\\n{sha256_hex(原始请求体)}"
  kind=sms    → body {"from","msg","timestamp"} → channel=sms
  kind=notify → body {"title","content","sender","extra","timestamp"} → channel=api
"""

import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_text, encrypt_text
from app.core.deps import get_current_user
from app.core.netutil import client_ip
from app.core.ratelimit import (
    INGEST_LIMITER,
    check_login_allowed,
    record_login_failure,
    record_login_success,
)
from app.core.security import verify_password
from app.core.timeutil import utcnow
from app.db.session import get_db
from app.models.device import Device
from app.models.source import Source
from app.models.user import User
from app.schemas.device import DeviceOut
from app.services.ingest_service import create_message

logger = logging.getLogger(__name__)

router = APIRouter(tags=["devices"])

MAX_TIME_SKEW = 300  # 时间窗 ±5 分钟
NONCE_TTL = 300
MAX_INGEST_BODY = 512 * 1024  # 未认证接口的请求体上限
# 签名格式：64 位十六进制。先校验格式再做常数时间比较——含高位字节的 header
# （latin-1 解码）会让 compare_digest 对 str 抛 TypeError → 未处理 500
_SIGNATURE_RE = re.compile(r"^[0-9a-f]{64}$")

# 8 位设备码字符集：大写英文+数字，去除易混（0/O、1/I/L）
CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def gen_device_code(db: Session) -> str:
    for _ in range(50):
        code = "".join(secrets.choice(CODE_CHARS) for _ in range(8))
        if db.get(Device, code) is None:
            return code
    raise HTTPException(500, "设备码生成失败，请重试")


def _encrypt_secret(secret: str) -> str:
    return encrypt_text(secret)


def _decrypt_secret(device: Device) -> str | None:
    return decrypt_text(device.device_secret_cipher)


def _sign_string(device_code: str, ts: int, nonce: str, body_sha: str) -> str:
    return f"{device_code}\n{ts}\n{nonce}\n{body_sha}"


def _device_out(d: Device) -> DeviceOut:
    out = DeviceOut.model_validate(d)
    out.created_at = d.created_at
    out.last_seen_at = d.last_seen_at
    return out


def _get_own_device(db: Session, user: User, code: str) -> Device:
    device = db.get(Device, code)
    if not device or (device.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "设备不存在")
    return device


def _ensure_source(db: Session, device: Device) -> Source:
    """设备绑定的来源被误删时自动重建并重绑。"""
    source = db.get(Source, device.source_id) if device.source_id else None
    if source is None or source.is_deleted:
        source = Source(
            user_id=device.user_id,
            name=f"{device.name} {'短信' if device.kind == 'sms' else '消息'}",
            type="sms" if device.kind == "sms" else "api",
            token=secrets.token_urlsafe(24),
        )
        db.add(source)
        db.flush()
        device.source_id = source.id
    return source


# ---- 防重放：nonce 持久化到 SQLite（重启/多 worker 均有效） ----
_nonce_last_cleanup = 0.0


def _consume_nonce(db: Session, device_code: str, nonce: str) -> bool:
    """插入 nonce 唯一键判定重放；返回 False 表示重复。过期行低频清理。"""
    global _nonce_last_cleanup
    from datetime import timedelta

    from app.models.ingest_nonce import IngestNonce

    now = time.time()
    if now - _nonce_last_cleanup > 60:
        _nonce_last_cleanup = now
        cutoff = utcnow() - timedelta(seconds=NONCE_TTL * 2)
        db.query(IngestNonce).filter(IngestNonce.created_at < cutoff).delete(synchronize_session=False)
    try:
        db.add(IngestNonce(device_code=device_code, nonce=nonce[:64]))
        db.commit()
        return True
    except IntegrityError:
        # 唯一键冲突 = 重放，正常拒绝
        db.rollback()
        return False
    except Exception:
        # 其他 DB 异常同样按拒绝处理（fail-closed），但必须留下可诊断的日志
        db.rollback()
        logger.exception("nonce 写入失败，已按重放拒绝（设备 %s）", device_code)
        return False


class DeviceRegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: str = Field(default="sms", pattern="^(sms|notify)$")
    platform: str = Field(default="android", max_length=16)
    app_version: str = Field(default="", max_length=32)
    # 可选：绑定到已有来源（API 来源创建时同步注册设备）；不传则默认复用/创建短信来源
    source_id: int | None = None


class DevicePatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    is_active: bool | None = None


class RevealIn(BaseModel):
    password: str = Field(min_length=1)


@router.post("/devices/register")
def register_device(
    body: DeviceRegisterIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """注册转发设备（即创建一个接入源），返回一次性设备密钥。"""
    source = None
    if body.source_id:
        source = (
            db.query(Source)
            .filter(Source.id == body.source_id, Source.user_id == user.id, Source.is_deleted.is_(False))
            .first()
        )
        if source is None:
            raise HTTPException(404, "要绑定的来源不存在")
        body.kind = "sms" if source.type == "sms" else "notify"

    dup = (
        db.query(Device)
        .filter(Device.user_id == user.id, Device.is_deleted.is_(False), Device.name == body.name.strip())
        .first()
    )
    if dup:
        # 同名设备 = 重新绑定（换机/重装/吊销后重绑）：重新签发密钥覆盖并重新激活，
        # 旧密钥即刻失效，避免用户必须先去 Web 端手动删除。
        # 注意：此处不能新建来源（孤儿来源正是重复卡片问题的根源）；
        # 指定 source_id 时把设备重绑到该来源，未指定则沿用原绑定。
        secret = secrets.token_urlsafe(32)
        dup.device_secret_cipher = _encrypt_secret(secret)
        dup.app_version = body.app_version
        dup.is_active = True
        if source is not None:
            dup.source_id = source.id
        dup.last_seen_at = utcnow()
        db.commit()
        db.refresh(dup)
        return {
            "device_id": dup.id,
            "device_secret": secret,  # 明文仅此一次返回
            "device": _device_out(dup),
        }

    # 新设备：未指定来源时每台设备独占一个接入服务
    # （多台设备共享同一源会导致来源名错乱；同名设备重绑走上方 dup 覆盖，不会重复建源）
    owned = (
        db.query(func.count(Device.id))
        .filter(Device.user_id == user.id, Device.is_deleted.is_(False))
        .scalar()
        or 0
    )
    if owned >= 100:  # 与 navlinks 的数量上限同思路：认证用户的合法用例远达不到，只防灌表
        raise HTTPException(400, "设备数量已达上限（100 台），请先删除不再使用的设备")
    device_name = body.name.strip()  # 判重与存储统一用 strip 后的值，避免「 X」绕过同名重绑
    if source is None:
        source = Source(
            user_id=user.id,
            name=f"{device_name} {'短信' if body.kind == 'sms' else '通知'}",
            type="sms" if body.kind == "sms" else "api",
            token=secrets.token_urlsafe(24),
        )
        db.add(source)
        db.flush()

    code = gen_device_code(db)
    secret = secrets.token_urlsafe(32)
    device = Device(
        id=code,
        user_id=user.id,
        name=device_name,
        kind=body.kind,
        platform=body.platform,
        app_version=body.app_version,
        source_id=source.id,
        device_secret_cipher=_encrypt_secret(secret),
        last_seen_at=utcnow(),  # 注册即激活
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return {
        "device_id": code,
        "device_secret": secret,  # 明文仅此一次返回
        "device": _device_out(device),
    }


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(Device)
    if user.role != "admin":
        query = query.filter(Device.user_id == user.id)
    query = query.filter(Device.is_deleted.is_(False))
    return [_device_out(d) for d in query.order_by(Device.created_at.desc()).all()]


@router.patch("/devices/{code}", response_model=DeviceOut)
def patch_device(
    code: str,
    body: "DevicePatchIn",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = _get_own_device(db, user, code)
    if body.name is not None:
        new_name = body.name.strip()
        device.name = new_name
        # 同步来源名（接入源卡片与设备展示一致）
        source = db.get(Source, device.source_id) if device.source_id else None
        if source:
            source.name = new_name if source.type != "sms" else f"{new_name} 短信"
    if body.is_active is not None:
        device.is_active = body.is_active
    db.commit()
    db.refresh(device)
    return _device_out(device)


@router.post("/devices/{code}/reveal")
def reveal_secret(
    code: str,
    body: RevealIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """重新查看设备密钥：需验证当前登录用户密码。

    原密码校验复用登录失败计数（独立命名空间）：JWT 被盗时不能借此无限爆破账户密码。
    """
    device = _get_own_device(db, user, code)
    pw_key = f"reveal:{user.username}"
    ip = client_ip(request)
    try:
        check_login_allowed(pw_key)
    except PermissionError as e:
        raise HTTPException(429, str(e))
    if not verify_password(body.password, user.password_hash):
        record_login_failure(pw_key, ip)
        raise HTTPException(401, "密码错误")
    record_login_success(pw_key, ip)
    secret = _decrypt_secret(device)
    if secret is None:
        raise HTTPException(500, "设备密钥损坏，请重置密钥")
    return {"device_id": device.id, "device_secret": secret}


@router.post("/devices/{code}/regenerate")
def regenerate_device_secret(
    code: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """重置设备密钥（旧密钥立即失效），返回新密钥（仅此一次）。"""
    device = _get_own_device(db, user, code)
    secret = secrets.token_urlsafe(32)
    device.device_secret_cipher = _encrypt_secret(secret)
    db.commit()
    return {"device_id": device.id, "device_secret": secret}


@router.delete("/devices/{code}")
def delete_device(
    code: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除设备（逻辑删除）：区别于吊销（is_active=False），30 天后由 purge 物理清除。"""
    from datetime import datetime, timezone

    device = _get_own_device(db, user, code)
    device.is_active = False
    device.is_deleted = True
    device.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


# ---- 统一签名推送入口 ----
class DeviceSmsPush(BaseModel):
    from_: str | None = Field(default=None, alias="from")
    msg: str = Field(min_length=1, max_length=100000)
    timestamp: int | None = None


class DeviceNotifyPush(BaseModel):
    title: str | None = Field(default=None, max_length=256)
    content: str = Field(min_length=1, max_length=100000)
    sender: str | None = Field(default=None, max_length=256)
    extra: dict | None = None
    timestamp: int | None = None


_MIN_MSG_TIMESTAMP = 946684800  # 2000-01-01：早于此视为异常上报


def _client_received_at(ts: int | None) -> datetime | None:
    """客户端上报的消息时间：超出合理范围就忽略（回落到服务器时间），避免 500。"""
    if not ts:
        return None
    if ts < _MIN_MSG_TIMESTAMP or ts > time.time() + 86400:
        logger.warning("设备上报时间戳超出合理范围，已忽略: %s", ts)
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        logger.warning("设备上报时间戳无法解析，已忽略: %s", ts)
        return None


# ---- ingest 接口 IP 级限流（内存）：防止在线枚举 8 位设备码 ----

def _check_ingest_rate(ip: str) -> None:
    """与 /auth 系列同一套滑窗实现（core.ratelimit），被拒的调用不计数也不续期窗口。"""
    try:
        INGEST_LIMITER.hit(ip)
    except PermissionError as e:
        raise HTTPException(429, str(e))


async def _authenticate_push(
    request: Request,
    x_device_id: str | None,
    x_timestamp: str | None,
    x_nonce: str | None,
    x_signature: str | None,
    db: Session,
) -> tuple[Device, Source | None, dict]:
    """签名推送公共校验链路（/ingest/device 与 /ingest/device-test 共用）。

    返回 (设备, 绑定来源或 None, 已解析的 JSON 请求体)。
    鉴权失败统一 401；鉴权通过但来源已停用返回 403（提示先启用服务）。
    """
    client_ip_addr = client_ip(request)
    _check_ingest_rate(client_ip_addr)

    auth_fail = HTTPException(401, "鉴权失败")
    # 鉴权前就限制请求体大小：设备推送只有短信/元数据，512KB 足够。
    # 否则未认证者可用超大请求体把服务端内存吃满（DoS）。
    declared = request.headers.get("content-length")
    if declared and not (declared.isascii() and declared.isdigit()):
        raise HTTPException(400, "非法 Content-Length")
    if declared and int(declared) > MAX_INGEST_BODY:
        raise HTTPException(413, "请求体过大")
    # 边读边限：Content-Length 缺失（chunked）时 request.body() 仍会先缓冲整个请求体，
    # 未认证者可借此打满内存；改为流式读取，超限立即中断。
    raw_size = 0
    body_parts: list[bytes] = []
    async for piece in request.stream():
        raw_size += len(piece)
        if raw_size > MAX_INGEST_BODY:
            raise HTTPException(413, "请求体过大")
        body_parts.append(piece)
    raw_body = b"".join(body_parts)
    if not raw_body or not raw_body.strip():
        raise HTTPException(422, "请求体为空")
    if not (x_device_id and x_timestamp and x_nonce and x_signature):
        raise auth_fail

    device = db.get(Device, (x_device_id or "").strip())
    if not device or device.is_deleted or not device.is_active:
        raise auth_fail

    try:
        ts = int(x_timestamp or "")
    except ValueError:
        raise auth_fail
    if abs(time.time() - ts) > MAX_TIME_SKEW:
        raise auth_fail

    secret = _decrypt_secret(device)
    if secret is None:
        raise HTTPException(500, "设备密钥损坏，请重置密钥")

    body_sha = hashlib.sha256(raw_body).hexdigest()
    # 兼容大小写：LuatOS 的 crypto.sha256() 返回大写十六进制，很多设备脚本会直接把大写哈希
    # 拼进签名串（协议文档写的是小写）。两种大小写都接受——HMAC 输入只差大小写，安全性不变。
    signature = (x_signature or "").lower()
    if not _SIGNATURE_RE.match(signature):
        # 格式不对（含非十六进制/非 ASCII 字符）直接按鉴权失败处理：
        # 既防 compare_digest 对 str 抛 TypeError 变 500，也防畸形签名打进 nonce 表
        raise auth_fail
    for candidate_sha in (body_sha, body_sha.upper()):
        expected = hmac.new(
            secret.encode("utf-8"),
            _sign_string(device.id, ts, x_nonce or "", candidate_sha).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if hmac.compare_digest(expected, signature):
            break
    else:
        raise auth_fail

    # nonce 在验签成功后才消费：先入库的话，仅知 8 位设备码的攻击者就能
    # 消耗任意 nonce，还会把嗅探到的合法推送「抢先重放」成 nonce 冲突丢消息
    if not await run_in_threadpool(_consume_nonce, db, device.id, x_nonce or ""):
        raise auth_fail

    # 来源已删除视为未绑定（由 _ensure_source 重建）；已停用则明确拒绝推送
    source = db.get(Source, device.source_id) if device.source_id else None
    if source is not None and source.is_deleted:
        source = None
    if source is not None and not source.is_active:
        raise HTTPException(403, "该设备所属接入服务已停用，请先在 Web/App 端重新启用")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(422, "请求体 JSON 解析失败")
    if not isinstance(payload, dict):
        raise HTTPException(422, "请求体应为 JSON 对象")
    return device, source, payload


def _apply_push_message(db: Session, device: Device, source: Source | None, payload: dict):
    """验签后的落库段（解析 + create_message + commit），整体放线程池执行。

    create_message 含附件写盘与大事务提交：SQLite 写锁被扫描/清理线程持有时
    commit 最多等 busy_timeout(30s)，在 async 端点里直接跑会把整个事件循环
    （SSE 心跳、健康检查、所有请求）一起拖住。
    """
    received_at = None
    if device.kind == "sms":
        try:
            parsed = DeviceSmsPush.model_validate(payload)
        except Exception:
            # msg 上限 10 万字符，超长内容也会走到这里（区分开便于设备端排查）
            raise HTTPException(422, "短信设备请求体应为 {from, msg}，且内容不超过 10 万字符")
        if not parsed.msg.strip():
            raise HTTPException(422, "短信内容为空")
        received_at = _client_received_at(parsed.timestamp)
        msg = create_message(
            db,
            source,
            channel="sms",
            sender=parsed.from_ or "",
            content_text=parsed.msg,
            received_at=received_at,
            extra={},
        )
    else:
        try:
            parsed = DeviceNotifyPush.model_validate(payload)
        except Exception:
            # content 上限 10 万字符 / title·sender 上限 256，超长内容也会走到这里
            raise HTTPException(422, "通知设备请求体应为 {title, content, sender}，且 content 不超过 10 万字符")
        if not parsed.content.strip():
            raise HTTPException(422, "通知内容为空")
        received_at = _client_received_at(parsed.timestamp)
        msg = create_message(
            db,
            source,
            channel="api",
            sender=parsed.sender or device.name,
            title=parsed.title or "",
            content_text=parsed.content,
            received_at=received_at,
            extra=parsed.extra or {},
        )
    db.commit()
    return msg


@router.post("/ingest/device")
async def device_ingest(
    request: Request,
    x_device_id: str | None = Header(default=None),
    x_timestamp: str | None = Header(default=None),
    x_nonce: str | None = Header(default=None),
    x_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """统一签名推送入口：按设备 kind 分流（sms→短信消息；notify→通知消息）。

    鉴权失败统一返回 401「鉴权失败」，不区分具体原因（防设备码枚举）；
    设备有效但所属接入服务已停用时返回 403（此时应先在 Web/App 重新启用服务）。
    """
    device, source, payload = await _authenticate_push(
        request, x_device_id, x_timestamp, x_nonce, x_signature, db
    )

    def _touch():
        device.last_seen_at = utcnow()
        db.commit()

    await run_in_threadpool(_touch)
    source = source or await run_in_threadpool(_ensure_source, db, device)
    msg = await run_in_threadpool(_apply_push_message, db, device, source, payload)
    return {"ok": True, "duplicate": msg is None, "id": msg.id if msg else None}


@router.post("/ingest/device-test")
async def device_ingest_test(
    request: Request,
    x_device_id: str | None = Header(default=None),
    x_timestamp: str | None = Header(default=None),
    x_nonce: str | None = Header(default=None),
    x_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """连通性测试入口：与 /ingest/device 完全相同的签名校验链路，但不落任何消息。

    供 App「发送测试」按钮验证 设备码/密钥/服务器时间/服务启停 是否配置正确。
    """
    device, source, _ = await _authenticate_push(
        request, x_device_id, x_timestamp, x_nonce, x_signature, db
    )

    def _touch():
        device.last_seen_at = utcnow()
        db.commit()

    await run_in_threadpool(_touch)
    return {
        "ok": True,
        "device_id": device.id,
        "device_name": device.name,
        "source_id": source.id if source else None,
        "source_name": source.name if source else "",
        "server_time": int(time.time()),
    }
