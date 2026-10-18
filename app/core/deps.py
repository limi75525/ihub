from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User


def _extract_token(request: Request, token_query: str | None) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth.removeprefix("Bearer ").strip()
    if token_query:
        return token_query
    return None


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """完整 JWT 只认 Authorization 头，不接受 ?token= 查询参数。

    query 参数会落入反代 access log / 浏览器历史 / Referer；需要 URL 传凭据的
    只有 <img>/<audio> 等媒体标签（走 get_media_user 的 media_key，泄露面小且可轮换）。
    SSE 等长连接前端用 fetch 流 + Authorization 头，同样不需要 query。
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未登录或登录已过期",
        headers={"WWW-Authenticate": "Bearer"},
    )
    raw = _extract_token(request, None)
    if not raw:
        raise credentials_exception
    payload = decode_access_token(raw)
    if not payload:
        raise credentials_exception
    try:
        user_id = int(payload["sub"])
        pwd_version = int(payload.get("pwd_version", -1))
    except (KeyError, TypeError, ValueError):
        # 签名有效但载荷不完整/类型异常（如旧版本 token）：按未登录处理而非 500
        raise credentials_exception
    user = db.get(User, user_id)
    if not user or not user.is_active or user.is_deleted:
        raise credentials_exception
    # 密码版本校验：改密码/重置密码后旧 token 一律失效
    if pwd_version != (user.pwd_version or 0):
        raise credentials_exception
    return user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def get_media_user(
    request: Request,
    db: Session = Depends(get_db),
    token: str | None = Query(default=None, alias="token"),
) -> User:
    """媒体资源鉴权：仅接受用户的 media_key（?token= 或 Bearer）。

    media_key 只能读取图片/附件等 GET 资源，泄露影响面远小于完整 JWT；
    在反代 access log 中出现也是可轮换、可吊销的。
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="媒体凭据无效或已过期",
    )
    raw = _extract_token(request, token)
    if not raw:
        raise credentials_exception
    user = (
        db.query(User)
        .filter(
            User.media_key == raw,
            User.is_active.is_(True),
            User.is_deleted.is_(False),
        )
        .first()
    )
    if not user:
        raise credentials_exception
    return user
