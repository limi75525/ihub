import html as html_mod
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.fsutil import safe_mtime
from app.core.netutil import client_ip
from app.core.ratelimit import (
    check_captcha_allowed,
    check_ip_allowed,
    check_login_allowed,
    check_register_allowed,
    record_captcha,
    record_login_failure,
    record_login_success,
    record_register,
)
from app.core.security import create_access_token, hash_password, verify_password

# 时序抹平用的假哈希（随机口令生成，永不可能验证通过）
_DUMMY_BCRYPT_HASH = hash_password(secrets.token_urlsafe(24))
from app.core.timeutil import as_utc
from app.db.session import get_db
from app.models.system_setting import get_setting_db
from app.models.user import User
from app.schemas.auth import (
    LoginIn,
    MeOut,
    PasswordChangeIn,
    ProfileUpdateIn,
    RegisterIn,
    TokenOut,
    UserOut,
)
from app.services.uploads import read_limited, save_unique

router = APIRouter(prefix="/auth", tags=["auth"])

ALLOWED_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
}


def _deep_decode(value: str) -> str:
    """反复实体解码直到稳定（至多 5 轮），并去掉浏览器会忽略的空白控制符。

    浏览器解析 URL 属性时会剥掉 tab/换行，因此 `jav\\tascript:` 与实体编码
    `&#106;avascript:` 实际等价——必须在解码+归一化之后做判断才可靠。
    """
    text = value
    for _ in range(5):
        decoded = html_mod.unescape(text)
        if decoded == text:
            break
        text = decoded
    return re.sub(r"[\t\r\n\f\x00\s]", "", text)


_DANGEROUS_SCHEME = ("javascript:", "vbscript:", "data:text/html", "data:image/svg+xml")
# href/src 允许的 scheme 白名单（deep_decode 已去掉空白，统一小写判断）
_SAFE_ATTR_SCHEME = ("#", "/", "http:", "https:", "mailto:", "data:image/png", "data:image/jpeg",
                     "data:image/gif", "data:image/webp")
# 连同内容整体移除的危险元素（SMIL 动画可通过 attributeName=href 注入 javascript: 目标）
_SVG_DROP_TAGS = ("script", "animate", "set", "handler", "foreignobject", "iframe", "embed", "object")
_SCRIPT_ELEMENT_RE = re.compile(
    r"<\s*(?:" + "|".join(_SVG_DROP_TAGS) + r")\b[^>]*>.*?<\s*/\s*(?:" + "|".join(_SVG_DROP_TAGS) + r")\s*>|"
    r"<\s*(?:" + "|".join(_SVG_DROP_TAGS) + r")\b[^>]*/?>",
    re.IGNORECASE | re.DOTALL,
)
_ATTR_RE = re.compile(
    r"\s([a-zA-Z_:][-\w:.]*)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)"
)


def _svg_attr_name(name: str) -> str:
    return _deep_decode(name).lower()


def sanitize_svg(data: bytes) -> bytes:
    """SVG 是 XML 文档，可携带脚本与事件属性，同源直接访问会造成存储型 XSS。

    清洗策略（正则不可信时宁可整份拒绝）：
    1. 移除 script / SMIL 动画（animate/set/handler）/ foreignObject / 嵌入对象元素；
    2. 剥除 on* 事件属性；
    3. href/xlink:href/src 白名单放行（http/https/mailto/#/相对路径/data:image），
       其余一律移除——实体编码与 tab 混入的 javascript: 已在解码归一化后识别；
    4. 终检：对整份文档深度解码后仍出现 javascript:/vbscript: 目标 → 返回空字节
       （调用方按「文件为空」拒绝上传）。
    """
    text = data.decode("utf-8", "replace")
    text = _SCRIPT_ELEMENT_RE.sub("", text)

    def _clean_attrs(match: re.Match) -> str:
        name, raw_value = match.group(1), match.group(2)
        value = raw_value[1:-1] if raw_value[:1] in ("\"", "'") and raw_value[-1:] == raw_value[:1] else raw_value
        lname = _svg_attr_name(name)
        if lname.startswith("on"):
            return ""
        if lname in ("href", "xlink:href", "src"):
            probe = _deep_decode(value).lower()
            if probe.startswith(_DANGEROUS_SCHEME):
                return ""
            if not probe.startswith(_SAFE_ATTR_SCHEME):
                return ""
        return match.group(0)

    text = _ATTR_RE.sub(_clean_attrs, text)

    normalized = _deep_decode(text).lower()
    if re.search(r"=\s*[\"']?(javascript|vbscript)\s*:", normalized) or "<script" in normalized:
        return b""
    return text.encode("utf-8")


def media_file_headers(path: Path) -> dict:
    """SVG 文件加 Content-Disposition: attachment：<img> 展示不受影响，
    但直接在浏览器打开该 URL 时下载而非执行（防同源脚本运行）。"""
    if path.suffix.lower() == ".svg":
        return {"Content-Disposition": "attachment"}
    return {}


MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 兜底默认 2MB；实际以 设置 → 系统 的 avatar_max_mb 为准（1-20MB）


