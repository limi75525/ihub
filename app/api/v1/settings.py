"""系统设置（管理员）。"""

import logging
import threading
import time as _time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.auth import registration_open
from app.api.v1.recycle import recycle_enabled
from app.core.config import settings as cfg
from app.core.deps import get_current_admin
from app.core.fsutil import data_file
from app.db.session import get_db
from app.models.system_setting import get_int_setting, get_setting, get_setting_db, set_setting
from app.models.user import User
from app.services.logo_urls import file_url
from app.services.retention import get_pending_at, get_retention_days, run_retention_cleanup
from app.services.uploads import read_limited, save_unique
from app.core import outbound
from app.core import data_dirs

RETENTION_ALLOWED = (0, 7, 30, 180, 365)

logger = logging.getLogger(__name__)

ALLOWED_SITE_LOGO_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/x-icon": ".ico",
}
MAX_SITE_LOGO_SIZE = 2 * 1024 * 1024  # 2MB

# 登录背景壁纸通常较大，放宽到 8MB，并允许动图
ALLOWED_LOGIN_BG_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_LOGIN_BG_SIZE = 8 * 1024 * 1024  # 8MB

router = APIRouter(prefix="/settings", tags=["settings"])

SITE_LOGO_ENDPOINT = "/api/v1/settings/site-logo-file"
LOGIN_BG_ENDPOINT = "/api/v1/settings/login-bg-file"


def _brand_file_url(path_rel: str, endpoint: str) -> str | None:
    """品牌图片（站点 Logo / 登录背景）的展示地址：公开接口也要取到，带 mtime 缓存戳。
    require_file：残留的已删文件路径不下发必然 404 的地址。"""
    return file_url(path_rel, endpoint, None, require_file=True)


@router.get("/public")
def public_settings(db: Session = Depends(get_db)):
    return {
        "registration_open": registration_open(db),
        "captcha_enabled": get_setting_db(db, "captcha_enabled", "false") == "true",
        # 站点品牌：未自定义时为 None，前端回退默认标题/Logo
        "site_title": get_setting_db(db, "site_title", "") or None,
        "site_logo": _brand_file_url(get_setting_db(db, "site_logo_path", ""), SITE_LOGO_ENDPOINT),
        # 登录背景：本地上传优先于在线链接；均未设置为 None
        "login_bg": _login_bg_url(get_setting_db(db, "login_bg_path", ""))
        or get_setting_db(db, "login_bg_url", "")
        or None,
        "login_bg_url": get_setting_db(db, "login_bg_url", "") or None,
        # 回收站开关：所有用户都会受删除行为影响（关闭时删除立即生效不可恢复），随公开接口下发
        "recycle_enabled": recycle_enabled(),
        # 上传大小限制随公开接口下发，供各上传入口做前端预检查
        "max_avatar_mb": get_int_setting("avatar_max_mb", 2, 1, 20),
        "max_transfer_mb": get_int_setting("transfer_max_mb", 512, 1, 2048),
    }


def _login_bg_url(path_rel: str) -> str | None:
    return _brand_file_url(path_rel, LOGIN_BG_ENDPOINT)


def _clear_setting_file(key: str) -> None:
    """清除「路径存设置、文件在 DATA_DIR」的品牌图片（登录背景 / 站点 Logo）。"""
    rel = get_setting(key, "")
    if rel:
        (Path(cfg.DATA_DIR) / rel).unlink(missing_ok=True)
    set_setting(key, "")


def _clear_login_bg_file() -> None:
    _clear_setting_file("login_bg_path")


class LoginBgUrlIn(BaseModel):
    url: str = Field(default="", max_length=2048)


@router.patch("/login-bg-url")
def set_login_bg_url(body: LoginBgUrlIn, admin: User = Depends(get_current_admin)):
    """设置在线背景图链接；置空即清除（上传本地壁纸会覆盖在线链接）。"""
    url = body.url.strip()
    if url and not url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "在线图片链接需以 http(s):// 开头")
    _clear_login_bg_file()
    set_setting("login_bg_url", url)
    return {"ok": True, "login_bg": url or None}


def _store_login_bg(data: bytes, ext: str) -> str:
    """落盘登录背景并清在线链接（磁盘写入 + 设置写库，整体放线程池）。"""
    _clear_login_bg_file()
    set_setting("login_bg_url", "")
    rel = save_unique(data_dirs.BG, "login", ext, data)
    set_setting("login_bg_path", rel)
    return rel


