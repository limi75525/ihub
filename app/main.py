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
from app.core.crypto import encrypt_text
from app.core.netutil import client_ip
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import Source  # noqa: F401 确保模型已注册
from app.models.ingest_nonce import IngestNonce  # noqa: F401 防重放表
from app.models.system_setting import get_setting_db
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
from app.services.seed_common import SeedError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# create_all 不会给已存在的表补列，这里按需做轻量列迁移
_REQUIRED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "messages": [
        ("is_starred", "BOOLEAN DEFAULT 0"),
        ("is_pinned", "BOOLEAN DEFAULT 0"),
        ("is_deleted", "BOOLEAN DEFAULT 0"),
        ("deleted_at", "DATETIME"),
    ],
    "users": [
        ("last_login_ip", "VARCHAR(64) DEFAULT ''"),
        ("is_deleted", "BOOLEAN DEFAULT 0"),
        ("deleted_at", "DATETIME"),
        ("pwd_version", "INTEGER DEFAULT 0"),
        ("media_key", "VARCHAR(64)"),
        ("signature", "VARCHAR(128) DEFAULT ''"),
        ("email", "VARCHAR(128) DEFAULT ''"),
    ],
    "sources": [
        ("is_deleted", "BOOLEAN DEFAULT 0"),
        ("deleted_at", "DATETIME"),
        ("sort_order", "INTEGER DEFAULT 0"),
        ("imap_verify_tls", "BOOLEAN DEFAULT 1"),
        ("is_system", "BOOLEAN DEFAULT 0"),
    ],
    "devices": [("is_deleted", "BOOLEAN DEFAULT 0"), ("deleted_at", "DATETIME")],
    "logo_rules": [("is_deleted", "BOOLEAN DEFAULT 0"), ("deleted_at", "DATETIME")],
    "system_settings": [("is_deleted", "BOOLEAN DEFAULT 0"), ("deleted_at", "DATETIME")],
    "music_tracks": [
        ("album_artist", "VARCHAR(512) DEFAULT ''"),
        ("genre", "VARCHAR(128) DEFAULT ''"),
        ("year", "INTEGER DEFAULT 0"),
        ("track_no", "INTEGER DEFAULT 0"),
        ("disc_no", "INTEGER DEFAULT 0"),
        ("bitrate", "INTEGER DEFAULT 0"),
        ("sample_rate", "INTEGER DEFAULT 0"),
        ("cover_path", "VARCHAR(256)"),
    ],
    "music_playlists": [
        ("description", "VARCHAR(1024) DEFAULT ''"),
        ("cover_path", "VARCHAR(256)"),
    ],
    "transfer_items": [
        ("origin", "VARCHAR(16) DEFAULT 'share'"),
        ("dir_path", "VARCHAR(256) DEFAULT ''"),
    ],
    "video_items": [
        ("original_title", "VARCHAR(512) DEFAULT ''"),
        ("plot", "TEXT DEFAULT ''"),
        ("rating", "FLOAT DEFAULT 0"),
        ("genres", "VARCHAR(256) DEFAULT ''"),
        ("directors", "VARCHAR(512) DEFAULT ''"),
        ("actors", "TEXT DEFAULT ''"),
        ("runtime_min", "INTEGER DEFAULT 0"),
        ("poster_ref", "VARCHAR(512) DEFAULT ''"),
        ("fanart_ref", "VARCHAR(512) DEFAULT ''"),
        ("series_plot", "TEXT DEFAULT ''"),
        ("series_rating", "FLOAT DEFAULT 0"),
        ("series_genres", "VARCHAR(256) DEFAULT ''"),
        ("tmdb_id", "VARCHAR(32) DEFAULT ''"),
        ("series_tmdb_id", "VARCHAR(32) DEFAULT ''"),
        ("meta_sig", "VARCHAR(64) DEFAULT ''"),
    ],
}


def _ensure_sqlite_columns():
    from sqlalchemy import text

    with engine.connect() as conn:
        # 旧版头像规则表（按 4 种类型拆分）已被组合式 logo_rules 取代，直接弃用
        has_old = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='avatar_rules'")
        ).first()
        if has_old:
            conn.execute(text("DROP TABLE avatar_rules"))
        for table, columns in _REQUIRED_COLUMNS.items():
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if not existing:
                continue
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        conn.commit()