def avatar_upload_max_size() -> int:
    """个人头像上限与头像库同源（avatar_max_mb 设置），避免前端放行、后端拒绝的错位。"""
    from app.models.system_setting import get_int_setting

    return get_int_setting("avatar_max_mb", MAX_AVATAR_SIZE // (1024 * 1024), 1, 20) * 1024 * 1024


def registration_open(db: Session) -> bool:
    return get_setting_db(db, "registration_open", "true") == "true"


def captcha_enabled(db: Session) -> bool:
    return get_setting_db(db, "captcha_enabled", "false") == "true"


def _check_captcha(db: Session, captcha_id: str | None, captcha_code: str | None) -> None:
    """验证码开关开启时校验（一次性消费）；未开启直接放行。"""
    if not captcha_enabled(db):
        return
    from app.services.captcha import verify

    if not captcha_id or not captcha_code:
        raise HTTPException(400, "请输入验证码")
    if not verify(captcha_id, captcha_code):
        raise HTTPException(400, "验证码错误或已过期")


def ensure_media_key(user: User, db: Session) -> str:
    """保证用户持有媒体密钥（注册/登录时惰性生成）。"""
    if not user.media_key:
        user.media_key = secrets.token_urlsafe(24)
        db.commit()
    return user.media_key or ""


def rotate_media_key(user: User) -> str:
    """改密码/重置密码时轮换媒体密钥，旧 URL 上的 key 立即失效。"""
    user.media_key = secrets.token_urlsafe(24)
    return user.media_key or ""


@router.get("/captcha")
def get_captcha(request: Request):
    """签发图形验证码：返回 base64 PNG 数据地址。

    未认证端点且要跑 PIL 渲染（CPU），且验证码存储槽位有限（_MAX_STORED=200）：
    不限流可被高频刷签发把他人「展示中待提交」的验证码挤出存储，卡死登录/注册。
    """
    from app.services.captcha import data_url, issue

    ip = client_ip(request)
    try:
        check_captcha_allowed(ip)
    except PermissionError as e:
        raise HTTPException(429, str(e))
    cid, code = issue()
    record_captcha(ip)
    return {"id": cid, "image": data_url(code)}


@router.get("/bootstrap-status")
def bootstrap_status(db: Session = Depends(get_db)):
    """注册页初始化提示：是否首个账号（成为管理员）、是否开放注册、是否需要验证码。"""
    first_user = (db.query(func.count(User.id)).filter(User.is_deleted.is_(False)).scalar() or 0) == 0
    return {
        "first_user": first_user,
        "open": registration_open(db) if not first_user else True,
        "captcha_enabled": captcha_enabled(db),
    }


def _user_out(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.avatar_url = avatar_url_for(user)
    return out


def _token_for(user: User, db: Session) -> TokenOut:
    media_key = ensure_media_key(user, db)
    return TokenOut(
        access_token=create_access_token(user.id, user.username, user.role, user.pwd_version or 0),
        media_key=media_key,
        user=_user_out(user),
    )


def avatar_url_for(user: User) -> str | None:
    """头像地址附带文件修改时间，更换头像后 URL 变化，规避浏览器缓存旧图。"""
    if not user.avatar_path:
        return None
    path = Path(settings.DATA_DIR) / user.avatar_path
    v = safe_mtime(path)
    if not v:
        return None
    return f"/api/v1/users/avatar/{user.id}?v={v}"


_PLATFORM_INIT_KEY = "platform_initialized"


def _claim_first_user_slot(db: Session) -> bool:
    """原子占位「平台初始化」标记：INSERT OR IGNORE 命中（rowcount==1）即本请求是占位者。

    首个用户的判定原来是无锁的「先查 count 再插入」，两个不同用户名的并发注册
    都可能读到 count==0 而双双成为管理员（TOCTOU）。system_settings.key 是主键，
    SQLite 单写者语义下 INSERT OR IGNORE 天然原子：并发下只有一个请求能插入成功。
    """
    from sqlalchemy import text

    row = db.execute(
        text(
            "INSERT OR IGNORE INTO system_settings (key, value, is_deleted, deleted_at) "
            f"VALUES ('{_PLATFORM_INIT_KEY}', :ts, 0, NULL)"
        ),
        {"ts": datetime.now(timezone.utc).isoformat()},
    )
    return (row.rowcount or 0) == 1


@router.post("/register", response_model=TokenOut)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    # 限流在前：注册要跑 bcrypt（刻意昂贵的哈希），未认证端点不能无限调用
    try:
        check_register_allowed(ip)
    except PermissionError as e:
        raise HTTPException(429, str(e))
    _check_captcha(db, body.captcha_id, body.captcha_code)
    # 原子占位成功 = 本请求最先抵达；仅当实例确实还没有活跃用户时引导为管理员。
    # 老实例升级场景（有用户、无占位行）：占位者 active>0 会落为普通用户，无副作用。
    first_slot = _claim_first_user_slot(db)
    user_count = db.query(func.count(User.id)).filter(User.is_deleted.is_(False)).scalar() or 0
    if first_slot and user_count == 0:
        role = "admin"  # 首个用户引导为管理员
    else:
        role = "user"
        if not registration_open(db):
            raise HTTPException(403, "管理员已关闭注册")

    if db.query(User).filter(User.username == body.username, User.is_deleted.is_(False)).first():
        raise HTTPException(400, "用户名已被占用")

    user = User(username=body.username, password_hash=hash_password(body.password), role=role)
    db.add(user)
    record_register(ip)
    try:
        db.commit()
    except IntegrityError:
        # 用户名查重与插入非原子：并发同名注册时后到者撞唯一约束，回滚后按占用返回
        db.rollback()
        raise HTTPException(400, "用户名已被占用")
    db.refresh(user)
    return _token_for(user, db)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    # 限流在前：被锁定的请求不消耗验证码
    try:
        check_ip_allowed(ip)
        check_login_allowed(body.username)
    except PermissionError as e:
        raise HTTPException(429, str(e))
    _check_captcha(db, body.captcha_id, body.captcha_code)
    user = db.query(User).filter(User.username == body.username, User.is_deleted.is_(False)).first()
    if user is None:
        # 用户不存在时也做一次等价 bcrypt 校验，抹平响应时间差，
        # 防止用「响应耗时」枚举有效用户名（真实校验约 100ms+，跳过则仅 ~3ms）
        verify_password(body.password, _DUMMY_BCRYPT_HASH)
        record_login_failure(body.username, ip)
        raise HTTPException(401, "用户名或密码错误")
    if not verify_password(body.password, user.password_hash):
        record_login_failure(body.username, ip)
        raise HTTPException(401, "用户名或密码错误")
    if not user.is_active:
        # 禁用账号校验通过也不清除失败计数：否则可被用来刷低锁定阈值
        raise HTTPException(403, "账号已被禁用")
    record_login_success(body.username, ip)
    return _token_for(user, db)


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    media_key = ensure_media_key(user, db)
    out = MeOut(
        id=user.id,
        username=user.username,
        nickname=user.nickname or "",
        # signature/email 不传会给 schema 默认空串，前端刷新后签名与邮箱显示丢失
        signature=user.signature or "",
        email=user.email or "",
        avatar_url=avatar_url_for(user),
        role=user.role,
        is_active=user.is_active,
        created_at=as_utc(user.created_at),
        media_key=media_key,
    )
    return out


@router.patch("/profile", response_model=UserOut)
def update_profile(
    body: ProfileUpdateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user.nickname = body.nickname.strip()
    user.signature = body.signature.strip()[:128]
    user.email = body.email.strip()[:128]
    db.commit()
    db.refresh(user)
    return _user_out(user)


def _store_avatar(user: User, ext: str, data: bytes) -> str:
    """删除旧头像并落盘新文件（磁盘写，放线程池）；返回入库用的相对路径。"""
    if user.avatar_path:
        old = Path(settings.DATA_DIR) / user.avatar_path
        old.unlink(missing_ok=True)
    return save_unique("avatars", f"user_{user.id}", ext, data)


async def apply_avatar_upload(user: User, file: UploadFile) -> None:
    """头像上传的公共校验与落盘（本人 /auth/avatar 与管理员 /users/{id}/avatar 共用）。

    只改 user.avatar_path，不提交事务——交由调用方决定何时 commit/refresh。
    """
    ext = ALLOWED_IMAGE_TYPES.get(file.content_type or "")
    if not ext:
        raise HTTPException(400, "仅支持 PNG / JPG / WebP / SVG / ICO 图片")
    # 设置读取（独立会话）与图片解码/落盘都不在事件循环里跑
    limit = await run_in_threadpool(avatar_upload_max_size)
    data = await read_limited(file, limit, f"头像不能超过 {limit // 1024 // 1024}MB（可在 设置 → 系统 → 附件上传限制 调整）")
    if ext == ".svg":
        data = await run_in_threadpool(sanitize_svg, data)
    if not data:
        raise HTTPException(400, "文件为空")
    user.avatar_path = await run_in_threadpool(_store_avatar, user, ext, data)


@router.post("/avatar", response_model=UserOut)
async def upload_avatar(
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    await apply_avatar_upload(user, file)
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.post("/password", response_model=TokenOut)
def change_password(
    body: PasswordChangeIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 原密码校验限速：JWT 被盗时可绕过登录接口的锁定机制在线爆破原密码，
    # 复用登录失败的计数器（独立命名空间，不与登录互相干扰）
    pw_key = f"pwchange:{user.username}"
    ip = client_ip(request)
    try:
        check_login_allowed(pw_key)
    except PermissionError as e:
        raise HTTPException(429, str(e))
    if not verify_password(body.old_password, user.password_hash):
        record_login_failure(pw_key, ip)
        raise HTTPException(400, "原密码错误")
    record_login_success(pw_key, ip)
    user.password_hash = hash_password(body.new_password)
    # 版本 +1 使该用户所有旧 JWT 立即失效；媒体密钥同步轮换
    user.pwd_version = (user.pwd_version or 0) + 1
    rotate_media_key(user)
    db.commit()
    db.refresh(user)
    # 签发新 token：前端保存后可无感继续使用
    return _token_for(user, db)