@router.post("/login-bg")
async def upload_login_bg(file: UploadFile, admin: User = Depends(get_current_admin)):
    """上传本地壁纸作为登录背景；上传后清除在线链接设置。"""
    ext = ALLOWED_LOGIN_BG_TYPES.get(file.content_type or "")
    if not ext:
        raise HTTPException(400, "仅支持 PNG / JPG / WebP / GIF 图片")
    data = await read_limited(file, MAX_LOGIN_BG_SIZE, "背景图不能超过 8MB")
    rel = await run_in_threadpool(_store_login_bg, data, ext)
    return {"ok": True, "login_bg": _brand_file_url(rel, LOGIN_BG_ENDPOINT)}


@router.delete("/login-bg")
def reset_login_bg(admin: User = Depends(get_current_admin)):
    """恢复默认背景：清除上传文件与在线链接。"""
    _clear_login_bg_file()
    set_setting("login_bg_url", "")
    return {"ok": True, "login_bg": None}


@router.get("/login-bg-file")
def login_bg_file():
    """登录背景文件（公开：登录页未登录也需展示）。"""
    rel = get_setting("login_bg_path", "")
    if not rel:
        raise HTTPException(404, "未上传背景图")
    path = data_dirs.resolve_rel(rel)
    if not path or not path.is_file():
        raise HTTPException(404, "背景图文件缺失")
    return FileResponse(path)


class SiteTitleIn(BaseModel):
    title: str = Field(max_length=40)


@router.patch("/site-title")
def set_site_title(body: SiteTitleIn, admin: User = Depends(get_current_admin)):
    title = body.title.strip()
    set_setting("site_title", title)
    return {"ok": True, "site_title": title or None}


def _store_site_logo(data: bytes, ext: str) -> str:
    """落盘的站点 Logo（磁盘写入 + 设置写库，整体放线程池）。"""
    _clear_site_logo_file()
    rel = save_unique(data_dirs.AVATARS, "site", ext, data)
    set_setting("site_logo_path", rel)
    return rel


@router.post("/site-logo")
async def upload_site_logo(file: UploadFile, admin: User = Depends(get_current_admin)):
    ext = ALLOWED_SITE_LOGO_TYPES.get(file.content_type or "")
    if not ext:
        raise HTTPException(400, "仅支持 PNG / JPG / WebP / ICO 图片")
    data = await read_limited(file, MAX_SITE_LOGO_SIZE, "Logo 不能超过 2MB")
    rel = await run_in_threadpool(_store_site_logo, data, ext)
    return {"ok": True, "site_logo": _brand_file_url(rel, SITE_LOGO_ENDPOINT)}


@router.delete("/site-logo")
def reset_site_logo(admin: User = Depends(get_current_admin)):
    _clear_site_logo_file()
    return {"ok": True, "site_logo": None}


def _clear_site_logo_file() -> None:
    _clear_setting_file("site_logo_path")


@router.get("/site-logo-file")
def site_logo_file():
    """站点 Logo 文件（公开：登录页未登录也需展示）。"""
    rel = get_setting("site_logo_path", "")
    if not rel:
        raise HTTPException(404, "未上传 Logo")
    path = data_dirs.resolve_rel(rel)
    if not path or not path.is_file():
        raise HTTPException(404, "Logo 文件缺失")
    return FileResponse(path)


class ImageCacheIn(BaseModel):
    enabled: bool


@router.get("/image-cache")
def get_image_cache(admin: User = Depends(get_current_admin)):
    return {"enabled": get_setting("image_cache_enabled", "false") == "true"}


@router.patch("/image-cache")
def set_image_cache(body: ImageCacheIn, admin: User = Depends(get_current_admin)):
    """图片缓存开关：将站内引用的在线图片缓存到本地（功能开发中，仅先落地开关）。"""
    set_setting("image_cache_enabled", "true" if body.enabled else "false")
    return {"ok": True, "enabled": body.enabled}


class SystemSourcesIn(BaseModel):
    hidden: bool


@router.get("/system-sources")
def get_system_sources(admin: User = Depends(get_current_admin)):
    """系统来源（种子事件等）在管理员的接入服务列表中是否隐藏。"""
    return {"hidden": get_setting("hide_system_sources", "false") == "true"}


@router.patch("/system-sources")
def set_system_sources(body: SystemSourcesIn, admin: User = Depends(get_current_admin)):
    set_setting("hide_system_sources", "true" if body.hidden else "false")
    return {"ok": True, "hidden": body.hidden}


class RegistrationIn(BaseModel):
    open: bool


class RecycleIn(BaseModel):
    enabled: bool


@router.patch("/recycle")
def set_recycle(body: RecycleIn, admin: User = Depends(get_current_admin)):
    """回收站开关：开启后删除进入回收站保留 30 天；关闭后删除立即彻底删除。"""
    set_setting("recycle_enabled", "true" if body.enabled else "false")
    return {"ok": True, "recycle_enabled": body.enabled}