def _migrate_logo_groups():
    """旧版组合式 logo_rules（phone/signature/email/nickname 四字段）→ 企业分组模型。

    新结构：logo_groups（企业名称 + 默认头像）+ logo_rules(group_id, signature, account)。
    迁移按「单位」聚合：旧规则以 签名/昵称/号码/邮箱 第一个非空字段作为企业名，
    同名旧规则合并进同一分组，旧规则的头像成为分组默认头像，匹配字段拆为成员规则。
    幂等：新库（logo_rules 已含 account 列）直接跳过。"""
    from sqlalchemy import text

    from app.models.logo_group import LogoGroup
    from app.models.logo_rule import LogoRule as NewRule

    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(logo_rules)"))}
        if not cols or "account" in cols:
            return  # 全新库（create_all 已按新模型建表）或已完成迁移
        conn.execute(text("ALTER TABLE logo_rules RENAME TO logo_rules_old"))
        conn.commit()

    # 旧表已挪走，按新模型补建 logo_rules（此时 create_all 不会再跳过它）
    Base.metadata.create_all(bind=engine, tables=[NewRule.__table__])

    db = SessionLocal()
    moved_rules = 0
    try:
        from datetime import datetime as _dt

        def _parse_dt(v):
            """旧表 raw SQL 读出的时间通常是字符串，ORM DateTime 列只收 datetime。"""
            if isinstance(v, _dt):
                return v
            try:
                return _dt.fromisoformat(v) if v else None
            except (TypeError, ValueError):
                return None

        with engine.connect() as conn:
            old_rows = conn.execute(
                text(
                    "SELECT id, user_id, phone, signature, email, nickname, "
                    "logo_path, logo_url, created_at, is_deleted FROM logo_rules_old"
                )
            ).mappings().all()
        # 按 (user_id, 企业名) 聚合；软删旧规则不迁移（其 Logo 文件按归属清理后随之弃置）
        groups: dict[tuple[int, str], LogoGroup] = {}
        for row in old_rows:
            if row["is_deleted"]:
                continue
            key = (row["signature"] or row["nickname"] or row["phone"] or row["email"] or "未命名").strip()[:128]
            gk = (row["user_id"], key)
            if gk not in groups:
                g = LogoGroup(user_id=row["user_id"], name=key)
                db.add(g)
                db.flush()
                groups[gk] = g
            g = groups[gk]
            # 第一个带 Logo 的旧规则头像 → 企业默认头像（成员规则不再重复挂同一张图）
            if not g.logo_path and not g.logo_url and (row["logo_path"] or row["logo_url"]):
                g.logo_path = row["logo_path"]
                g.logo_url = row["logo_url"]
            members: list[tuple[str, str]] = []
            if row["phone"]:
                members.append((row["signature"] or "", row["phone"]))
            if row["email"]:
                members.append((row["signature"] or row["nickname"] or "", row["email"]))
            if not members:
                members.append((row["signature"] or row["nickname"] or "", ""))
            for sig, acct in members:
                dup = (
                    db.query(NewRule.id)
                    .filter(
                        NewRule.user_id == row["user_id"],
                        NewRule.group_id == g.id,
                        NewRule.signature == (sig or "")[:64],
                        NewRule.account == (acct or "")[:256],
                    )
                    .first()
                )
                if dup:
                    continue
                db.add(
                    NewRule(
                        user_id=row["user_id"],
                        group_id=g.id,
                        signature=(sig or "")[:64],
                        account=(acct or "")[:256],
                        created_at=_parse_dt(row["created_at"]),
                    )
                )
                moved_rules += 1
        db.commit()
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE logo_rules_old"))
            conn.commit()
        logger.info(
            "头像库已迁移为企业分组模型：%s 个企业分组、%s 条匹配规则",
            len(groups), moved_rules,
        )
    except Exception:
        db.rollback()
        logger.exception("头像库分组迁移失败（保留旧表 logo_rules_old 供排查）")
        raise
    finally:
        db.close()


def _migrate_email_passwords():
    """历史明文授权码统一加密为 Fernet 密文（幂等：密文跳过）。"""
    db = SessionLocal()
    try:
        sources = (
            db.query(Source)
            .filter(Source.type == "email", Source.email_password.isnot(None))
            .all()
        )
        migrated = 0
        for s in sources:
            if not s.email_password or s.email_password.startswith("gAAAA"):
                continue  # 已是密文
            s.email_password = encrypt_text(s.email_password)
            migrated += 1
        if migrated:
            db.commit()
            logger.info("已加密 %s 个来源的历史明文授权码", migrated)
    finally:
        db.close()


def _reset_stale_scans() -> None:
    """进程启动即代表上一次扫描线程已不存在；把残留的 running 状态标记为中断。

    音乐与影视共用同一状态结构，分别复位，避免 /scan 以「已在运行」为由
    拒绝启动、状态页永远显示 running。
    """
    from app.services.media_scan import reset_stale_scan

    for state_key, label in (("music_scan_state", "音乐"), ("video_scan_state", "影视")):
        reset_stale_scan(state_key, label)


def _cleanup_seed_system_sources() -> None:
    """删除历史「种子」系统来源及其事件消息（系统通知已接管，接入服务不再展示）。

    注意：这里必须是普通函数——曾误加 @asynccontextmanager，调用出来只是个
    context manager 对象、函数体从不执行，导致旧库里的「种子」系统来源一直
    留在 接入服务 里且界面不给删除按钮。
    """
    from app.models.message import Message

    db = SessionLocal()
    try:
        ids = [
            sid
            for (sid,) in db.query(Source.id)
            .filter(Source.is_system.is_(True), Source.name == "种子")
            .all()
        ]
        if not ids:
            return
        deleted = (
            db.query(Message)
            .filter(Message.source_id.in_(ids))
            .delete(synchronize_session=False)
        )
        db.query(Source).filter(Source.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
        logger.info("已清理种子系统来源 %s 个及其事件消息 %s 条", len(ids), deleted)
    except Exception:
        db.rollback()
        logger.exception("清理种子系统来源失败")


def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()
    # data/ 目录布局 v2（ihub_ 前缀）迁移必须最先跑：后续所有模块按新路径读写
    migrate_layout()
    migrate_network_proxy()
    _migrate_logo_groups()
    _migrate_email_passwords()
    # 系统通知上线（2026-10-25）：种子事件不再进消息中心，历史「种子」系统来源及其消息一并清除
    _cleanup_seed_system_sources()
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


@app.exception_handler(SeedError)
async def seed_error_handler(request: Request, exc: SeedError):
    """种子上游错误统一映射；消息已脱敏，不包含密码/API_TOKEN。"""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


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
