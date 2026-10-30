"""开源品牌图标库：下载/管理（管理员）+ 检索/匹配/取图（登录用户）。

图标本体不随 iHub 发布，由管理员在「头像库 → 图标库」下载后落盘到
`data/ihub_brand_icons/`，实例级共享；每个库的 name / license / source_url
随接口下发，前端在选图与编辑处标明来源。
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.deps import get_current_admin, get_current_user, get_media_user
from app.db.session import get_db
from app.models.logo_group import LogoGroup
from app.models.logo_rule import LogoRule
from app.models.nav_link import NavLink
from app.models.source import Source
from app.models.user import User
from app.services import brand_icons
from app.services.uploads import read_limited

router = APIRouter(prefix="/brand", tags=["brand"])

MAX_UPLOAD = 120 * 1024 * 1024


def _usage(db: Session, lib_id: str) -> int:
    like = f"/api/v1/brand/icon/{lib_id}/%"
    total = 0
    for model in (NavLink, LogoGroup, LogoRule, Source):
        total += db.query(model).filter(model.logo_url.like(like)).count()
    return total


@router.get("/libs")
def list_libs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """可下载与已安装的图标库；附带每库当前引用数（管理员卸载前判断）。"""
    items = brand_icons.list_libs()
    is_admin = user.role == "admin"
    for item in items:
        item["usage"] = _usage(db, item["id"]) if is_admin and item["installed"] else 0
    return {"items": items, "installed": [x["id"] for x in items if x["installed"]]}


@router.post("/libs/{lib_id}/install")
def install_lib(
    lib_id: str,
    admin: User = Depends(get_current_admin),
):
    """下载并安装内置图标库（后台任务，返回 task_id 供轮询）。"""
    if lib_id not in brand_icons.BUILTIN_LIBS:
        raise HTTPException(404, "未知图标库")
    task_id = uuid.uuid4().hex[:16]
    brand_icons._task_set(task_id, state="running", phase="download", message="准备下载", lib=lib_id)
    import threading

    threading.Thread(target=brand_icons.install_builtin, args=(lib_id, task_id), daemon=True).start()
    return {"ok": True, "task_id": task_id}


@router.get("/tasks/{task_id}")
def task_state(task_id: str, admin: User = Depends(get_current_admin)):
    state = brand_icons.task_state(task_id)
    if not state:
        raise HTTPException(404, "任务不存在或已过期")
    return state


@router.post("/libs/fetch")
def install_from_url(
    url: str = Form(...),
    name: str = Form(""),
    license_name: str = Form(""),
    source_url: str = Form(""),
    lib_id: str = Form(""),
    admin: User = Depends(get_current_admin),
):
    """从自定义链接下载图标库 zip（后台任务）。"""
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "下载地址必须是 http(s)")
    lid = (lib_id or "").strip().lower() or f"custom-{uuid.uuid4().hex[:8]}"
    if lid in brand_icons.BUILTIN_LIBS:
        raise HTTPException(400, "该标识为内置库保留，请换一个")
    task_id = uuid.uuid4().hex[:16]
    brand_icons._task_set(task_id, state="running", phase="download", message="准备下载", lib=lid)
    import threading

    threading.Thread(
        target=brand_icons.install_from_url,
        args=(lid, (name or lid)[:64], url[:500], task_id),
        kwargs={"license_name": license_name[:64], "source_url": source_url[:300]},
        daemon=True,
    ).start()
    return {"ok": True, "task_id": task_id, "lib_id": lid}


@router.post("/upload")
async def upload_lib(
    file: UploadFile = File(...),
    name: str = Form(""),
    license_name: str = Form(""),
    source_url: str = Form(""),
    lib_id: str = Form(""),
    admin: User = Depends(get_current_admin),
):
    """手动上传图标库包（zip，内含任意 SVG 文件夹即可）。"""
    data = await read_limited(file, MAX_UPLOAD, "图标库包不能超过 120MB")
    if not data[:2] == b"PK":
        raise HTTPException(400, "请上传 zip 格式的图标库包")
    lid = (lib_id or "").strip().lower() or f"custom-{uuid.uuid4().hex[:8]}"
    if lid in brand_icons.BUILTIN_LIBS:
        raise HTTPException(400, "该标识为内置库保留，请换一个")
    # 未填名称时：包内 manifest 声明优先，其次用上传的 zip 文件名（去掉 .zip）
    default_name = Path(file.filename or "").stem or lid
    try:
        result = await run_in_threadpool(
            brand_icons.install_from_zip, lid, name.strip()[:64], data,
            license_name=license_name[:64], source_url=source_url[:300],
            fallback_name=default_name[:64],
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, **result}


@router.delete("/libs/{lib_id}")
def remove_lib(
    lib_id: str,
    force: bool = Query(False),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """卸载图标库；仍被引用时需 force=1（前端展示引用数并二次确认）。"""
    usage = _usage(db, lib_id)
    if usage and not force:
        raise HTTPException(409, f"仍有 {usage} 处正在使用该库的图标")
    ok = brand_icons.remove_lib(lib_id)
    if not ok:
        raise HTTPException(404, "图标库未安装")
    return {"ok": True, "usage": usage}


@router.get("/search")
def search(
    q: str = Query("", max_length=100),
    lib: str | None = Query(None, max_length=48),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0, le=20000),
    user: User = Depends(get_current_user),
):
    """图标库检索：q 支持中文名、英文名、slug。"""
    return brand_icons.search(q, lib=lib, limit=limit, offset=offset)


@router.get("/suggest")
def suggest(
    name: str = Query("", max_length=100),
    url: str = Query("", max_length=500),
    limit: int = Query(5, ge=1, le=20),
    user: User = Depends(get_current_user),
):
    """导航 URL / 企业名 → 图标候选（auto=True 表示最高分足以自动预选）。"""
    return brand_icons.suggest(name=name, url=url, limit=limit)


@router.get("/icon/{lib_id}/{slug}")
def icon(
    lib_id: str,
    slug: str,
    c: str = Query("", max_length=9),
    user: User = Depends(get_media_user),
):
    """图标文件：img 标签走 media_key；simple-icons 支持 ?c=RRGGBB 换色。"""
    try:
        data, mime = brand_icons.icon_bytes(lib_id, slug, color=c)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError:
        raise HTTPException(400, "非法图标库标识")
    return Response(
        content=data,
        media_type=mime,
        headers={
            "Cache-Control": "private, max-age=604800",
            # 第三方/自定义 SVG 一律按沙箱处理：直接打开该地址也不能在站点源内执行脚本
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
        },
    )
