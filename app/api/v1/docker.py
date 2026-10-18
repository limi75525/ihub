"""容器监控 / 控制（管理员）。

数据来自宿主机 Docker Engine API（socket 由部署时挂载，见 deploy/docker-compose.yml 注释）。
双开关门禁（system_settings 存储，均默认关）：
- docker_monitor_enabled：监控总开关。关闭时**所有** /docker/* 接口不触碰 Docker
  （一律 503，/docker/status 返回 disabled 形状），事件线程同步停止；
- docker_control_enabled：容器控制开关（启停/重启/删除/拉镜像）。需监控开关已开，
  否则 403——写接口三重校验：管理员 + 监控开关 + 控制开关，缺一不可。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_admin
from app.db.session import get_db
from app.models.system_setting import get_setting_db
from app.models.user import User
from app.services import docker_service as docker

logger = logging.getLogger(__name__)

# 写操作审计：时间由日志格式自带，逐条记录 用户/操作/容器 与结果
audit_log = logging.getLogger("ihub.docker.control")

router = APIRouter(prefix="/docker", tags=["docker"])

MONITOR_KEY = "docker_monitor_enabled"
CONTROL_KEY = "docker_control_enabled"


def monitor_enabled(db: Session) -> bool:
    return get_setting_db(db, MONITOR_KEY, "false") == "true"


def control_enabled(db: Session) -> bool:
    return get_setting_db(db, CONTROL_KEY, "false") == "true"


def _gate_monitor(db: Session) -> None:
    """监控总开关门禁：关闭时绝不发起对 Docker 的任何真实访问。"""
    if not monitor_enabled(db):
        raise HTTPException(status_code=503, detail="容器监控未开启")


def _gate_control(db: Session) -> None:
    if not control_enabled(db):
        raise HTTPException(status_code=403, detail="容器控制未开启（设置 → 系统 → 容器控制）")


def _require_available() -> None:
    ok, err = docker.available()
    if not ok:
        raise HTTPException(status_code=503, detail=err or "Docker 不可用")


@router.get("/status")
def status(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """探测 Docker 是否可用（页面据此显示列表 / 挂载引导 / 开关引导）。"""
    if not monitor_enabled(db):
        # disabled 形状：前端据此显示「去设置开启」而不是挂载引导
        return {
            "available": False,
            "disabled": True,
            "monitor_enabled": False,
            "control_enabled": control_enabled(db),
            "host": docker.host_display(),
        }
    ok, err = docker.available()
    if not ok:
        return {
            "available": False,
            "disabled": False,
            "monitor_enabled": True,
            "control_enabled": control_enabled(db),
            "host": docker.host_display(),
            "error": err,
        }
    return {
        "available": True,
        "disabled": False,
        "monitor_enabled": True,
        "control_enabled": control_enabled(db),
        "host": docker.host_display(),
        **docker.version_info(),
    }


@router.get("/containers")
def containers(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    _gate_monitor(db)
    _require_available()
    items = docker.list_containers()
    running = sum(1 for i in items if i["state"] == "running")
    return {
        "available": True,
        "summary": {"total": len(items), "running": running, "exited": len(items) - running},
        "items": items,
    }


@router.get("/containers/{cid}/logs")
def container_logs(
    cid: str,
    tail: int = Query(default=300, ge=1, le=1000),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    # cid 先校验再探测可用性：无论 Docker 是否在线，恶意 ID 一律 400（探针可稳定断言）
    if not cid or not cid.isalnum():
        raise HTTPException(status_code=400, detail="容器 ID 不合法")
    _gate_monitor(db)
    _require_available()
    try:
        return docker.container_logs(cid, tail)
    except docker.DockerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/df")
def system_df(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """磁盘占用摘要（镜像 / 容器可写层 / 卷 / 构建缓存）。"""
    _gate_monitor(db)
    _require_available()
    try:
        return docker.system_df()
    except docker.DockerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ---- 容器控制（写操作）：管理员 + 监控开关 + 控制开关 三重校验，缺一不可 ----


def _run_control(cid: str, db: Session, admin: User, op: str, fn) -> dict:
    """写操作公共路径：cid 校验 → 双开关门禁 → 执行 → 审计 → 失效列表缓存。"""
    if not cid or not cid.isalnum():
        raise HTTPException(status_code=400, detail="容器 ID 不合法")
    _gate_monitor(db)
    _gate_control(db)
    _require_available()
    try:
        out = fn()
    except docker.DockerError as exc:
        audit_log.info("容器控制审计：user=%s op=%s cid=%s result=失败 reason=%s", admin.username, op, cid, exc.message)
        if exc.status in (400, 404, 409):
            raise HTTPException(status_code=exc.status, detail=exc.message)
        raise HTTPException(status_code=502, detail=exc.message)
    except docker.DockerUnavailable as exc:
        audit_log.info("容器控制审计：user=%s op=%s cid=%s result=失败 reason=%s", admin.username, op, cid, exc)
        raise HTTPException(status_code=503, detail=str(exc))
    docker.invalidate_list_cache()
    audit_log.info("容器控制审计：user=%s op=%s cid=%s result=成功", admin.username, op, cid)
    return {"ok": True, **out}


@router.post("/containers/{cid}/start")
def container_start(
    cid: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return _run_control(cid, db, admin, "启动", lambda: docker.container_action(cid, "start"))


@router.post("/containers/{cid}/stop")
def container_stop(
    cid: str,
    t: int = Query(default=10, ge=1, le=60, description="优雅退出超时秒数"),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return _run_control(cid, db, admin, "停止", lambda: docker.container_action(cid, "stop", t))


@router.post("/containers/{cid}/restart")
def container_restart(
    cid: str,
    t: int = Query(default=10, ge=1, le=60, description="优雅退出超时秒数"),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return _run_control(cid, db, admin, "重启", lambda: docker.container_action(cid, "restart", t))


@router.delete("/containers/{cid}")
def container_remove(
    cid: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """删除容器本体（不删镜像、不带 -v 删卷；运行中容器会被 Docker 拒绝并返回 409）。"""
    return _run_control(cid, db, admin, "删除", lambda: docker.remove_container(cid))


class PullIn(BaseModel):
    image: str


@router.post("/images/pull")
def image_pull(
    body: PullIn,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """拉取镜像（默认 latest tag）。v1 仅拉取，不自动重建容器。"""
    _gate_monitor(db)
    _gate_control(db)
    _require_available()
    # 审计日志防注入：400（镜像名校验）路径的 image 未清洗，含换行可伪造多行审计记录
    image_audit = " ".join(str(body.image).split())[:200]
    try:
        out = docker.pull_image(body.image)
    except docker.DockerError as exc:
        audit_log.info(
            "容器控制审计：user=%s op=拉取镜像 image=%s result=失败 reason=%s",
            admin.username, image_audit, exc.message,
        )
        if exc.status == 400:
            raise HTTPException(status_code=400, detail=exc.message)
        if exc.status == 404:
            raise HTTPException(status_code=404, detail=exc.message)
        raise HTTPException(status_code=502, detail=exc.message)
    except docker.DockerUnavailable as exc:
        audit_log.info(
            "容器控制审计：user=%s op=拉取镜像 image=%s result=失败 reason=%s",
            admin.username, image_audit, exc,
        )
        raise HTTPException(status_code=503, detail=str(exc))
    audit_log.info(
        "容器控制审计：user=%s op=拉取镜像 image=%s result=成功", admin.username, out["image"]
    )
    return {"ok": True, "message": out["message"], "image": out["image"]}
