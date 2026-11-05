import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings
from app.core.data_dirs import migrate_layout, migrate_network_proxy
from app.core.netutil import client_ip
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import Source  # noqa: F401 确保模型已注册
from app.models.ingest_nonce import IngestNonce  # noqa: F401 防重放表
from app.db.migrations import run_startup_migrations
from app.db.settings_repo import get_setting_db
from app.models.user import User
from app.scheduler import (
    register_janitor_job,
    register_purge_job,
    register_seed_prewarm_job,
    register_update_check_job,
    register_retention_job,
    scheduler,
    sync_email_jobs,
)
from app.services.retention import run_retention_cleanup
from app.services.purge import purge_expired
from app.services import docker_service, seed_events, seed_traffic, seed_transfer
from app.services.events import broker
from app.core.errors import UpstreamError, domain_error_handler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

def _reset_stale_scans() -> None:
    """进程启动即代表上一次扫描线程已不存在；把残留的 running 状态标记为中断。

    音乐与影视共用同一状态结构，分别复位，避免 /scan 以「已在运行」为由
    拒绝启动、状态页永远显示 running。
    """
    from app.services.media_scan import reset_stale_scan

    for state_key, label in (("music_scan_state", "音乐"), ("video_scan_state", "影视")):
        reset_stale_scan(state_key, label)


def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    # 数据库增量迁移与一次性数据修复（_REQUIRED_COLUMNS 补列 / logo 分组迁移 /
    # 授权码加密 / 种子系统来源清理）收拢在 db/migrations，组装根只留一行
    run_startup_migrations()
    # data/ 目录布局 v2（ihub_ 前缀）迁移必须最先跑：后续所有模块按新路径读写
    migrate_layout()
    migrate_network_proxy()
    broker.set_loop(asyncio.get_running_loop())

    # 上个进程若死在扫描中，*_scan_state 的 running 会永久残留导致 /scan 拒绝启动——启动时复位
    _reset_stale_scans()

    db = SessionLocal()
    try:
        sync_email_jobs(db.query(Source).all())
        user_count = db.query(User.id).count()
        # 容器监控默认关闭：开关为 false 时事件线程不启动，也不会访问 Docker
        docker_monitor_on = get_setting_db(db, "docker_monitor_enabled", "false") == "true"
    finally:
        db.close()
    register_retention_job()
    register_purge_job()
    register_janitor_job()
    register_seed_prewarm_job()
    register_update_check_job()
    # 进程重启后把 24h 内的发现页预热快照读回内存，首个访客无需等 MP
    from app.services.seed_prewarm import hydrate_from_disk as _hydrate_seed_cache
    _hydrate_seed_cache()
    run_retention_cleanup()
    purge_expired()
    scheduler.start()
    docker_service.sync_events_worker(broker, docker_monitor_on)
    # 网络流量只读采样可以常驻：qB 已配置时从启动起保留最近 6 分钟曲线；
    # 种子事件线程仍按原策略延迟到页面/测试连接成功后再启动。
    seed_traffic.sync_worker()
    seed_transfer.start_worker()
    if user_count == 0:
        logger.info("尚未注册用户：首次访问 Web 界面注册的账号将成为管理员")
    logger.info("iHub 后端已启动，数据目录：%s", settings.DATA_DIR)
    yield
    seed_events.stop_worker()
    seed_traffic.stop_worker()
    seed_transfer.stop_worker()
    docker_service.stop_events_worker()
    scheduler.shutdown(wait=False)


# API 文档默认不对公网暴露（匿名可枚举全部接口结构）；需要时设 IHUB_ENABLE_DOCS=true
import os as _os

_enable_docs = _os.getenv("IHUB_ENABLE_DOCS", "").lower() in ("1", "true", "yes")

app = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan,
    docs_url="/api/docs" if _enable_docs else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if _enable_docs else None,
)


