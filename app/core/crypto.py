"""字段级加密：基于 SECRET_KEY 派生的 Fernet。

设备密钥（devices）与邮箱授权码（sources.email_password）共用同一套
加解密；decrypt_text 对非密文（历史明文）返回 None，由调用方决定回退。
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import SECRET_KEY


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt_text(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_text(cipher: str) -> str | None:
    try:
        return _fernet().decrypt(cipher.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


_FERNET_PREFIX = "gAAAAA"  # Fernet token 版本字节 0x80 的 base64 前缀


def looks_encrypted(value: str) -> bool:
    """是否“看起来是 Fernet 密文”。

    用于区分两种 decrypt_text 返回 None 的情况：历史明文（可直接使用）
    与密钥变更后解不开的密文（必须报错，绝不能把密文当明文密码提交给第三方服务）。
    """
    return value.startswith(_FERNET_PREFIX) and len(value) >= 80
