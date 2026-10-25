from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import SECRET_KEY, settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _create_token(
    user_id: int,
    username: str,
    role: str,
    pwd_version: int,
    *,
    purpose: str,
    days: int,
) -> str:
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        # 密码版本：与 users.pwd_version 不一致即视为失效（改密码/重置密码后旧 token 全灭）
        "pwd_version": pwd_version,
        # remember cookie 里的长期令牌不能当访问令牌用；老 token 没有 purpose 字段时按 access 兼容
        "purpose": purpose,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(days=days),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(user_id: int, username: str, role: str, pwd_version: int = 0) -> str:
    return _create_token(
        user_id,
        username,
        role,
        pwd_version,
        purpose="access",
        days=settings.ACCESS_TOKEN_EXPIRE_DAYS,
    )


def create_remember_token(user_id: int, username: str, role: str, pwd_version: int = 0) -> str:
    return _create_token(
        user_id,
        username,
        role,
        pwd_version,
        purpose="remember",
        days=settings.REMEMBER_ME_DAYS,
    )


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
