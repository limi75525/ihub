import json
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_media_user
from app.core.fsutil import data_file
from app.core.sqlutil import escape_like
from app.core.timeutil import as_utc
from app.db.session import get_db
from app.models.logo_group import LogoGroup
from app.models.logo_rule import LogoRule
from app.models.message import Message
from app.models.source import Source
from app.models.user import User
from app.schemas.message import BatchActionIn, MessageDetailOut, MessageListOut
from app.services.events import broker
from app.services.logo_urls import file_url

router = APIRouter(prefix="/messages", tags=["messages"])


def _publish_read(user_id: int, ids: list[int] | None, read: bool, all_: bool = False) -> None:
    """已读/未读状态变化广播（SSE）：各端据此原位同步未读点与角标。
    ids=None 且 all_=True 表示「全部标为已读」（read-all 不逐条取 id）。"""
    broker.publish({
        "type": "message.read", "user_id": user_id,
        "ids": ids or [], "read": read, "all": all_,
    })


class MessageFilterParams(BaseModel):
    page: int = 1
    page_size: int = 50
    channel: str | None = None
    source_id: int | None = None
    is_read: bool | None = None
    starred: bool | None = None
    pinned: bool | None = None
    q: str | None = None


def _apply_filters(db: Session, user: User, params: MessageFilterParams):
    # 逻辑删除的行不再参与任何查询/计数/去重外的操作
    q = db.query(Message).filter(
        Message.user_id == user.id, Message.is_deleted.is_(False)
    )
    if params.channel:
        q = q.filter(Message.channel == params.channel)
    if params.source_id:
        q = q.filter(Message.source_id == params.source_id)
    if params.is_read is not None:
        q = q.filter(Message.is_read == params.is_read)
    if params.starred is not None:
        # 与 is_read/pinned 一致的三态语义：starred=false 过滤「未收藏」而非忽略
        q = q.filter(Message.is_starred.is_(params.starred))
    if params.pinned is not None:
        q = q.filter(Message.is_pinned == params.pinned)
    if params.q:
        # 转义 LIKE 通配符：否则 q 含 %/_ 时语义失控（单 % 全表通配，大库全表扫描）
        kw = f"%{escape_like(params.q)}%"
        q = q.filter(
            or_(
                Message.title.ilike(kw, escape="\\"),
                Message.content_text.ilike(kw, escape="\\"),
                Message.sender.ilike(kw, escape="\\"),
            )
        )
    return q


# 短信企业签名：【xxx】 / [xxx]
_SMS_SIGNATURE_RE = re.compile(r"^\s*[【\[]\s*([^】\]]{1,24}?)\s*[】\]]")


def _logo_rules(db: Session, user_id: int) -> tuple[list[LogoRule], dict[int, LogoGroup]]:
    """取用户全部有效匹配规则 + 其所属企业分组（按 id 索引）。"""
    rules = db.query(LogoRule).filter(LogoRule.user_id == user_id, LogoRule.is_deleted.is_(False)).all()
    groups = {
        g.id: g
        for g in db.query(LogoGroup).filter(LogoGroup.user_id == user_id, LogoGroup.is_deleted.is_(False)).all()
    }
    return rules, groups


def _norm_phone(v: str) -> str:
    return (v or "").replace(" ", "").replace("-", "").replace("+86", "")


def _loads_json(raw: str | None, default):
    """容忍脏数据：单条记录的 JSON 损坏不应让整个列表接口 500。"""
    try:
        value = json.loads(raw or "")
    except (ValueError, TypeError):
        return default
    return value if isinstance(value, type(default)) else default


_EMAIL_IN_HEADER_RE = re.compile(r"<([^<>\s]+@[^<>\s]+)>")