class _AuthBodyLimitMiddleware:
    """未认证认证端点（/api/v1/auth/*）的请求体上限：64KB。

    登录/注册无需凭据即可到达，正常 JSON 不到 2KB；裸 uvicorn 部署（无反代限 body）
    时，超大请求体会被整体缓冲进内存后才被 Pydantic 拒绝，可被用来做内存放大。
    带 Content-Length 的请求在进入应用前直接拒绝；chunked 无长度的请求边读边计数，
    超限后不再向应用投递数据并断开（uvicorn 会随之关闭连接）。
    例外：/auth/avatar 是已认证端点（JWT 在先），按 avatar_max_mb 自限大小，
    不能套用 64KB——否则所有真实图片头像都会在进入端点前被 413 拒掉。
    """

    _LIMIT = 64 * 1024
    _EXEMPT_PATHS = ("/api/v1/auth/avatar",)

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or not scope["path"].startswith("/api/v1/auth/")
            or scope["path"] in self._EXEMPT_PATHS
        ):
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        cl = headers.get(b"content-length")
        if cl is not None:
            try:
                declared = int(cl)
            except ValueError:
                await _plain_response(send, 400, b'{"detail":"invalid content-length"}')
                return
            if declared > self._LIMIT:
                await _plain_response(send, 413, b'{"detail":"request entity too large"}')
                return
            await self.app(scope, receive, send)
            return

        over = {"flag": False}

        async def counting_receive():
            if over["flag"]:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                over["n"] = over.get("n", 0) + len(message.get("body", b""))
                if over["n"] > self._LIMIT:
                    over["flag"] = True
                    return {"type": "http.disconnect"}
            return message

        await self.app(scope, counting_receive, send)


async def _plain_response(send, status: int, body: bytes):
    # 未读请求体直接响应时必须声明 close，否则残留 body 会触发客户端 RST
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


# 注意：端点内 raise 的 413（如 /ingest/device、/transfer/upload 的流式超限）不要
# 全局加 connection: close——h11 对这类响应会先排空/优雅处理请求剩余 body，客户端
# 能完整读到 413；一旦声明 close，uvicorn 会提前关连接，还在发送大 body 的客户端
# 直接吃 RST（security_probe F 节实测回归）。close 只用于中间件手动 send 的短响应。


# 添加顺序即中间件层级：先加的在里层。body-limit 必须在 CORS 之前 add，
# 让 CORS 成为最外层——否则 413 短响应不经过 CORS，跨源部署下浏览器只会看到网络错误
app.add_middleware(_AuthBodyLimitMiddleware)

# CORS：默认不返回跨域头（nginx 同源部署无需 CORS）；
# 需要跨源时配置环境变量 IHUB_CORS_ORIGINS="http://a,https://b"
if settings.CORS_ORIGINS.strip():
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix="/api/v1")


# 前端入口（HTML）永不缓存：构建产物文件名带哈希可长缓存，但 index.html
# 若被浏览器启发式缓存，发版后用户会一直拿到旧 bundle（本轮多次踩坑）。
@app.middleware("http")
async def _no_cache_html(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if request.method == "GET" and (path == "/" or path.endswith(".html")):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(OverflowError)
async def int_overflow_handler(request: Request, exc: OverflowError):
    """路径/查询里的 id 超出 SQLite int64 范围时 SQLAlchemy 抛 OverflowError，
    统一回 404（资源不存在语义），避免 500 日志噪音。"""
    return JSONResponse(status_code=404, content={"detail": "资源不存在"})


@app.exception_handler(UpstreamError)
async def upstream_error_handler(request: Request, exc: UpstreamError):
    """领域错误统一映射（含 SeedError）；消息已脱敏，不包含密码/API_TOKEN。"""
    return await domain_error_handler(request, exc)


@app.get("/api/health")
def health(request: Request):
    """健康检查。

    client_ip 回显「服务端把本次请求算作哪个 IP」（限流/登录锁定的维度），
    用于排查反向代理是否按预期传递客户端地址：从外网 curl 一下，
    若显示的是代理机内网地址（如 192.168.1.3）而不是自己的公网 IP，
    说明代理没有追加 X-Forwarded-For / 覆盖 X-Real-IP。
    """
    return {
        "ok": True,
        "app": settings.APP_NAME,
        "client_ip": client_ip(request),
        "trust_proxy_headers": settings.TRUST_PROXY_HEADERS,
    }


# 前端构建产物由 FastAPI 直接托管（主仓库 frontend-dist/，Docker 镜像内为 /app/frontend-dist）；
# 本地开发兜底同级的 iHub-Frontend/dist（前端仓 build 产物，免拷贝）
_frontend_dist = Path(__file__).resolve().parent.parent / "frontend-dist"
if not _frontend_dist.is_dir():
    _frontend_dist = Path(__file__).resolve().parent.parent.parent / "iHub-Frontend" / "dist"
if _frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
