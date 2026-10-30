"""头像库：企业分组（LogoGroup）+ 匹配规则（LogoRule）管理。

数据模型：一个企业一个分组（名称 + 默认头像），分组下多条匹配规则
（企业名称/签名 + 号码/邮箱地址）。规则可另设「精确头像」覆盖同企业
不同部门/子品牌（如 美团外卖 vs 美团），未设置时回退企业默认头像。

消息侧匹配降级链见 messages._match_logo：
号码/邮箱精确 → 签名精确 → 签名前缀 → 邮箱@域名。
导入导出为 ZIP（manifest.json + images/）；同时兼容导入 v1 旧版单表格式。
"""

import io
import json
import logging
import threading
import urllib.request
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.auth import sanitize_svg
from app.core.deps import get_current_user, get_media_user
from app.core.netutil import safe_logo_url
from app.models.system_setting import get_setting
from app.models.transfer_item import TransferItem
from app.core.timeutil import as_utc
from app.db.session import get_db
from app.models.logo_group import LogoGroup
from app.models.logo_rule import LogoRule
from app.models.user import User
from app.services.logo_urls import file_url
from app.services.uploads import read_limited, save_unique
from app.core import data_dirs

router = APIRouter(prefix="/logos", tags=["logos"])

logger = logging.getLogger(__name__)

# 在线头像缓存线程上限：反复保存带外链的规则时不再无限开线程
_CACHE_SEM = threading.Semaphore(4)

ALLOWED_LOGO_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
    "image/svg+xml": ".svg",
}
# ZIP 导入可接受的图片后缀：比单图上传宽一档——导出包会把文件库引用的原图
# 原样带回（.jpeg/.gif 是文件库常见后缀），导入若只认 .jpg 会静默丢头像
ZIP_LOGO_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".svg"}
MAX_LOGO_SIZE = 2 * 1024 * 1024  # 导入压缩包内单图的硬上限（ZIP 炸弹防护）
AVATAR_MIN_MB, AVATAR_MAX_MB = 1, 20
MAX_IMPORT_RAW_SIZE = 32 * 1024 * 1024  # 上传的导入文件（ZIP / JSON）上限
MAX_MANIFEST_JSON_SIZE = 4 * 1024 * 1024  # 压缩包内 manifest.json 上限

MANIFEST_NAME = "manifest.json"


def avatar_max_size() -> int:
    """头像本地上传大小上限（字节），可在 设置 → 系统 → 附件上传限制 配置。"""
    from app.models.system_setting import get_int_setting

    return get_int_setting("avatar_max_mb", 2, AVATAR_MIN_MB, AVATAR_MAX_MB) * 1024 * 1024


def _read_zip_entry(zf: zipfile.ZipFile, name: str, limit: int) -> bytes:
    """按上限读取压缩包条目：先整体解压再判断大小会被 zip 炸弹撑爆内存。"""
    with zf.open(name) as fh:
        data = fh.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(400, f"压缩包内 {name} 解压后超过 {limit // 1024 // 1024}MB 上限")
    return data


def _norm_signature(v: str | None) -> str:
    return (v or "").strip()[:64]


def _norm_account(v: str | None) -> str:
    """号码/邮箱地址归一化：邮箱统一小写；号码去空格/短横线/+86。"""
    v = (v or "").strip()
    if "@" in v:
        v = v.lower()
    else:
        v = v.replace(" ", "").replace("-", "").replace("+86", "")
    return v[:256]


def _norm_name(v: str | None) -> str:
    return (v or "").strip()[:128]


def _clean_rule_fields(body: dict) -> dict:
    """归一化规则匹配字段；企业名称与号码/邮箱地址至少填一项。"""
    fields = {
        "signature": _norm_signature(body.get("signature")),
        "account": _norm_account(body.get("account")),
    }
    if not any(fields.values()):
        raise HTTPException(400, "企业名称与号码/邮箱地址至少填写一项")
    return fields


def _group_logo_display(g: LogoGroup) -> str | None:
    return file_url(g.logo_path, f"/api/v1/logos/groups/{g.id}/logo-file", g.logo_url)