def _match_logo(rules: list[LogoRule], groups: dict[int, LogoGroup], m: Message) -> LogoRule | LogoGroup | None:
    """匹配降级链（渠道无关）：号码/邮箱精确 → 签名精确 → 签名前缀 → 邮箱@域名。

    - account：短信=号码（归一化），邮件=发件地址；
    - signature：短信=【】企业签名，邮件=显示名（尖括号前），通知=发方名称；
    - 签名两级中规则企业名优先，随后以分组名兜底（美团 分组天然命中 美团/美团外卖），
      前缀多命中取最长名称（更具体）。
    命中规则未设「精确头像」时由 _avatar_logo 回退企业默认头像；命中分组即企业默认头像。"""
    if m.channel == "sms":
        account = _norm_phone(m.sender or "")
        sig_m = _SMS_SIGNATURE_RE.match(m.content_text or "")
        sig = sig_m.group(1).strip() if sig_m else ""
    elif m.channel == "email":
        extra = _loads_json(m.extra, {})
        account = (extra.get("sender_email") or "").strip().lower()
        sender = (m.sender or "").strip()
        if not account:
            # 兼容「昵称 <addr@dom.com>」形态：取尖括号内的地址
            angled = _EMAIL_IN_HEADER_RE.search(sender)
            account = (angled.group(1) if angled else sender).lower()
            if "@" not in account:
                account = ""
        # 显示名 = 尖括号前的部分（「京东健康 <x@jd.com>」→「京东健康」）
        angled = _EMAIL_IN_HEADER_RE.search(sender)
        if angled:
            sig = sender[: angled.start()].strip()
        elif "@" not in sender:
            sig = sender
        else:
            sig = ""
    else:  # api / notify：发方名称参与签名两级匹配
        account = ""
        sig = (m.sender or "").strip()

    if account:
        for r in rules:
            if r.account and r.account == account:
                return r
    if sig:
        for r in rules:
            if r.signature and r.signature == sig:
                return r
        # 签名前缀（规则）：京东 命中 京东外卖；多命中取最长企业名
        prefix_best: LogoRule | None = None
        for r in rules:
            if r.signature and len(r.signature) < len(sig) and sig.startswith(r.signature):
                if prefix_best is None or len(r.signature) > len(prefix_best.signature):
                    prefix_best = r
        if prefix_best is not None:
            return prefix_best
        # 分组名兜底：企业名本身也参与精确与前缀匹配（美团 → 美团外卖/美团优选）
        for g in groups.values():
            if g.name and g.name == sig:
                return g
        g_best: LogoGroup | None = None
        for g in groups.values():
            if g.name and len(g.name) < len(sig) and sig.startswith(g.name):
                if g_best is None or len(g.name) > len(g_best.name):
                    g_best = g
        if g_best is not None:
            return g_best
    # 邮箱@域名降级：完整地址未命中规则时命中同域名任一规则（team@jd.com → noreply@jd.com 的规则）
    if account and "@" in account:
        domain = account.rsplit("@", 1)[-1]
        if domain:
            for r in rules:
                if r.account and "@" in r.account and r.account.rsplit("@", 1)[-1] == domain:
                    return r
    return None


def _avatar_logo(obj: LogoRule | LogoGroup | None, groups: dict[int, LogoGroup] | None = None) -> str | None:
    """命中规则 → 规则「精确头像」；未设置 → 企业默认头像；命中分组 → 企业默认头像。"""
    if obj is None:
        return None
    if isinstance(obj, LogoGroup):
        return file_url(obj.logo_path, f"/api/v1/logos/groups/{obj.id}/logo-file", obj.logo_url)
    if obj.logo_path or obj.logo_url:
        return file_url(obj.logo_path, f"/api/v1/logos/rules/{obj.id}/logo-file", obj.logo_url)
    g = (groups or {}).get(obj.group_id)
    if g is not None:
        return file_url(g.logo_path, f"/api/v1/logos/groups/{g.id}/logo-file", g.logo_url)
    return None


