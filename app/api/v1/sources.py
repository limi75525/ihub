import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import encrypt_text
from app.core.deps import get_current_user, get_media_user
from app.core.netutil import safe_logo_url
from app.core.timeutil import as_utc
from app.db.session import get_db
from app.models.message import Message
from app.models.source import Source
from app.models.device import Device
from app.models.system_setting import get_setting_db
from app.models.user import User
from app.scheduler import sync_email_jobs
from app.schemas.message import MessageOut
from app.schemas.source import EmailTestIn, SourceCreate, SourceOut, SourceUpdate
from app.services.imap_service import last_error, poll_source, test_connection
from app.services.logo_urls import file_url
from app.services.uploads import read_limited, save_unique
from app.core import data_dirs

router = APIRouter(prefix="/sources", tags=["sources"])

logger = logging.getLogger(__name__)

MAX_REPARSE = 15  # 重新解析：回退并重拉的最新邮件数
MANUAL_PULL_LIMIT = 30  # 手动拉取（立即拉取）单次最多拉取的最新邮件数


def _assert_email_host_allowed(host: str) -> None:
    """test-email / 邮箱源的创建与修改是登录用户可触发的出站连接（IMAP 协议 SSRF）：
    与在线头像缓存同一策略，目标解析到私网/环回/链路本地/保留段一律拒绝。
    自建内网邮件服务器的部署可设 IHUB_ALLOW_PRIVATE_EMAIL_HOST=true 豁免。"""
    if settings.ALLOW_PRIVATE_EMAIL_HOST:
        return
    from app.core.netutil import host_resolves_private

    private_ip = host_resolves_private(host or "")
    if private_ip:
        raise HTTPException(
            400,
            f"邮箱服务器地址解析到内网/保留 IP（{private_ip}），已拒绝；"
            "自建内网邮件服务可在环境变量设 IHUB_ALLOW_PRIVATE_EMAIL_HOST=true",
        )

# SVG 不允许上传：内联脚本在同源直接访问时可执行（存储型 XSS）
ALLOWED_LOGO_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/x-icon": ".ico",
}
MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2MB


def logo_display(source: Source) -> str | None:
    """上传文件 → 站内取图地址（带 mtime 版本防缓存）；外链 URL → 原样。"""
    return file_url(source.logo_path, f"/api/v1/sources/{source.id}/logo-file", source.logo_url) or None


def _out(db: Session, source: Source, counts: dict | None = None) -> SourceOut:
    """counts：该来源的消息计数 {is_read: n}；列表接口批量预算后传入（免逐来源 N+1）。"""
    if counts is None:
        counts = dict(
            db.query(Message.is_read, func.count(Message.id))
            .filter(Message.source_id == source.id, Message.is_deleted.is_(False))
            .group_by(Message.is_read)
            .all()
        )
    out = SourceOut.model_validate(source)
    out.message_count = sum(counts.values())
    out.unread_count = counts.get(False, 0)
    out.created_at = as_utc(source.created_at)
    out.last_seen_at = as_utc(source.last_seen_at)
    out.last_poll_at = as_utc(source.last_poll_at)
    out.logo = logo_display(source)
    out.logo_kind = "file" if source.logo_path else ("url" if source.logo_url else None)
    return out


def _own_source(db: Session, user: User, source_id: int) -> Source:
    source = db.query(Source).filter(Source.id == source_id, Source.user_id == user.id, Source.is_deleted.is_(False)).first()
    if not source:
        raise HTTPException(404, "接入源不存在")
    return source


def _clear_logo_file(source: Source) -> None:
    if source.logo_path:
        p = data_dirs.resolve_rel(source.logo_path)
        if p:
            p.unlink(missing_ok=True)
        source.logo_path = None


@router.get("", response_model=list[SourceOut])
def list_sources(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Source).filter(Source.user_id == user.id, Source.is_deleted.is_(False))
    # 系统来源（种子事件等）普通用户始终不可见；管理员可在
    # 设置 → 系统 → 隐藏管理员系统通知 中隐藏（默认显示）。
    if user.role != "admin" or get_setting_db(db, "hide_system_sources", "false") == "true":
        q = q.filter(Source.is_system.is_(False))
    sources = q.order_by(Source.sort_order.asc(), Source.id.asc()).all()
    # 一次分组查询取全部来源的消息计数，避免逐来源 COUNT
    counts: dict[int, dict] = {}
    if sources:
        rows = (
            db.query(Message.source_id, Message.is_read, func.count(Message.id))
            .filter(Message.source_id.in_([s.id for s in sources]), Message.is_deleted.is_(False))
            .group_by(Message.source_id, Message.is_read)
            .all()
        )
        for sid, is_read, n in rows:
            counts.setdefault(sid, {})[is_read] = n
    return [_out(db, s, counts.get(s.id, {})) for s in sources]


