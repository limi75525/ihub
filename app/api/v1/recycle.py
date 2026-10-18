"""回收站：软删数据（消息 / 头像规则 / 接入服务）的查看、恢复与彻底删除。

删除动作是否先进回收站由系统设置 recycle_enabled 决定（默认开启，见 settings.py）：
- 开启：删除 = 软删置位（现状），30 天后由 purge 物理清除；
- 关闭：删除 = 立即物理删除（回收站页仅剩此前遗留的软删数据，仍可恢复/清理）。

恢复「接入服务」时级联恢复其软删的消息与设备行；设备吊销状态（is_active）保持不变，
恢复后如需继续收消息需重新启用/注册设备。
"""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.fsutil import safe_mtime
from app.core.timeutil import as_utc
from app.db.session import get_db
from app.api.v1.books import _purge_book
from app.models.book import Book
from app.models.device import Device
from app.models.logo_rule import LogoRule
from app.models.message import Message
from app.models.source import Source
from app.models.user import User
from app.scheduler import sync_email_jobs
from app.services.ingest_service import delete_attachments
from app.services.purge import PURGE_DAYS

router = APIRouter(prefix="/recycle", tags=["recycle"])

RECYCLE_TYPES = ("message", "logo", "source", "book")


def recycle_enabled() -> bool:
    """回收站开关（系统设置，管理员可改）。读库走独立短会话，供各删除入口调用。"""
    from app.models.system_setting import get_setting

    return get_setting("recycle_enabled", "true") == "true"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _owned_logo(rel: str | None) -> Path | None:
    """规则/来源自己的 Logo 文件（data/logos/ 下）才允许删除；
    引用自文件库的图片（data/transfer/...）归文件库所有，绝不能连带删掉。"""
    if not rel:
        return None
    if not rel.replace("\\", "/").startswith("logos/"):
        return None
    path = (Path(settings.DATA_DIR) / rel).resolve()
    # 前缀校验之外再卡一道 DATA_DIR 包含关系（logos/../x 之类穿越值未来若入库也不致越界删/读）
    try:
        path.relative_to(Path(settings.DATA_DIR).resolve())
    except ValueError:
        return None
    return path


def _soft_deleted(db: Session, user: User, model, extra=None):
    q = db.query(model).filter(model.user_id == user.id, model.is_deleted.is_(True))
    if extra is not None:
        q = q.filter(extra)
    return q


# ---------------- 列表 ----------------


def _message_rows(db: Session, user: User) -> list[dict]:
    rows = (
        _soft_deleted(db, user, Message)
        .order_by(Message.deleted_at.desc(), Message.id.desc())
        .limit(500)
        .all()
    )
    names = dict(
        db.query(Source.id, Source.name).filter(Source.user_id == user.id).all()
    )
    out = []
    for m in rows:
        title = (m.title or "").strip()
        snippet = (m.content_text or "").strip().replace("\n", " ")
        label = title or snippet[:80] or ("短信" if m.channel == "sms" else "消息")
        out.append(
            {
                "id": m.id,
                "type": "message",
                "label": label[:120],
                "detail": f"{names.get(m.source_id, '未知来源')} · {m.sender or '未知发送方'}",
                "deleted_at": as_utc(m.deleted_at) if m.deleted_at else None,
                "original_at": as_utc(m.received_at),
                "has_attachment": m.attachments not in (None, "", "[]"),
            }
        )
    return out