def _message_out(m: Message, source_name: str = "", source_logo: str | None = None, detail: bool = False, avatar: str | None = None) -> dict:
    atts = _loads_json(m.attachments, [])
    d = {
        "id": m.id,
        "source_id": m.source_id,
        "source_name": source_name,
        "source_logo": source_logo,
        "channel": m.channel,
        "sender": m.sender or "",
        "recipient": m.recipient or "",
        "title": m.title or "",
        # 列表仅做摘要截断减小载荷；详情必须返回全文（截断的纯文本邮件在详情页表现为「内容不完整」）
        "content_text": (m.content_text or "") if detail else (m.content_text or "")[:400],
        "content_html": m.content_html,
        "has_html": bool(m.content_html),
        "attachments": [
            {
                "filename": a.get("filename", ""),
                "size": a.get("size", 0),
                "content_type": a.get("content_type", ""),
            }
            for a in atts
        ],
        "extra": _loads_json(m.extra, {}),
        "avatar": avatar,
        "is_read": m.is_read,
        "is_starred": bool(m.is_starred),
        "is_pinned": bool(m.is_pinned),
        "received_at": as_utc(m.received_at),
        "created_at": as_utc(m.created_at),
    }
    if not detail:
        d.pop("content_html")
    return d


def _source_map(db: Session, user_id: int) -> dict[int, tuple[str, str | None]]:
    rows = (
        db.query(Source.id, Source.name, Source.logo_path, Source.logo_url)
        .filter(Source.user_id == user_id)
        .all()
    )
    return {
        sid: (name, file_url(logo_path, f"/api/v1/sources/{sid}/logo-file", logo_url))
        for sid, name, logo_path, logo_url in rows
    }