def _rule_logo_display(r: LogoRule) -> str | None:
    """规则自己的精确头像（可空）：展示端为空时回退企业默认头像。"""
    return file_url(r.logo_path, f"/api/v1/logos/rules/{r.id}/logo-file", r.logo_url)


def _rule_out(r: LogoRule, with_group: bool = False) -> dict:
    d = {
        "id": r.id,
        "group_id": r.group_id,
        "signature": r.signature,
        "account": r.account,
        "logo": _rule_logo_display(r),
        "logo_kind": "file" if r.logo_path else ("url" if r.logo_url else None),
        "created_at": as_utc(r.created_at),
    }
    if with_group:
        d["group"] = None
    return d


def _group_out(g: LogoGroup, rules: list[LogoRule] | None = None) -> dict:
    return {
        "id": g.id,
        "name": g.name,
        "logo": _group_logo_display(g),
        "logo_kind": "file" if g.logo_path else ("url" if g.logo_url else None),
        "created_at": as_utc(g.created_at),
        "rules": [_rule_out(r) for r in (rules or [])],
    }


def _own_group(db: Session, user: User, group_id: int) -> LogoGroup:
    g = db.get(LogoGroup, group_id)
    if not g or g.user_id != user.id or g.is_deleted:
        raise HTTPException(404, "企业分组不存在")
    return g


def _own_rule(db: Session, user: User, rule_id: int) -> LogoRule:
    r = db.get(LogoRule, rule_id)
    if not r or r.user_id != user.id or r.is_deleted:
        raise HTTPException(404, "规则不存在")
    return r


def _group_rules(db: Session, user: User, group_id: int) -> list[LogoRule]:
    return (
        db.query(LogoRule)
        .filter(LogoRule.user_id == user.id, LogoRule.group_id == group_id, LogoRule.is_deleted.is_(False))
        .order_by(LogoRule.id.asc())
        .all()
    )


# 每用户上限：防认证用户循环调用灌表（与 devices 100 / nav 200 同思路）
MAX_LOGO_GROUPS_PER_USER = 200
MAX_LOGO_RULES_PER_USER = 500


def _user_group_count(db: Session, user_id: int) -> int:
    return db.query(LogoGroup.id).filter(LogoGroup.user_id == user_id, LogoGroup.is_deleted.is_(False)).count()


def _user_rule_count(db: Session, user_id: int) -> int:
    return db.query(LogoRule.id).filter(LogoRule.user_id == user_id, LogoRule.is_deleted.is_(False)).count()


def _check_group_quota(db: Session, user: User, adding: int = 1) -> None:
    if _user_group_count(db, user.id) + adding > MAX_LOGO_GROUPS_PER_USER:
        raise HTTPException(400, f"企业分组已达上限（{MAX_LOGO_GROUPS_PER_USER} 个）")


def _check_rule_quota(db: Session, user: User, adding: int = 1) -> None:
    if _user_rule_count(db, user.id) + adding > MAX_LOGO_RULES_PER_USER:
        raise HTTPException(400, f"匹配规则已达上限（{MAX_LOGO_RULES_PER_USER} 条）")


def _dup_group(db: Session, user: User, name: str, exclude_id: int | None = None):
    q = db.query(LogoGroup).filter(LogoGroup.user_id == user.id, LogoGroup.name == name)
    if exclude_id:
        q = q.filter(LogoGroup.id != exclude_id)
    return q


def _dup_rule(db: Session, user: User, group_id: int, fields: dict, exclude_id: int | None = None):
    q = db.query(LogoRule).filter(
        LogoRule.user_id == user.id,
        LogoRule.group_id == group_id,
        LogoRule.signature == fields["signature"],
        LogoRule.account == fields["account"],
    )
    if exclude_id:
        q = q.filter(LogoRule.id != exclude_id)
    return q


# ---------------- 企业分组 ----------------


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    logo_url: str | None = None
    library_file_id: int | None = None  # 引用文件库中的图片


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    logo_url: str | None = None
    library_file_id: int | None = None
    clear_logo: bool = False  # 清除当前头像（文件/外链一并清）


class RuleCreate(BaseModel):
    signature: str | None = None
    account: str | None = None
    logo_url: str | None = None
    library_file_id: int | None = None