def _logo_rows(db: Session, user: User) -> list[dict]:
    """回收站「头像」类条目 = 软删的企业分组（整组恢复）+ 单独删除的匹配规则。

    id 用字符串前缀区分实体（group:<id> / rule:<id>），恢复与彻底删除按前缀分发；
    随分组级联软删的成员规则不单独列出（由分组条目承载，避免重复与误操作）。"""
    from app.models.logo_group import LogoGroup

    rows = (
        _soft_deleted(db, user, LogoGroup)
        .order_by(LogoGroup.deleted_at.desc(), LogoGroup.id.desc())
        .limit(500)
        .all()
    )
    out = []
    for g in rows:
        rule_count = (
            db.query(LogoRule.id)
            .filter(LogoRule.group_id == g.id, LogoRule.is_deleted.is_(True))
            .count()
        )
        logo = None
        if g.logo_path and _owned_logo(g.logo_path):
            path = _owned_logo(g.logo_path)
            v = safe_mtime(path)
            if v:
                logo = f"/api/v1/recycle/logo-file/group:{g.id}?v={v}"
        out.append(
            {
                "id": f"group:{g.id}",
                "type": "logo",
                "label": g.name.replace(f"~del{g.id}", ""),
                "detail": f"企业分组 · 含 {rule_count} 条匹配规则",
                "logo": logo,
                "deleted_at": as_utc(g.deleted_at) if g.deleted_at else None,
                "original_at": as_utc(g.created_at),
                "has_attachment": bool(g.logo_path),
            }
        )
    # 单独删除的规则（其分组仍有效；分组被删时的级联规则由分组条目承载）
    lone_rules = (
        db.query(LogoRule)
        .join(LogoGroup, LogoRule.group_id == LogoGroup.id)
        .filter(
            LogoRule.user_id == user.id,
            LogoRule.is_deleted.is_(True),
            LogoGroup.is_deleted.is_(False),
        )
        .order_by(LogoRule.deleted_at.desc(), LogoRule.id.desc())
        .limit(500)
        .all()
    )
    for r in lone_rules:
        label = (r.signature or r.account or "（无匹配字段）").replace(f"~del{r.id}", "")
        match_text = "、".join(
            f"{label_zh}：{val}"
            for label_zh, val in (("企业名称", r.signature), ("号码/邮箱", r.account))
            if val
        )
        logo = None
        if r.logo_path and _owned_logo(r.logo_path):
            path = _owned_logo(r.logo_path)
            v = safe_mtime(path)
            if v:
                logo = f"/api/v1/recycle/logo-file/rule:{r.id}?v={v}"
        out.append(
            {
                "id": f"rule:{r.id}",
                "type": "logo",
                "label": label,
                "detail": "匹配规则 · " + (match_text or "无匹配字段"),
                "logo": logo,
                "deleted_at": as_utc(r.deleted_at) if r.deleted_at else None,
                "original_at": as_utc(r.created_at),
                "has_attachment": bool(r.logo_path),
            }
        )
    return out


def _book_rows(db: Session, user: User) -> list[dict]:
    rows = (
        _soft_deleted(db, user, Book)
        .order_by(Book.deleted_at.desc(), Book.id.desc())
        .limit(500)
        .all()
    )
    out = []
    for b in rows:
        author = f" · {b.author}" if b.author else ""
        out.append(
            {
                "id": b.id,
                "type": "book",
                "label": b.title,
                "detail": f"{b.format.upper()} 图书 · 共 {b.chapter_count} 章{author}",
                "logo": None,
                "deleted_at": as_utc(b.deleted_at) if b.deleted_at else None,
                "original_at": as_utc(b.created_at),
                "has_attachment": bool(b.cover_path),
            }
        )
    return out


def _source_rows(db: Session, user: User) -> list[dict]:
    rows = (
        _soft_deleted(db, user, Source)
        .order_by(Source.deleted_at.desc(), Source.id.desc())
        .limit(500)
        .all()
    )
    type_label = {"sms": "短信", "email": "邮件", "api": "通知"}
    # 每来源两条独立查询会放大成 2N 次（N≤500）：分组聚合一次取回计数与「含附件」标记
    source_ids = [s.id for s in rows]
    count_map: dict[int, int] = {}
    att_map: set[int] = set()
    if source_ids:
        base = db.query(
            Message.source_id.label("sid"),
            func.count(Message.id).label("cnt"),
            func.max(
                case((Message.attachments.notin_(("", "[]")), 1), else_=0)
            ).label("has_att"),
        ).filter(Message.source_id.in_(source_ids), Message.is_deleted.is_(True))
        for r in base.group_by(Message.source_id).all():
            count_map[r.sid] = int(r.cnt or 0)
            if int(r.has_att or 0):
                att_map.add(r.sid)
    out = []
    for s in rows:
        msg_count = count_map.get(s.id, 0)
        out.append(
            {
                "id": s.id,
                "type": "source",
                "label": s.name,
                "detail": f"{type_label.get(s.type, s.type)} 接入服务 · 含 {msg_count} 条历史消息",
                "deleted_at": as_utc(s.deleted_at) if s.deleted_at else None,
                "original_at": as_utc(s.created_at),
                "has_attachment": s.id in att_map,
            }
        )
    return out


