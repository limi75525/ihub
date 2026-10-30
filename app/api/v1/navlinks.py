from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.auth import ALLOWED_IMAGE_TYPES
from app.core.netutil import safe_logo_url
from app.core.timeutil import as_utc
from app.core.deps import get_current_user, get_media_user
from app.db.session import get_db
from app.models.nav_link import NavLink
from app.models.user import User
from app.services.logo_urls import file_url
from app.services.uploads import read_limited, save_unique
from app.core import data_dirs

router = APIRouter(prefix="/nav", tags=["nav"])

MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2MB，与头像一致
MAX_NAV_COUNT = 200


def _logo_out(db_less_link: NavLink) -> str | None:
    """展示地址：上传的走带 media 鉴权的接口；在线地址原样返回（展示端按头像库规则补全）。
    上传文件已丢失时回退在线地址（require_file）。"""
    return file_url(
        db_less_link.logo_path,
        f"/api/v1/nav/{db_less_link.id}/logo",
        db_less_link.logo_url,
        require_file=True,
    ) or None


def _has_file_logo(link: NavLink) -> bool:
    return bool(link.logo_path)


def _link_out(link: NavLink) -> dict:
    return {
        "id": link.id,
        "name": link.name,
        "description": link.description,
        "url": link.url,
        "url_lan": link.url_lan,
        "open_mode": link.open_mode if link.open_mode in ("new", "current") else "new",
        "logo": _logo_out(link),
        "sort_order": link.sort_order,
        "created_at": as_utc(link.created_at).isoformat(),
    }


def _own_link(db: Session, user: User, link_id: int) -> NavLink:
    link = db.query(NavLink).filter(NavLink.id == link_id, NavLink.user_id == user.id).first()
    if not link:
        raise HTTPException(404, "导航不存在")
    return link


def _remove_logo_file(link: NavLink):
    path = data_dirs.resolve_rel(link.logo_path)
    if link.logo_path and not path:
        return  # 越界/非法路径：不删文件也不动字段（与旧行为一致）
    if path:
        path.unlink(missing_ok=True)
    link.logo_path = ""


def _ensure_http_url(url: str, field: str = "网站地址") -> None:
    """导航地址白名单：http(s) 绝对地址或 / 开头的站内相对路径。

    导航地址会被浏览器按链接语义打开，放任任意 scheme 会把 javascript:/data: 这类
    可执行载荷存进库（当前为自 XSS；将来若导航改为共享即升级为存储型 XSS）。
    """
    u = url.strip()
    if not u:
        return
    low = u.lower()
    if low.startswith(("http://", "https://", "/")):
        return
    raise HTTPException(400, f"{field}需以 http(s):// 开头（站内路径可用 / 开头）")


def _check_fields(name: str, url: str, url_lan: str = "", open_mode: str = "new"):
    if not name.strip():
        raise HTTPException(400, "网站标题不能为空")
    if len(name) > 128:
        raise HTTPException(400, "网站标题过长")
    if not url.strip():
        raise HTTPException(400, "网站地址不能为空")
    if len(url) > 1024:
        raise HTTPException(400, "地址过长")
    _ensure_http_url(url)
    if len(url_lan) > 1024:
        raise HTTPException(400, "内网地址过长")
    _ensure_http_url(url_lan, "内网地址")
    if open_mode not in ("new", "current"):
        raise HTTPException(400, "打开方式无效")


async def _read_logo(file: UploadFile | None) -> tuple[bytes, str] | None:
    if file is None or not file.filename:
        return None
    ext = ALLOWED_IMAGE_TYPES.get(file.content_type or "")
    if not ext:
        raise HTTPException(400, "Logo 仅支持 PNG / JPG / WebP / GIF / ICO / SVG 图片")
    data = await read_limited(file, MAX_LOGO_SIZE, "Logo 图片不能超过 2MB")
    if ext == ".svg":
        # 与头像/头像库同策略：剥除脚本/事件属性/javascript: 目标（含实体编码与 SMIL 注入）
        from app.api.v1.auth import sanitize_svg

        data = await run_in_threadpool(sanitize_svg, data)
        if not data:
            raise HTTPException(400, "SVG 含有不被允许的内容（脚本/事件属性/javascript: 目标），已拒绝")
    return data, ext


