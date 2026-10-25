import secrets
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_prefix="IHUB_", extra="ignore"
    )

    APP_NAME: str = "iHub"
    # 后端版本：与 Web 前端版本同步递增（发版时一起改），版本更新检查用
    APP_VERSION: str = "1.6.6"

    # 数据目录：SQLite 数据库、附件、密钥都放这里，Docker 挂载卷指向它
    # 默认落在仓库内 iHub/data（与 docker-compose 的 ./data 挂载点一致）
    DATA_DIR: Path = BACKEND_DIR / "data"

    # 留空则首次启动自动生成并持久化到 DATA_DIR/.secret_key
    SECRET_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_DAYS: int = 7
    # 勾选「记住我」时 HttpOnly Cookie 的有效期；到期后必须重新登录
    REMEMBER_ME_DAYS: int = 30

    # sms/api 类型来源超过该分钟数无推送则视为离线
    DEVICE_OFFLINE_MINUTES: int = 10

    # 用于统计"今日"的时区
    TIMEZONE: str = "Asia/Shanghai"

    # CORS 白名单：逗号分隔，留空=不返回跨域头（nginx 同源部署无需配置；
    # 仅前端与其他源分离的开发/部署场景需要，如 "http://localhost:15173"）
    CORS_ORIGINS: str = ""

    # 是否采信 X-Real-IP / X-Forwarded-For 作为客户端 IP（限流维度）。
    # 默认 false：直接使用 TCP 对端地址。仅当部署在会覆写该头的反向代理之后才开启，
    # 否则客户端可伪造该头绕过登录锁定与推送限流。
    TRUST_PROXY_HEADERS: bool = False
    # 可信代理层数：X-Forwarded-For 从右往左第 N 个值视为真实客户端。
    # 单层反代（Lucky / 本机 nginx）保持 1；前面还有 Cloudflare 等 CDN 时设为 2。
    TRUSTED_PROXY_HOPS: int = 1

    # 邮箱来源的目标地址（test-email / 创建与修改邮箱源）默认拒绝解析到
    # 私网/环回/链路本地/保留段的域名（登录用户可借此探测内网，IMAP 协议 SSRF）。
    # 自建内网邮件服务器的部署设 IHUB_ALLOW_PRIVATE_EMAIL_HOST=true 豁免。
    ALLOW_PRIVATE_EMAIL_HOST: bool = False


settings = Settings()
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)


def _ensure_secret_key() -> str:
    if settings.SECRET_KEY:
        return settings.SECRET_KEY
    key_file = settings.DATA_DIR / ".secret_key"
    if key_file.exists():
        settings.SECRET_KEY = key_file.read_text(encoding="utf-8").strip()
    else:
        settings.SECRET_KEY = secrets.token_hex(32)
        key_file.write_text(settings.SECRET_KEY, encoding="utf-8")
        try:
            # 该密钥同时是 JWT 签名密钥与 Fernet 根密钥（邮箱授权码/设备密钥的派生源），
            # 多用户 Linux 宿主机上必须限制为仅属主可读（Windows 无 POSIX 权限位，忽略失败）
            key_file.chmod(0o600)
        except OSError:
            pass
    return settings.SECRET_KEY


SECRET_KEY = _ensure_secret_key()