@router.get("")
def list_recycle(
    type: str = "all",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """回收站列表：type=all/message/logo/source；每类最多返回 500 条。"""
    if type not in ("all", *RECYCLE_TYPES):
        raise HTTPException(400, "未知的类型筛选")
    messages = _message_rows(db, user) if type in ("all", "message") else []
    logos = _logo_rows(db, user) if type in ("all", "logo") else []
    sources = _source_rows(db, user) if type in ("all", "source") else []
    books = _book_rows(db, user) if type in ("all", "book") else []
    items = sorted(
        [*messages, *logos, *sources, *books],
        key=lambda x: x["deleted_at"] or "",
        reverse=True,
    )
    counts = {
        "message": len(messages),
        "logo": len(logos),
        "source": len(sources),
        "book": len(books),
    }
    return {"counts": counts, "items": items, "purge_days": PURGE_DAYS}


@router.get("/logo-file/{entity}")
def recycle_logo_file(
    entity: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """回收站中头像（企业分组/匹配规则）的 Logo 预览（已软删，不能走 /logos 的接口）。"""
    from app.models.logo_group import LogoGroup

    kind, _, raw_id = entity.partition(":")
    try:
        row_id = int(raw_id)
    except ValueError:
        raise HTTPException(404, "Logo 文件缺失")
    if kind == "group":
        obj = (
            db.query(LogoGroup)
            .filter(LogoGroup.id == row_id, LogoGroup.user_id == user.id, LogoGroup.is_deleted.is_(True))
            .first()
        )
    else:
        obj = (
            db.query(LogoRule)
            .filter(LogoRule.id == row_id, LogoRule.user_id == user.id, LogoRule.is_deleted.is_(True))
            .first()
        )
    path = _owned_logo(obj.logo_path) if obj else None
    if not path or not path.is_file():
        raise HTTPException(404, "Logo 文件缺失")
    from fastapi.responses import FileResponse

    from app.api.v1.auth import media_file_headers

    return FileResponse(path, headers=media_file_headers(path))


# ---------------- 恢复 ----------------


class RecycleIdsIn(BaseModel):
    type: str = Field(pattern="^(message|logo|source|book)$")
    # logo 类条目 id 是 "group:<id>" / "rule:<id>" 字符串；其余类型为 int
    ids: list[str | int] = Field(min_length=1, max_length=500)


@router.post("/restore")
def restore_items(
    body: RecycleIdsIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    restored, skipped = 0, []
    if body.type == "message":
        restored = (
            _soft_deleted(db, user, Message, Message.id.in_(body.ids))
            .update({"is_deleted": False, "deleted_at": None}, synchronize_session=False)
        )
    elif body.type == "logo":
        from app.models.logo_group import LogoGroup

        def _unsuffix_rule(rule: LogoRule) -> None:
            for field in ("signature", "account"):
                val = getattr(rule, field) or ""
                marker = f"~del{rule.id}"
                if val.endswith(marker):
                    setattr(rule, field, val[: -len(marker)])

        for raw_id in body.ids:
            kind, _, raw = str(raw_id).partition(":")
            try:
                row_id = int(raw)
            except ValueError:
                skipped.append({"id": raw_id, "reason": "格式无效"})
                continue
            if kind == "group":
                g = _soft_deleted(db, user, LogoGroup, LogoGroup.id == row_id).first()
                if not g:
                    skipped.append({"id": raw_id, "reason": "企业分组不存在"})
                    continue
                # 撤销软删后缀并级联恢复全部成员规则
                marker = f"~del{g.id}"
                if (g.name or "").endswith(marker):
                    g.name = g.name[: -len(marker)]
                g.is_deleted = False
                g.deleted_at = None
                for r in db.query(LogoRule).filter(
                    LogoRule.group_id == g.id, LogoRule.is_deleted.is_(True)
                ).all():
                    _unsuffix_rule(r)
                    r.is_deleted = False
                    r.deleted_at = None
                try:
                    db.commit()
                    restored += 1
                except IntegrityError:
                    db.rollback()
                    db.expire(g)
                    skipped.append({"id": raw_id, "reason": "同名企业已存在"})
            else:
                r = _soft_deleted(db, user, LogoRule, LogoRule.id == row_id).first()
                if not r:
                    skipped.append({"id": raw_id, "reason": "规则不存在"})
                    continue
                g = db.get(LogoGroup, r.group_id)
                if g is None or g.is_deleted:
                    skipped.append({"id": raw_id, "reason": "所属企业已删除，请先恢复该企业"})
                    continue
                _unsuffix_rule(r)
                r.is_deleted = False
                r.deleted_at = None
                try:
                    db.commit()
                    restored += 1
                except IntegrityError:
                    db.rollback()
                    # 同匹配值的规则已重建：回滚本条，保持软删状态
                    db.expire(r)
                    skipped.append({"id": raw_id, "reason": "相同匹配值的规则已存在"})
    elif body.type == "book":
        restored = (
            _soft_deleted(db, user, Book, Book.id.in_(body.ids))
            .update({"is_deleted": False, "deleted_at": None}, synchronize_session=False)
        )
    else:  # source
        sources = _soft_deleted(db, user, Source, Source.id.in_(body.ids)).all()
        for s in sources:
            # 级联恢复其软删的消息与设备（设备吊销状态保持不变）
            db.query(Message).filter(
                Message.source_id == s.id, Message.is_deleted.is_(True)
            ).update({"is_deleted": False, "deleted_at": None}, synchronize_session=False)
            db.query(Device).filter(
                Device.source_id == s.id, Device.is_deleted.is_(True)
            ).update({"is_deleted": False, "deleted_at": None}, synchronize_session=False)
            s.is_deleted = False
            s.deleted_at = None
            restored += 1
        if restored:
            db.commit()
            sync_email_jobs(db.query(Source).all())
            return {"ok": True, "restored": restored, "skipped": skipped}
    db.commit()
    return {"ok": True, "restored": restored, "skipped": skipped}


# ---------------- 彻底删除 ----------------


class PurgeIn(BaseModel):
    """ids 为空 = 彻底删除该 type 全部；type 与 ids 均缺省 = 清空回收站。"""

    type: str | None = Field(default=None, pattern="^(message|logo|source|book)$")
    ids: list[str | int] = Field(default_factory=list, max_length=500)


def _purge_messages(db: Session, user: User, ids: list[int]) -> int:
    q = _soft_deleted(db, user, Message)
    if ids:
        q = q.filter(Message.id.in_(ids))
    rows = q.all()
    for m in rows:
        delete_attachments(m.attachments)
        db.delete(m)
    return len(rows)


def _purge_logos(db: Session, user: User, ids: list[int]) -> int:
    from app.models.logo_group import LogoGroup

    deleted = 0
    for raw_id in ids:
        kind, _, raw = str(raw_id).partition(":")
        try:
            row_id = int(raw)
        except ValueError:
            continue
        if kind == "group":
            g = _soft_deleted(db, user, LogoGroup, LogoGroup.id == row_id).first()
            if not g:
                continue
            # 分组 + 全部（软删）成员规则连带彻底删除
            for r in db.query(LogoRule).filter(LogoRule.group_id == g.id).all():
                path = _owned_logo(r.logo_path)
                if path:
                    path.unlink(missing_ok=True)
                db.delete(r)
            path = _owned_logo(g.logo_path)
            if path:
                path.unlink(missing_ok=True)
            db.delete(g)
            deleted += 1
        else:
            r = _soft_deleted(db, user, LogoRule, LogoRule.id == row_id).first()
            if not r:
                continue
            path = _owned_logo(r.logo_path)
            if path:
                path.unlink(missing_ok=True)
            db.delete(r)
            deleted += 1
    return deleted


def _purge_books(db: Session, user: User, ids: list[int]) -> int:
    q = _soft_deleted(db, user, Book)
    if ids:
        q = q.filter(Book.id.in_(ids))
    rows = q.all()
    for b in rows:
        _purge_book(db, b)
    return len(rows)


def _purge_sources(db: Session, user: User, ids: list[int]) -> int:
    q = _soft_deleted(db, user, Source)
    if ids:
        q = q.filter(Source.id.in_(ids))
    sources = q.all()
    changed = False
    for s in sources:
        for m in db.query(Message).filter(Message.source_id == s.id).all():
            delete_attachments(m.attachments)
            db.delete(m)
        db.query(Device).filter(Device.source_id == s.id).delete(synchronize_session=False)
        path = _owned_logo(s.logo_path)
        if path:
            path.unlink(missing_ok=True)
        db.delete(s)
        changed = True
    if changed:
        db.commit()
        sync_email_jobs(db.query(Source).all())
    return len(sources)


@router.post("/purge")
def purge_items(
    body: PurgeIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.type is None and body.ids:
        raise HTTPException(400, "缺少类型（type）")
    deleted = 0
    if body.type in (None, "message"):
        deleted += _purge_messages(db, user, body.ids if body.type == "message" else [])
    if body.type in (None, "logo"):
        deleted += _purge_logos(db, user, body.ids if body.type == "logo" else [])
    if body.type in (None, "source"):
        deleted += _purge_sources(db, user, body.ids if body.type == "source" else [])
    if body.type in (None, "book"):
        deleted += _purge_books(db, user, body.ids if body.type == "book" else [])
    db.commit()
    return {"ok": True, "deleted": deleted}