class DockerFlagsIn(BaseModel):
    monitor_enabled: bool | None = None
    control_enabled: bool | None = None


@router.get("/docker")
def get_docker_flags(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """容器监控 / 控制双开关状态（均默认关；控制依赖监控，但存储上互相独立）。"""
    return {
        "monitor_enabled": get_setting_db(db, "docker_monitor_enabled", "false") == "true",
        "control_enabled": get_setting_db(db, "docker_control_enabled", "false") == "true",
    }


@router.patch("/docker")
def set_docker_flags(
    body: DockerFlagsIn,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """更新容器双开关。监控开关变化时同步启停 Docker 事件线程（无需重启后端）。"""
    from app.services import docker_service
    from app.services.events import broker

    for enabled, key, label in (
        (body.monitor_enabled, "docker_monitor_enabled", "监控"),
        (body.control_enabled, "docker_control_enabled", "控制"),
    ):
        if enabled is None:
            continue
        set_setting(key, "true" if enabled else "false")
        logger.info(
            "容器控制审计：user=%s op=开关%s enabled=%s",
            admin.username,
            label,
            enabled,
        )
    monitor_on = get_setting_db(db, "docker_monitor_enabled", "false") == "true"
    docker_service.sync_events_worker(broker, monitor_on)
    return {
        "ok": True,
        "monitor_enabled": monitor_on,
        "control_enabled": get_setting_db(db, "docker_control_enabled", "false") == "true",
    }


class LimitsIn(BaseModel):
    avatar_max_mb: int
    transfer_max_mb: int


@router.get("/limits")
def get_limits(admin: User = Depends(get_current_admin)):
    from app.models.system_setting import get_int_setting

    return {
        "avatar_max_mb": get_int_setting("avatar_max_mb", 2, 1, 20),
        "transfer_max_mb": get_int_setting("transfer_max_mb", 512, 1, 2048),
    }


@router.patch("/limits")
def set_limits(body: LimitsIn, admin: User = Depends(get_current_admin)):
    """附件上传大小限制：头像本地上传图片（1-20MB）、快传/文件库附件（1-2048MB）。"""
    if not (1 <= body.avatar_max_mb <= 20):
        raise HTTPException(400, "头像图片上限需在 1-20MB 之间")
    if not (1 <= body.transfer_max_mb <= 2048):
        raise HTTPException(400, "附件上限需在 1-2048MB 之间")
    set_setting("avatar_max_mb", str(body.avatar_max_mb))
    set_setting("transfer_max_mb", str(body.transfer_max_mb))
    return {"ok": True, **body.model_dump()}


class CaptchaIn(BaseModel):
    enabled: bool


@router.patch("/captcha")
def set_captcha(
    body: CaptchaIn,
    admin: User = Depends(get_current_admin),
):
    set_setting("captcha_enabled", "true" if body.enabled else "false")
    return {"ok": True, "captcha_enabled": body.enabled}


class RetentionIn(BaseModel):
    days: int
    execute: str = Field(default="later", pattern="^(now|later)$")


@router.get("/retention")
def get_retention(admin: User = Depends(get_current_admin)):
    try:
        days = int(get_setting("retention_days", "0"))
    except (TypeError, ValueError):
        days = 0
    if days not in RETENTION_ALLOWED:
        days = 0
    return {"days": days, "pendingAt": get_pending_at()}


@router.patch("/retention")
def set_retention(body: RetentionIn, admin: User = Depends(get_current_admin)):
    if body.days not in RETENTION_ALLOWED:
        raise HTTPException(400, "保留天数仅支持 0（关闭）/一周/一月/半年/一年")
    old = get_retention_days()
    set_setting("retention_days", str(body.days))
    deleted = 0
    pending = ""
    # 长期 → 短期：需确认。execute=now 立即删除；否则 10 分钟后由定时检查执行
    if body.days > 0 and old > 0 and body.days < old:
        if body.execute == "now":
            # 大库清理可持续数十秒，不能在请求线程里同步跑（请求必超时）；
            # 放后台线程执行，接口立即返回（前端提示「已保存」，删除结果看消息页/SSE）
            import threading

            threading.Thread(target=run_retention_cleanup, daemon=True, name="retention-now").start()
        else:
            from datetime import datetime, timedelta, timezone

            pending = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
            set_setting("retention_pending_at", pending)
    else:
        # 变长期 / 关闭 / 不变：取消任何待执行删除
        set_setting("retention_pending_at", "")
    return {
        "ok": True,
        "days": body.days,
        "deleted": deleted,
        "pendingAt": pending or None,
    }


@router.patch("/registration")
def set_registration(
    body: RegistrationIn,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if (db.query(User).filter(User.is_deleted.is_(False)).count() or 0) == 0:
        raise HTTPException(400, "尚未初始化")
    set_setting("registration_open", "true" if body.open else "false")
    return {"ok": True, "registration_open": body.open}


# ---------------- 网络（出站代理 + TMDB 地址，2026-10-25） ----------------


class NetworkIn(BaseModel):
    proxy: str | None = None
    extra_domains: str | None = None
    tmdb_api_base: str | None = None
    tmdb_image_base: str | None = None


@router.get("/network")
def get_network(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    from app.core import outbound

    return {
        "proxy": get_setting_db(db, outbound.PROXY_KEY, ""),
        "extra_domains": get_setting_db(db, outbound.EXTRA_KEY, ""),
        "tmdb_api_base": get_setting_db(db, "video_tmdb_api_base", ""),
        "tmdb_image_base": get_setting_db(db, "video_tmdb_image_base", ""),
        "builtin_suffixes": list(outbound.BUILTIN_SUFFIXES),
    }


@router.patch("/network")
def set_network(body: NetworkIn, admin: User = Depends(get_current_admin)):
    from app.core import outbound

    if body.proxy is not None:
        proxy = body.proxy.strip()
        if proxy and not proxy.lower().startswith(("http://", "https://")):
            raise HTTPException(400, "代理地址需以 http:// 或 https:// 开头（暂不支持 socks5）")
        set_setting(outbound.PROXY_KEY, proxy[:256])
        logger.info("网络设置审计：user=%s op=出站代理 proxy=%s", admin.username, proxy or "(清空)")
    if body.extra_domains is not None:
        set_setting(outbound.EXTRA_KEY, body.extra_domains.strip()[:1024])
    if body.tmdb_api_base is not None:
        set_setting("video_tmdb_api_base", body.tmdb_api_base.strip()[:256])
    if body.tmdb_image_base is not None:
        set_setting("video_tmdb_image_base", body.tmdb_image_base.strip()[:256])
    return {"ok": True}


@router.post("/network/test-proxy")
def test_proxy(admin: User = Depends(get_current_admin)):
    """用当前出站代理拉一个轻量探测地址，验证代理可用性与延迟。"""
    from app.core import outbound

    proxy = (get_setting(outbound.PROXY_KEY, "") or "").strip()
    if not proxy:
        return {"ok": False, "error": "尚未配置代理地址"}
    import urllib.request as _ureq

    req = _ureq.Request("https://www.gstatic.com/generate_204", headers={"User-Agent": "iHub/1.0"})
    t0 = _time.perf_counter()
    try:
        handler = _ureq.ProxyHandler({"http": proxy, "https": proxy})
        opener = _ureq.build_opener(handler)
        with opener.open(req, timeout=8) as resp:
            ms = int((_time.perf_counter() - t0) * 1000)
            return {"ok": resp.status == 204 or resp.status == 200, "ms": ms, "status": resp.status}
    except Exception as e:
        ms = int((_time.perf_counter() - t0) * 1000)
        return {"ok": False, "ms": ms, "error": str(getattr(e, "reason", None) or e)}


@router.post("/network/test-tmdb")
def test_tmdb(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """按当前网络设置实测 TMDB API 连通性（直连或走代理自动判定）。"""
    from app.core.credential import get_credential
    from app.services import tmdb

    api_base = get_setting_db(db, "video_tmdb_api_base", "") or tmdb.API_DEFAULT
    api_key = get_credential(db, "video_tmdb_key")
    url = f"{api_base.rstrip('/')}/3/configuration"
    if api_key:
        from urllib.parse import quote

        url += f"?api_key={quote(api_key, safe='')}"
    req = tmdb.UrlRequest(url, headers={"User-Agent": tmdb.USER_AGENT, "Accept": "application/json"})
    t0 = _time.perf_counter()
    try:
        opener = outbound.opener_for(url)
        with opener.open(req, timeout=10) as resp:
            ms = int((_time.perf_counter() - t0) * 1000)
            return {"ok": resp.status == 200, "ms": ms, "status": resp.status}
    except Exception as e:
        ms = int((_time.perf_counter() - t0) * 1000)
        return {"ok": False, "ms": ms, "error": str(getattr(e, "reason", None) or e)}


# ---------------- 存储占用与定期清理（2026-10-25） ----------------


@router.get("/storage")
def storage_overview_api(admin: User = Depends(get_current_admin)):
    from app.services import janitor

    return janitor.storage_overview()


@router.post("/storage/cleanup")
def storage_cleanup(admin: User = Depends(get_current_admin)):
    from app.services import janitor

    if janitor.JANITOR_LOCK.locked():
        return {"ok": False, "error": "清理正在进行中"}
    threading.Thread(target=janitor.run_janitor, daemon=True).start()
    return {"ok": True, "started": True}