@router.post("", status_code=201)
def create_source(
    body: SourceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "名称不能为空")
    if db.query(Source).filter(Source.user_id == user.id, Source.name == name, Source.is_deleted.is_(False)).first():
        raise HTTPException(400, f"已存在同名接入服务「{name}」，名称不能重复")
    source = Source(
        user_id=user.id,
        name=name,
        type=body.type,
        token=secrets.token_urlsafe(24),
        imap_host=body.imap_host,
        imap_port=body.imap_port,
        imap_ssl=body.imap_ssl,
        imap_verify_tls=body.imap_verify_tls,
        email_account=body.email_account,
        # 授权码 Fernet 加密落库（拖库不泄露邮箱）
        email_password=encrypt_text(body.email_password) if body.email_password else None,
        poll_interval=body.poll_interval,
        folder=body.folder,
        logo_url=safe_logo_url(body.logo_url),
    )
    if body.type == "email":
        _assert_email_host_allowed(body.imap_host)
        ok, detail = test_connection(
            body.imap_host, body.imap_port or 993, body.imap_ssl,
            body.email_account, body.email_password, body.folder,
            verify_tls=body.imap_verify_tls,
        )
        if not ok:
            raise HTTPException(400, f"邮箱连接失败：{detail}")
    # API 来源按消息类型分流：kind=sms → 短信来源；kind=notify → 通知(api)来源
    if body.type == "api":
        source.type = "sms" if body.kind == "sms" else "api"
    db.add(source)
    db.commit()
    db.refresh(source)
    _sync_jobs(db, user)

    out = _out(db, source)
    # API 来源：同步注册一台设备（唯一鉴权方式），密钥仅此一次返回
    if body.type == "api":
        import secrets as _secrets

        from app.api.v1.devices import _device_out, _encrypt_secret, gen_device_code

        secret = _secrets.token_urlsafe(32)
        device = Device(
            id=gen_device_code(db),
            user_id=user.id,
            name=name,
            kind=body.kind,
            platform="api",
            app_version="web-registered",
            source_id=source.id,
            device_secret_cipher=_encrypt_secret(secret),
        )
        db.add(device)
        db.commit()
        db.refresh(device)
        out_dict = out.model_dump()
        out_dict["device_id"] = device.id
        out_dict["device_secret"] = secret
        out_dict["device"] = _device_out(device).model_dump()
        return out_dict
    return out.model_dump()