def _apply_form(link: NavLink, name, description, url, url_lan, open_mode) -> None:
    link.name = name.strip()[:128]
    link.description = (description or "").strip()[:512]
    link.url = url.strip()[:1024]
    link.url_lan = (url_lan or "").strip()[:1024]
    link.open_mode = open_mode


class ReorderIn(BaseModel):
    # 封顶防灌：导航本身上限 200，超大 ids 数组只会把 SQLite 拖进无意义的 IN 编译
    ids: list[int] = Field(min_length=1, max_length=500)


@router.get("")
def list_links(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(NavLink)
        .filter(NavLink.user_id == user.id)
        .order_by(NavLink.sort_order.asc(), NavLink.id.asc())
        .all()
    )
    return {"items": [_link_out(l) for l in rows]}


@router.post("")
async def create_link(
    name: str = Form(...),
    url: str = Form(...),
    description: str = Form(""),
    url_lan: str = Form(""),
    open_mode: str = Form("new"),
    logo_url: str = Form(""),
    file: UploadFile | None = File(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_fields(name, url, url_lan, open_mode)
    count = db.query(NavLink).filter(NavLink.user_id == user.id).count()
    if count >= MAX_NAV_COUNT:
        raise HTTPException(400, f"最多创建 {MAX_NAV_COUNT} 个导航")
    link = NavLink(user_id=user.id, sort_order=count)
    _apply_form(link, name, description, url, url_lan, open_mode)
    logo = await _read_logo(file)
    if logo:
        data, ext = logo
        link.logo_path = await run_in_threadpool(save_unique, data_dirs.NAV_LOGOS, f"nav_{user.id}", ext, data)
        link.logo_url = ""
    else:
        link.logo_url = (safe_logo_url(logo_url.strip()) or "")[:1024]
    db.add(link)
    db.commit()
    return {"ok": True, "item": _link_out(link)}


@router.patch("/{link_id}")
async def update_link(
    link_id: int,
    name: str = Form(...),
    url: str = Form(...),
    description: str = Form(""),
    url_lan: str = Form(""),
    open_mode: str = Form("new"),
    logo_url: str = Form(""),
    clear_logo: str = Form(""),
    file: UploadFile | None = File(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    link = _own_link(db, user, link_id)
    _check_fields(name, url, url_lan, open_mode)
    _apply_form(link, name, description, url, url_lan, open_mode)
    logo = await _read_logo(file)
    if logo:
        data, ext = logo
        _remove_logo_file(link)
        link.logo_path = await run_in_threadpool(save_unique, data_dirs.NAV_LOGOS, f"nav_{user.id}", ext, data)
        link.logo_url = ""
    elif clear_logo == "1":
        _remove_logo_file(link)
        link.logo_url = ""
    else:
        link.logo_url = (safe_logo_url(logo_url.strip()) or "")[:1024]
        if link.logo_url and link.logo_path:
            _remove_logo_file(link)
    db.commit()
    return {"ok": True, "item": _link_out(link)}


@router.delete("/{link_id}")
def delete_link(link_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    link = _own_link(db, user, link_id)
    _remove_logo_file(link)
    db.delete(link)
    db.commit()
    return {"ok": True}


@router.post("/reorder")
def reorder(body: ReorderIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ids = body.ids or []
    if not ids:
        raise HTTPException(400, "缺少排序数据")
    rows = db.query(NavLink).filter(NavLink.user_id == user.id, NavLink.id.in_(ids)).all()
    by_id = {r.id: r for r in rows}
    for idx, nid in enumerate(ids):
        if nid in by_id:
            by_id[nid].sort_order = idx
    db.commit()
    return {"ok": True}


@router.get("/{link_id}/logo")
def get_logo(
    link_id: int,
    user: User = Depends(get_media_user),
    db: Session = Depends(get_db),
):
    link = db.query(NavLink).filter(NavLink.id == link_id, NavLink.user_id == user.id).first()
    if not link or not link.logo_path:
        raise HTTPException(404, "Logo 不存在")
    path = data_dirs.resolve_rel(link.logo_path)
    if not path or not path.is_file():
        raise HTTPException(404, "Logo 不存在")
    from app.api.v1.auth import media_file_headers

    return FileResponse(path, headers=media_file_headers(path))
