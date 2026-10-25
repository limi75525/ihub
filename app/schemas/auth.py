from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.core.timeutil import as_utc


def _ensure_utc(cls, v):
    return as_utc(v)


# bcrypt 只处理前 72 字节，超出会直接抛 ValueError（注册/改密会变成 500），
# 因此按字节数设上限并给出明确提示，而不是让请求以 500 结束。
MAX_PASSWORD_BYTES = 72


def _check_password_bytes(v: str) -> str:
    if len(v.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("密码过长：最多 72 字节（约 72 个英文字符或 24 个汉字）")
    return v


class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=MAX_PASSWORD_BYTES)
    # 图形验证码（系统开启后必填）
    captcha_id: str | None = Field(default=None, max_length=64)
    captcha_code: str | None = Field(default=None, max_length=64)

    _pw_bytes = field_validator("password")(_check_password_bytes)


class LoginIn(BaseModel):
    # 与 RegisterIn 同上限：登录请求未认证，字段长度不设防会被拿来灌大解析内存
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_BYTES)
    captcha_id: str | None = Field(default=None, max_length=64)
    captcha_code: str | None = Field(default=None, max_length=64)
    # true 时签发 HttpOnly 长期令牌，前端不保存密码
    remember_me: bool = False


class ProfileUpdateIn(BaseModel):
    nickname: str = Field(min_length=0, max_length=64)
    signature: str = Field(default="", max_length=128)
    email: str = Field(default="", max_length=128)


class TokenOut(BaseModel):
    access_token: str
    # 媒体访问密钥：图片/附件等 GET 资源的 ?token= 使用（泄露影响面小于 JWT，改密码即轮换）
    media_key: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: int
    username: str
    nickname: str = ""
    signature: str = ""
    email: str = ""
    avatar_url: str | None = None
    role: str
    is_active: bool
    created_at: datetime

    _tz = field_validator("created_at", mode="before")(_ensure_utc)
    model_config = {"from_attributes": True}


class MeOut(UserOut):
    """当前登录用户：附带自己的 media_key（img 标签无法携带请求头）"""

    media_key: str

    model_config = {"from_attributes": True}


class PasswordChangeIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=MAX_PASSWORD_BYTES)

    _pw_bytes = field_validator("new_password")(_check_password_bytes)


TokenOut.model_rebuild()