@router.patch("/{source_id}", response_model=SourceOut)
def update_source(
    source_id: int,
    body: SourceUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    source = _own_source(db, user, source_id)
    if source.is_system and set(body.model_fields_set) - {"is_active"}:
        raise HTTPException(400, "系统来源只支持启用/停用")
    old_type = source.type
    # 重命名唯一性校验（排除自身）
    if "name" in body.model_fields_set:
        new_name = (body.name or "").strip()
        if not new_name:
            raise HTTPException(400, "名称不能为空")
        dup = (
            db.query(Source)
            .filter(
                Source.user_id == user.id,
                Source.name == new_name,
                Source.is_deleted.is_(False),
                Source.id != source_id,
            )
            .first()
        )
        if dup:
            raise HTTPException(400, f"已存在同名接入服务「{new_name}」，名称不能重复")
        source.name = new_name
    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "logo_url":
            # 清空 logo：移除旧文件与外链；置新 URL：替换并删除本地上传文件
            _clear_logo_file(source)
            source.logo_url = safe_logo_url((value or "").strip()) or None
            continue
        if field == "name":
            continue  # 已在上面单独处理（trim + 查重）
        if field == "email_password":
            # 空串 = 不修改（保留原授权码）。落到库里的字面 "" 会让解密得到 None，
            # 之后被当空密码去登录邮箱，产生难排查的认证失败
            if value:
                source.email_password = encrypt_text(value)
            continue
        setattr(source, field, value)
    # 消息类型变化（sms↔api）时同步绑定设备的 kind
    if source.type in ("sms", "api") and source.type != old_type:
        from app.models.device import Device

        for device in db.query(Device).filter(Device.source_id == source.id).all():
            device.kind = "sms" if source.type == "sms" else "notify"
    # 邮箱来源改了服务器地址：同创建口径拦内网目标（提交前校验，不改原值）
    if source.type == "email" and "imap_host" in body.model_fields_set:
        _assert_email_host_allowed(source.imap_host)
    db.commit()
    db.refresh(source)
    _sync_jobs(db, user)
    return _out(db, source)


@router.delete("/{source_id}")
def delete_source(
    source_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from datetime import datetime, timezone

    from app.api.v1.recycle import recycle_enabled
    from app.models.device import Device
    from app.services.ingest_service import delete_attachments

    source = _own_source(db, user, source_id)
    if source.is_system:
        raise HTTPException(400, "系统来源不可删除，只能停用")
    # 启用中的服务仍在收消息（设备推送/邮箱轮询），禁止直接删除：先停用（is_active=False）
    # 才允许删。前端按钮在启用态置灰并提示，这里兜底拦 API 直调（App 端也是同一入口）。
    if source.is_active:
        raise HTTPException(400, "请先停用服务再删除")
    now = datetime.now(timezone.utc)
    if recycle_enabled():
        # 逻辑删除：来源 + 其全部历史消息 + 绑定设备一并软删（吊销用 is_active，删除用 is_deleted）
        db.query(Message).filter(Message.source_id == source_id).update(
            {"is_deleted": True, "deleted_at": now}, synchronize_session=False
        )
        db.query(Device).filter(Device.source_id == source_id).update(
            {"is_deleted": True, "is_active": False, "deleted_at": now}, synchronize_session=False
        )
        source.is_active = False
        source.is_deleted = True
        source.deleted_at = now
    else:
        # 回收站关闭：来源、历史消息（含附件文件）与绑定设备立即物理删除
        for m in db.query(Message).filter(Message.source_id == source_id).all():
            delete_attachments(m.attachments)
            db.delete(m)
        db.query(Device).filter(Device.source_id == source_id).delete(synchronize_session=False)
        logo = _owned_logo_file(source.logo_path)
        if logo:
            logo.unlink(missing_ok=True)
        db.delete(source)
    db.commit()
    _sync_jobs(db, user)
    return {"ok": True}


def _owned_logo_file(rel: str | None):
    """来源自己上传的 Logo（data/logos/ 下）才可物理删除；库内引用文件与外链不动。"""
    if not rel or not data_dirs.translate_rel(rel.replace("\\", "/")).startswith(data_dirs.AVATARS + "/"):
        return None
    return data_dirs.resolve_rel(rel)


class ReorderIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


@router.post("/reorder")
def reorder_sources(
    body: ReorderIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按给定 id 顺序持久化接入服务排序（设置页拖拽）。"""
    order = {sid: i for i, sid in enumerate(body.ids)}
    rows = (
        db.query(Source)
        .filter(Source.user_id == user.id, Source.id.in_(body.ids), Source.is_deleted.is_(False))
        .all()
    )
    for row in rows:
        row.sort_order = order.get(row.id, 0)
    db.commit()
    return {"ok": True}


def _replace_source_logo(source: Source, ext: str, data: bytes) -> str:
    """清旧 Logo 文件并落盘新文件（磁盘写放线程池）；返回入库相对路径。"""
    _clear_logo_file(source)
    source.logo_url = None
    return save_unique(data_dirs.AVATARS, f"source_{source.id}", ext, data)


@router.post("/{source_id}/logo", response_model=SourceOut)
async def upload_logo(
    source_id: int,
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    source = _own_source(db, user, source_id)
    ext = ALLOWED_LOGO_TYPES.get(file.content_type or "")
    if not ext:
        raise HTTPException(400, "仅支持 PNG / JPG / WebP / ICO 图片")
    data = await read_limited(file, MAX_LOGO_SIZE, "Logo 不能超过 2MB")

    source.logo_path = await run_in_threadpool(_replace_source_logo, source, ext, data)
    db.commit()
    db.refresh(source)
    return _out(db, source)


@router.get("/{source_id}/logo-file")
def get_logo_file(
    source_id: int,
    user: User = Depends(get_media_user),
    db: Session = Depends(get_db),
):
    from fastapi.responses import FileResponse


    source = _own_source(db, user, source_id)
    if not source.logo_path:
        raise HTTPException(404, "未上传 Logo")
    path = data_dirs.resolve_rel(source.logo_path)
    if not path or not path.is_file():
        raise HTTPException(404, "Logo 文件缺失")
    return FileResponse(path)


@router.post("/{source_id}/reparse")
def reparse_source(
    source_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """回退游标重拉最近 15 封邮件，应用最新解析逻辑（正文内嵌图片等）。"""
    source = _own_source(db, user, source_id)
    if source.type != "email":
        raise HTTPException(400, "仅邮箱来源支持重新解析")
    source.last_uid = max(0, source.last_uid - MAX_REPARSE)
    db.commit()
    fetched = poll_source(source.id, limit=MAX_REPARSE)
    db.refresh(source)
    err = last_error(source.id)
    return {"ok": err is None, "refreshed": fetched, "error": err}


@router.post("/test-email")
def test_email(
    body: EmailTestIn,
    user: User = Depends(get_current_user),
):
    _assert_email_host_allowed(body.imap_host)
    ok, detail = test_connection(
        body.imap_host, body.imap_port or 993, body.imap_ssl,
        body.email_account, body.email_password, body.folder,
        verify_tls=body.imap_verify_tls,
    )
    return {"ok": ok, "detail": detail}


@router.post("/{source_id}/poll")
def poll_now(
    source_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    source = _own_source(db, user, source_id)
    if source.type != "email":
        raise HTTPException(400, "仅邮箱来源支持手动拉取")
    fetched = poll_source(source.id, limit=MANUAL_PULL_LIMIT)
    db.refresh(source)
    err = last_error(source.id)
    return {"ok": err is None, "fetched": fetched, "error": err}


@router.post("/poll-all")
def poll_all(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """一次性拉取当前用户全部启用邮箱的最新邮件（刷新按钮 / App 下拉刷新调用）。

    并发拉取避免单个邮箱网络慢拖长整体耗时；总等待上限 12s，
    超时邮箱由后台线程继续完成，新邮件经 SSE 实时推送到前端。
    """
    import concurrent.futures

    email_sources = (
        db.query(Source)
        .filter(
            Source.user_id == user.id,
            Source.type == "email",
            Source.is_active.is_(True),
            Source.is_deleted.is_(False),
        )
        .all()
    )
    if not email_sources:
        return {"ok": True, "fetched": 0, "results": [], "timeout": []}

    results: list[dict] = []
    timeout_names: list[str] = []

    def _poll(source: Source) -> dict:
        try:
            n = poll_source(source.id, limit=MANUAL_PULL_LIMIT)
        except Exception as e:  # poll_source 内部已兜底，这里仅防御未捕获异常
            logger.exception("拉取来源 %s 失败", source.name)
            return {
                "source_id": source.id, "name": source.name, "fetched": 0,
                "ok": False, "error": str(e) or e.__class__.__name__,
            }
        err = last_error(source.id)
        return {"source_id": source.id, "name": source.name, "fetched": n, "ok": err is None, "error": err}

    # 不用 with：executor 退出时的 shutdown(wait=True) 会等所有慢任务跑完，12s 超时形同虚设
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
    try:
        futures = {pool.submit(_poll, s): s for s in email_sources}
        done, not_done = concurrent.futures.wait(
            futures, timeout=12, return_when=concurrent.futures.ALL_COMPLETED
        )
        for f in done:
            results.append(f.result())
        for f in not_done:
            timeout_names.append(futures[f].name)
    finally:
        # 响应按超时返回；已在运行的拉取由后台线程继续完成（poll_source 自开会话，不依赖请求），
        # 尚未开跑的取消本轮，等定时轮询兜底
        pool.shutdown(wait=False, cancel_futures=True)

    return {
        "ok": all(r["ok"] for r in results),
        "fetched": sum(r["fetched"] for r in results),
        "results": results,
        "timeout": timeout_names,
    }


@router.get("/{source_id}/messages", response_model=list[MessageOut])
def source_messages(
    source_id: int,
    limit: int = 20,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    source = _own_source(db, user, source_id)
    msgs = (
        db.query(Message)
        .filter(Message.source_id == source.id, Message.is_deleted.is_(False))
        .order_by(Message.received_at.desc())
        # 负数 limit 在 SQLite 里等于「不限制」，必须先夹到非负
        .limit(max(0, min(limit, 100)))
        .all()
    )
    return [_message_out(m, source.name, logo_display(source)) for m in msgs]


def _message_out(m: Message, source_name: str, source_logo: str | None) -> dict:
    from app.api.v1.messages import _message_out as _serialize

    return _serialize(m, source_name, source_logo)


def _sync_jobs(db: Session, user: User) -> None:
    sync_email_jobs(db.query(Source).all())