@router.get("", response_model=MessageListOut)
def list_messages(
    page: int = 1,
    page_size: int = 50,
    channel: str | None = None,
    source_id: int | None = None,
    is_read: bool | None = None,
    starred: bool | None = None,
    pinned: bool | None = None,
    q: str | None = None,
    order: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    params = MessageFilterParams(
        page=page,
        page_size=page_size,
        channel=channel,
        source_id=source_id,
        is_read=is_read,
        starred=starred,
        pinned=pinned,
        q=q,
    )
    query = _apply_filters(db, user, params)
    total = query.with_entities(func.count(Message.id)).scalar() or 0
    unread = (
        _apply_filters(db, user, params.model_copy(update={"is_read": False}))
        .with_entities(func.count(Message.id))
        .scalar()
        or 0
    )
    # order=time：纯按时间倒序（置顶消息不占据列表头部）——总览消息聚合用，
    # 语义为「最新的 N 条」，置顶消息只有本身足够新才会出现
    if order == "time":
        query = query.order_by(Message.received_at.desc(), Message.id.desc())
    else:
        query = query.order_by(Message.is_pinned.desc(), Message.received_at.desc(), Message.id.desc())
    items = (
        query.offset((page - 1) * page_size).limit(page_size).all()
    )
    src_map = _source_map(db, user.id)
    logo_rules, logo_groups = _logo_rules(db, user.id)
    items_out = []
    for m in items:
        name, logo = src_map.get(m.source_id, ("", None))
        items_out.append(
            _message_out(m, name, logo, avatar=_avatar_logo(_match_logo(logo_rules, logo_groups, m), logo_groups))
        )
    return MessageListOut(total=total, unread=unread, items=items_out)


@router.get("/unread-count")
def unread_count(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    rows = (
        db.query(Message.channel, func.count(Message.id))
        .filter(Message.user_id == user.id, Message.is_read.is_(False), Message.is_deleted.is_(False))
        .group_by(Message.channel)
        .all()
    )
    return {channel: count for channel, count in rows}


@router.post("/read-all")
def read_all(
    channel: str | None = None,
    source_id: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    params = MessageFilterParams(channel=channel, source_id=source_id)
    q = _apply_filters(db, user, params)
    updated = q.filter(Message.is_read.is_(False)).update({"is_read": True}, synchronize_session=False)
    db.commit()
    if updated:
        _publish_read(user.id, None, True, all_=True)
    return {"ok": True, "updated": updated}


@router.get("/ids")
def message_ids(
    channel: str | None = None,
    source_id: int | None = None,
    is_read: bool | None = None,
    starred: bool | None = None,
    pinned: bool | None = None,
    q: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按当前筛选返回全部消息 ID（批量全选用）。"""
    params = MessageFilterParams(
        channel=channel, source_id=source_id, is_read=is_read, starred=starred, pinned=pinned, q=q
    )
    rows = _apply_filters(db, user, params).with_entities(Message.id).all()
    return [r[0] for r in rows]


@router.post("/batch")
def batch_action(
    body: BatchActionIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Message).filter(Message.user_id == user.id, Message.id.in_(body.ids), Message.is_deleted.is_(False))
    if body.action == "delete":
        from app.api.v1.recycle import recycle_enabled
        from app.core.timeutil import utcnow

        if recycle_enabled():
            # 逻辑删除：保留行 30 天（purge 到期物理清除，期间可从回收站恢复）
            count = q.filter(Message.is_deleted.is_(False)).update(
                {"is_deleted": True, "deleted_at": utcnow()}, synchronize_session=False
            )
        else:
            # 回收站关闭：立即物理删除并回收附件
            from app.services.ingest_service import delete_attachments

            rows = q.all()
            for m in rows:
                delete_attachments(m.attachments)
                db.delete(m)
            count = len(rows)
    elif body.action in ("star", "unstar"):
        count = q.update({"is_starred": body.action == "star"}, synchronize_session=False)
    elif body.action in ("pin", "unpin"):
        count = q.update({"is_pinned": body.action == "pin"}, synchronize_session=False)
    else:
        count = q.update({"is_read": body.action == "read"}, synchronize_session=False)
        if body.action in ("read", "unread"):
            _publish_read(user.id, body.ids, body.action == "read")
    db.commit()
    return {"ok": True, "updated": count}


@router.get("/{message_id}", response_model=MessageDetailOut)
def message_detail(
    message_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    m = db.query(Message).filter(Message.id == message_id, Message.user_id == user.id, Message.is_deleted.is_(False)).first()
    if not m:
        raise HTTPException(404, "消息不存在")
    if not m.is_read:
        m.is_read = True
        db.commit()
        _publish_read(user.id, [message_id], True)
    source = db.get(Source, m.source_id)
    logo = None
    if source:
        logo = file_url(source.logo_path, f"/api/v1/sources/{source.id}/logo-file", source.logo_url)
    rules, groups = _logo_rules(db, user.id)
    avatar = _avatar_logo(_match_logo(rules, groups, m), groups)
    return _message_out(m, source.name if source else "", logo, detail=True, avatar=avatar)


@router.get("/{message_id}/attachments/{index}")
def download_attachment(
    message_id: int,
    index: int,
    user: User = Depends(get_media_user),
    db: Session = Depends(get_db),
):
    m = db.query(Message).filter(Message.id == message_id, Message.user_id == user.id, Message.is_deleted.is_(False)).first()
    if not m:
        raise HTTPException(404, "消息不存在")
    atts = _loads_json(m.attachments, [])
    if index < 0 or index >= len(atts):
        raise HTTPException(404, "附件不存在")
    att = atts[index] if isinstance(atts[index], dict) else {}
    if not att.get("path"):
        raise HTTPException(404, "附件文件缺失")
    # data_file：resolve + relative_to 严格判定（防止 data 同级前缀目录如 data-evil 绕过）
    path = data_file(settings.DATA_DIR, att["path"])
    if not path or not path.is_file():
        raise HTTPException(404, "附件文件缺失")
    filename = att.get("filename") or path.name
    return FileResponse(path, filename=filename)