class RuleUpdate(BaseModel):
    signature: str | None = None
    account: str | None = None
    logo_url: str | None = None
    library_file_id: int | None = None
    clear_logo: bool = False  # 清除规则的「精确头像」，回退企业默认


class RuleBatchCreate(BaseModel):
    """批量添加成员规则（同一企业默认头像）。items 为匹配字段列表。"""

    items: list[dict] = Field(min_length=1, max_length=100)


@router.get("/groups")
def list_groups(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """企业分组列表（含成员规则），前端卡片列表与详情页共用。"""
    groups = (
        db.query(LogoGroup)
        .filter(LogoGroup.user_id == user.id, LogoGroup.is_deleted.is_(False))
        .order_by(LogoGroup.created_at.desc(), LogoGroup.id.desc())
        .all()
    )
    rules = (
        db.query(LogoRule)
        .filter(LogoRule.user_id == user.id, LogoRule.is_deleted.is_(False))
        .order_by(LogoRule.id.asc())
        .all()
    )
    by_group: dict[int, list[LogoRule]] = {}
    for r in rules:
        by_group.setdefault(r.group_id, []).append(r)
    return [_group_out(g, by_group.get(g.id, [])) for g in groups]


@router.post("/groups")
def create_group(
    body: GroupCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    name = _norm_name(body.name)
    if not name:
        raise HTTPException(400, "请填写企业名称")
    if _dup_group(db, user, name).first():
        raise HTTPException(409, "同名企业已存在")
    _check_group_quota(db, user)
    g = LogoGroup(user_id=user.id, name=name, logo_url=safe_logo_url((body.logo_url or "").strip()) or None)
    db.add(g)
    if body.library_file_id:
        _attach_library_file(db, g, user, body.library_file_id)
    db.commit()
    db.refresh(g)
    if g.logo_url and not g.logo_path and get_setting("image_cache_enabled", "false") == "true":
        _spawn_cache(db, LogoGroup, g.id, g.logo_url)
    return _group_out(g, [])


@router.patch("/groups/{group_id}")
def update_group(
    group_id: int,
    body: GroupUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    g = _own_group(db, user, group_id)
    if body.clear_logo:
        _clear_logo_file(g)
        g.logo_url = None
    if body.name is not None:
        name = _norm_name(body.name)
        if not name:
            raise HTTPException(400, "请填写企业名称")
        if _dup_group(db, user, name, exclude_id=g.id).first():
            raise HTTPException(409, "同名企业已存在")
        g.name = name
    if "logo_url" in body.model_fields_set:
        if g.logo_path and (body.logo_url or "").strip():
            _clear_logo_file(g)
        g.logo_url = safe_logo_url((body.logo_url or "").strip()) or None
    if body.library_file_id:
        _attach_library_file(db, g, user, body.library_file_id)
    db.commit()
    db.refresh(g)
    if g.logo_url and not g.logo_path and get_setting("image_cache_enabled", "false") == "true":
        _spawn_cache(db, LogoGroup, g.id, g.logo_url)
    return _group_out(g, _group_rules(db, user, g.id))


@router.delete("/groups/{group_id}")
def delete_group(group_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """删除企业分组：软删分组并级联软删全部成员规则（回收站按分组整体恢复）。"""
    from datetime import datetime, timezone

    from app.api.v1.recycle import recycle_enabled

    g = _own_group(db, user, group_id)
    now = datetime.now(timezone.utc)
    if recycle_enabled():
        g.name = f"{g.name[:112]}~del{g.id}"
        g.is_deleted = True
        g.deleted_at = now
        for r in _group_rules(db, user, g.id):
            _soft_delete_rule(r, now)
    else:
        for r in _group_rules(db, user, g.id):
            _clear_logo_file(r)
            db.delete(r)
        _clear_logo_file(g)
        db.delete(g)
    db.commit()
    return {"ok": True}


def _soft_delete_rule(r: LogoRule, now) -> None:
    """软删规则：给首个非空匹配字段追加后缀解除 uq_logo_rule 唯一约束。"""
    for field in ("signature", "account"):
        val = getattr(r, field) or ""
        if val:
            setattr(r, field, f"{val[:200]}~del{r.id}")
            break
    r.is_deleted = True
    r.deleted_at = now


# ---------------- 成员规则 ----------------


@router.post("/groups/{group_id}/rules")
def create_rule(
    group_id: int,
    body: RuleCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    g = _own_group(db, user, group_id)
    fields = _clean_rule_fields(body.model_dump())
    if _dup_rule(db, user, g.id, fields).first():
        raise HTTPException(409, "相同的匹配规则已存在")
    _check_rule_quota(db, user)
    r = LogoRule(user_id=user.id, group_id=g.id, logo_url=safe_logo_url((body.logo_url or "").strip()) or None, **fields)
    db.add(r)
    if body.library_file_id:
        _attach_library_file(db, r, user, body.library_file_id)
    db.commit()
    db.refresh(r)
    if r.logo_url and not r.logo_path and get_setting("image_cache_enabled", "false") == "true":
        _spawn_cache(db, LogoRule, r.id, r.logo_url)
    return _rule_out(r)


@router.post("/groups/{group_id}/rules/batch")
def batch_create_rules(
    group_id: int,
    body: RuleBatchCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    g = _own_group(db, user, group_id)
    _check_rule_quota(db, user, adding=len(body.items))
    created, skipped = [], []
    for item in body.items:
        if not isinstance(item, dict):
            skipped.append({"item": item, "reason": "格式无效"})
            continue
        try:
            fields = _clean_rule_fields(item)
        except HTTPException as e:
            skipped.append({"item": item, "reason": e.detail})
            continue
        if _dup_rule(db, user, g.id, fields).first():
            skipped.append({"item": item, "reason": "已存在"})
            continue
        r = LogoRule(user_id=user.id, group_id=g.id, **fields)
        db.add(r)
        created.append(r)
    db.commit()
    for r in created:
        db.refresh(r)
    return {"created": [_rule_out(r) for r in created], "skipped": skipped}


@router.patch("/rules/{rule_id}")
def update_rule(
    rule_id: int,
    body: RuleUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    r = _own_rule(db, user, rule_id)
    if body.clear_logo:
        _clear_logo_file(r)
        r.logo_url = None
    merged = {
        "signature": body.signature if body.signature is not None else r.signature,
        "account": body.account if body.account is not None else r.account,
    }
    fields = _clean_rule_fields(merged)
    if _dup_rule(db, user, r.group_id, fields, exclude_id=r.id).first():
        raise HTTPException(409, "另一条规则已使用相同匹配值")
    r.signature = fields["signature"]
    r.account = fields["account"]
    if "logo_url" in body.model_fields_set:
        if r.logo_path and (body.logo_url or "").strip():
            _clear_logo_file(r)
        r.logo_url = safe_logo_url((body.logo_url or "").strip()) or None
    if body.library_file_id:
        _attach_library_file(db, r, user, body.library_file_id)
    db.commit()
    db.refresh(r)
    if r.logo_url and not r.logo_path and get_setting("image_cache_enabled", "false") == "true":
        _spawn_cache(db, LogoRule, r.id, r.logo_url)
    return _rule_out(r)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from datetime import datetime, timezone

    from app.api.v1.recycle import recycle_enabled

    r = _own_rule(db, user, rule_id)
    if recycle_enabled():
        _soft_delete_rule(r, datetime.now(timezone.utc))
    else:
        _clear_logo_file(r)
        db.delete(r)
    db.commit()
    return {"ok": True}


# ---------------- Logo 文件 / 文件库引用 / 在线缓存（分组与规则共用） ----------------


def _clear_logo_file(obj) -> None:
    """清掉对象自己的 Logo 文件（data/logos/ 下的上传/缓存文件）。
    引用自文件库的图片（data/transfer/...）归文件库所有，不能连带删除。"""
    if obj.logo_path:
        if data_dirs.translate_rel(obj.logo_path.replace("\\", "/")).startswith(data_dirs.AVATARS + "/"):
            p = data_dirs.resolve_rel(obj.logo_path)
            if p:
                p.unlink(missing_ok=True)
        obj.logo_path = None


def _attach_library_file(db, obj, user: User, file_id: int) -> None:
    """让分组/规则引用文件库中的图片（引用而非复制）。"""
    item = (
        db.query(TransferItem)
        .filter(
            TransferItem.id == file_id,
            TransferItem.user_id == user.id,
            TransferItem.kind == "image",
        )
        .first()
    )
    if not item or not item.file_path:
        raise HTTPException(404, "文件库图片不存在")
    _clear_logo_file(obj)
    obj.logo_path = item.file_path
    obj.logo_url = None


def _assert_public_http_url(url: str) -> None:
    """在线头像缓存是普通用户可触发的出站请求，必须拦内网（SSRF）：
    仅允许 http(s)；域名解析出的所有 IP 都不得是私网/环回/链路本地/保留段
    （169.254.169.254 云元数据、127.0.0.1、192.168.* 等一律拒绝）。
    内网判定与接入服务/邮箱等入口共用 core.netutil.host_resolves_private。"""
    from urllib.parse import urlsplit

    from app.core.netutil import host_resolves_private

    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("仅支持 http(s) 地址")
    if host_resolves_private(parts.hostname):
        raise ValueError("地址解析到内网/保留 IP，已拒绝")


class _SSRFCheckedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """urlopen 默认静默跟随重定向——跳转后的地址绕过上面的内网校验。
    重定向的每一跳都重新校验，不合规直接失败。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _cache_remote_logo(model_cls, obj_id: int, url: str) -> None:
    """异步：把在线图片下载进文件库（data/logos/），成功后切换为本地文件。
    使用独立会话；失败静默保留原 URL（记日志便于排查）。
    只允许 http(s) 且不得指向内网：logo_url 是普通用户可任意填写的出站地址，
    file://ftp:// 等协议与 127.0.0.1/169.254.169.254 等内网目标都会变成 SSRF。"""
    if not url.strip().lower().startswith(("http://", "https://")):
        return
    try:
        from urllib.request import Request, build_opener

        _assert_public_http_url(url)
        opener = build_opener(_SSRFCheckedRedirectHandler)
        req = Request(url, headers={"User-Agent": "iHub"})
        with opener.open(req, timeout=15) as resp:
            # 跟随重定向后的最终地址再核验一次（防 DNS/跳转组合绕过）
            _assert_public_http_url(resp.geturl())
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            data = resp.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            return
        ext = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "image/x-icon": ".ico",
            "image/svg+xml": ".svg",
        }.get(ctype)
        if not ext:
            return
        if ext == ".svg":
            # 远端图片同样是用户可控内容：SVG 必须与上传通道同策略清洗
            data = sanitize_svg(data)
            if not data:
                return

        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            obj = db.get(model_cls, obj_id)
            if not obj:
                return
            old_path = obj.logo_path
            obj.logo_path = save_unique(data_dirs.AVATARS, "cache", ext, data)
            db.commit()
            # 旧缓存文件（cache_*）换新后删除，避免反复改 logo_url 灌磁盘
            if old_path and data_dirs.translate_rel(old_path.replace("\\", "/")).startswith(data_dirs.AVATARS + "/cache_"):
                p = data_dirs.resolve_rel(old_path)
                if p:
                    p.unlink(missing_ok=True)
        finally:
            db.close()
    except Exception:
        logger.warning("在线头像缓存失败（保留原 URL）：%s", url, exc_info=True)


def _spawn_cache(db, model_cls, obj_id: int, url: str) -> None:
    if not url:
        return

    def _run():
        with _CACHE_SEM:
            _cache_remote_logo(model_cls, obj_id, url)

    threading.Thread(target=_run, daemon=True).start()


class LibraryFileIn(BaseModel):
    file_id: int


def _use_library_file_endpoint(db, user, obj, file_id: int):
    _attach_library_file(db, obj, user, file_id)
    db.commit()
    return {"ok": True, "logo_kind": "file"}


@router.post("/groups/{group_id}/use-library-file")
def group_use_library_file(
    group_id: int,
    body: LibraryFileIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    g = _own_group(db, user, group_id)
    return _use_library_file_endpoint(db, user, g, body.file_id)


@router.post("/rules/{rule_id}/use-library-file")
def rule_use_library_file(
    rule_id: int,
    body: LibraryFileIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    r = _own_rule(db, user, rule_id)
    return _use_library_file_endpoint(db, user, r, body.file_id)


def _logo_prefix(obj) -> str:
    """分组/规则 Logo 的文件名前缀（随机后缀由 save_unique 补，换图不覆盖旧文件）。"""
    return f"logo_{type(obj).__name__.lower()}_{obj.id}"


def _replace_logo_file(obj, ext: str, data: bytes) -> str:
    """清掉对象原有 Logo（文件 + logo_url）并落盘新文件；返回入库相对路径。

    磁盘写与删除都在线程池里执行（async 端点内不阻塞事件循环）。
    """
    _clear_logo_file(obj)
    obj.logo_url = None
    return save_unique(data_dirs.AVATARS, _logo_prefix(obj), ext, data)


async def _upload_logo_obj(db, user, obj, file: UploadFile) -> None:
    ext = ALLOWED_LOGO_TYPES.get(file.content_type or "")
    if not ext:
        raise HTTPException(400, "仅支持 PNG / JPG / WebP / SVG / ICO 图片")
    limit = await run_in_threadpool(avatar_max_size)
    data = await read_limited(file, limit, f"图片不能超过 {limit // 1024 // 1024}MB（可在 设置 → 系统 → 附件上传限制 调整）")
    if ext == ".svg":
        data = await run_in_threadpool(sanitize_svg, data)
        if not data:
            # 终检未过整份拒绝：不能把空字节写盘当成上传成功
            raise HTTPException(400, "SVG 含有不被允许的内容（脚本/事件属性/javascript: 目标），已拒绝")
    obj.logo_path = await run_in_threadpool(_replace_logo_file, obj, ext, data)
    db.commit()
    db.refresh(obj)


@router.post("/groups/{group_id}/logo")
async def upload_group_logo(
    group_id: int,
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    g = _own_group(db, user, group_id)
    await _upload_logo_obj(db, user, g, file)
    return _group_out(g, _group_rules(db, user, g.id))


@router.post("/rules/{rule_id}/logo")
async def upload_rule_logo(
    rule_id: int,
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    r = _own_rule(db, user, rule_id)
    await _upload_logo_obj(db, user, r, file)
    return _rule_out(r)


def _serve_logo_file(obj):
    if not obj.logo_path:
        raise HTTPException(404, "未上传 Logo")

    path = data_dirs.resolve_rel(obj.logo_path)
    if not path or not path.is_file():
        raise HTTPException(404, "Logo 文件缺失")
    from app.api.v1.auth import media_file_headers

    return FileResponse(path, headers=media_file_headers(path))


@router.get("/groups/{group_id}/logo-file")
def get_group_logo_file(
    group_id: int,
    user: User = Depends(get_media_user),
    db: Session = Depends(get_db),
):
    return _serve_logo_file(_own_group(db, user, group_id))


@router.get("/rules/{rule_id}/logo-file")
def get_rule_logo_file(
    rule_id: int,
    user: User = Depends(get_media_user),
    db: Session = Depends(get_db),
):
    return _serve_logo_file(_own_rule(db, user, rule_id))


# ---------------- 导入 / 导出 ----------------


@router.get("/export")
def export_logos(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """导出头像库为 ZIP：manifest.json（分组 + 规则）+ images/ 内真实图片文件。"""
    groups = (
        db.query(LogoGroup)
        .filter(LogoGroup.user_id == user.id, LogoGroup.is_deleted.is_(False))
        .order_by(LogoGroup.id.asc())
        .all()
    )
    buf = io.BytesIO()
    entries = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for g in groups:
            g_logo_file = None
            if g.logo_path:
                p = data_dirs.resolve_rel(g.logo_path)
                if p and p.is_file():
                    g_logo_file = f"images/group_{g.id}{p.suffix.lower()}"
                    zf.writestr(g_logo_file, p.read_bytes())
            rule_entries = []
            for r in _group_rules(db, user, g.id):
                r_logo_file = None
                if r.logo_path:
                    p = data_dirs.resolve_rel(r.logo_path)
                    if p and p.is_file():
                        r_logo_file = f"images/rule_{r.id}{p.suffix.lower()}"
                        zf.writestr(r_logo_file, p.read_bytes())
                rule_entries.append({
                    "signature": r.signature,
                    "account": r.account,
                    "logo_file": r_logo_file,
                    "logo_url": None if r.logo_path else r.logo_url,
                })
            entries.append({
                "name": g.name,
                "logo_file": g_logo_file,
                "logo_url": None if g.logo_path else g.logo_url,
                "rules": rule_entries,
            })
        zf.writestr(
            MANIFEST_NAME,
            json.dumps({"version": 2, "groups": entries}, ensure_ascii=False, indent=2),
        )
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=ihub-avatars.zip"},
    )


def _read_manifest_from_upload(raw: bytes) -> tuple[zipfile.ZipFile | None, dict]:
    """解析上传文件：ZIP（manifest.json v2 / 旧 rules.json v1）或纯 JSON。
    返回 (ZipFile 或 None, manifest dict)；ZipFile 由调用方读取（内存缓冲，无需关闭）。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
        if MANIFEST_NAME in zf.namelist():
            try:
                data = json.loads(_read_zip_entry(zf, MANIFEST_NAME, MAX_MANIFEST_JSON_SIZE))
            except (ValueError, UnicodeDecodeError):
                raise HTTPException(400, "压缩包 manifest.json 格式错误")
            if not isinstance(data, dict):
                raise HTTPException(400, "manifest.json 格式错误")
            return zf, data
        if "rules.json" in zf.namelist():
            # 旧版 v1 导出包：rules.json + images/，按旧结构转换
            try:
                data = json.loads(_read_zip_entry(zf, "rules.json", MAX_MANIFEST_JSON_SIZE))
            except (ValueError, UnicodeDecodeError):
                raise HTTPException(400, "压缩包 rules.json 格式错误")
            rules = data.get("rules", []) if isinstance(data, dict) else []
            if not isinstance(rules, list):
                raise HTTPException(400, "rules.json 缺少 rules 数组")
            return zf, {"version": 1, "rules": rules}
        raise HTTPException(400, "压缩包缺少 manifest.json")
    except zipfile.BadZipFile:
        pass
    except HTTPException:
        raise

    # ZIP 解析失败 → 尝试纯 JSON
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "无法读取文件，请使用本平台导出的 ZIP 文件")
    if not isinstance(data, dict):
        raise HTTPException(400, "文件格式错误")
    return None, data


def _old_rule_to_group(item: dict) -> tuple[dict, list[dict]]:
    """v1 旧规则条目 → (分组字段, 成员规则条目列表)。"""
    phone = item.get("phone") or ""
    email = item.get("email") or ""
    signature = item.get("signature") or ""
    nickname = item.get("nickname") or ""
    name = (signature or nickname or phone or email or "未命名").strip()[:128]
    rules = []
    if phone:
        rules.append({"signature": signature, "account": phone})
    if email:
        rules.append({"signature": signature or nickname, "account": email})
    if not rules:
        rules.append({"signature": signature or nickname, "account": ""})
    return {"name": name, "logo_file": item.get("logo_file"), "logo_url": item.get("logo_url")}, rules


def _store_logo_file_bytes(zf, logo_file, obj) -> None:
    """把 ZIP 内图片落盘挂到 obj（分组或规则）；SVG 清洗；单图超限只跳过该图。"""
    if zf is None or not isinstance(logo_file, str) or logo_file not in zf.namelist():
        return
    ext = Path(logo_file).suffix.lower()
    if ext not in ZIP_LOGO_EXTS:
        return
    try:
        img = _read_zip_entry(zf, logo_file, MAX_LOGO_SIZE)
    except HTTPException:
        return
    if not img:
        return
    if ext == ".svg":
        # ZIP 导入与单图上传同策略：SVG 剥除脚本/事件属性/javascript: 目标
        img = sanitize_svg(img)
        if not img:
            return
    obj.logo_path = save_unique(data_dirs.AVATARS, _logo_prefix(obj), ext, img)


def _process_import(db: Session, user: User, zf, manifest: dict) -> tuple[list, list]:
    """导入处理循环（flush/清洗/落盘/commit），整体跑在线程池：
    批量写入与文件 IO 不应阻塞事件循环。兼容 v2（groups）与 v1（rules）。"""
    created, skipped = [], []
    if manifest.get("version") == 2 or "groups" in manifest:
        group_items = manifest.get("groups", [])
        if not isinstance(group_items, list):
            raise HTTPException(400, "manifest.json 缺少 groups 数组")
        group_items = group_items[:200]
        _check_group_quota(db, user, adding=len(group_items))
        _check_rule_quota(db, user, adding=sum(len(g.get("rules") or []) if isinstance(g, dict) else 0 for g in group_items))
        for item in group_items:
            if not isinstance(item, dict):
                skipped.append({"item": item, "reason": "格式无效"})
                continue
            name = _norm_name(item.get("name"))
            if not name:
                skipped.append({"item": item, "reason": "缺少企业名称"})
                continue
            if _dup_group(db, user, name).first():
                skipped.append({"item": item, "reason": "同名企业已存在"})
                continue
            g = LogoGroup(user_id=user.id, name=name)
            db.add(g)
            db.flush()
            _store_logo_file_bytes(zf, item.get("logo_file"), g)
            if not g.logo_path and isinstance(item.get("logo_url"), str) and item["logo_url"].strip():
                g.logo_url = safe_logo_url(item["logo_url"].strip())
            rule_items = item.get("rules") or []
            if not isinstance(rule_items, list):
                rule_items = []
            for ri in rule_items[:100]:
                if not isinstance(ri, dict):
                    continue
                try:
                    fields = _clean_rule_fields(ri)
                except HTTPException as e:
                    skipped.append({"item": ri, "reason": e.detail})
                    continue
                if _dup_rule(db, user, g.id, fields).first():
                    skipped.append({"item": ri, "reason": "已存在"})
                    continue
                r = LogoRule(user_id=user.id, group_id=g.id, **fields)
                db.add(r)
                db.flush()
                _store_logo_file_bytes(zf, ri.get("logo_file"), r)
                if not r.logo_path and isinstance(ri.get("logo_url"), str) and ri["logo_url"].strip():
                    r.logo_url = safe_logo_url(ri["logo_url"].strip())
            created.append(g)
        db.commit()
        for g in created:
            db.refresh(g)
        return [_group_out(g, _group_rules(db, user, g.id)) for g in created], skipped

    # v1 旧格式：{"rules": [...]}（纯 JSON 外链头像或 ZIP 内图片）
    old_rules = manifest.get("rules", [])
    if not isinstance(old_rules, list) or not old_rules:
        raise HTTPException(400, "文件中没有头像数据")
    old_rules = old_rules[:200]
    _check_group_quota(db, user, adding=len(old_rules))
    _check_rule_quota(db, user, adding=len(old_rules) * 2)
    for item in old_rules:
        if not isinstance(item, dict):
            skipped.append({"item": item, "reason": "格式无效"})
            continue
        g_fields, rule_items = _old_rule_to_group(item)
        if _dup_group(db, user, g_fields["name"]).first():
            skipped.append({"item": item, "reason": "同名企业已存在"})
            continue
        g = LogoGroup(user_id=user.id, name=g_fields["name"])
        db.add(g)
        db.flush()
        _store_logo_file_bytes(zf, g_fields.get("logo_file"), g)
        if not g.logo_path and isinstance(g_fields.get("logo_url"), str) and g_fields["logo_url"].strip():
            g.logo_url = safe_logo_url(g_fields["logo_url"].strip())
        for ri in rule_items:
            try:
                fields = _clean_rule_fields(ri)
            except HTTPException:
                continue
            if _dup_rule(db, user, g.id, fields).first():
                continue
            r = LogoRule(user_id=user.id, group_id=g.id, **fields)
            db.add(r)
        created.append(g)
    db.commit()
    for g in created:
        db.refresh(g)
    return [_group_out(g, _group_rules(db, user, g.id)) for g in created], skipped


@router.post("/import")
async def import_logos(
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """导入头像库：本平台 v2 ZIP（manifest.json + images/）、v1 旧版 ZIP、或纯 JSON（仅外链）。"""
    raw = await file.read(MAX_IMPORT_RAW_SIZE + 1)
    if len(raw) > MAX_IMPORT_RAW_SIZE:
        raise HTTPException(400, "导入文件不能超过 32MB")
    # ZIP/JSON 解析（含 zip central directory 遍历）不占事件循环
    zf, manifest = await run_in_threadpool(_read_manifest_from_upload, raw)
    created, skipped = await run_in_threadpool(_process_import, db, user, zf, manifest)
    return {"created": created, "skipped": skipped}
