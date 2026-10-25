from datetime import datetime

from pydantic import BaseModel, Field, model_validator

EMAIL_PRESETS = {
    "qq": {"imap_host": "imap.qq.com", "imap_port": 993, "imap_ssl": True},
    "gmail": {"imap_host": "imap.gmail.com", "imap_port": 993, "imap_ssl": True},
    "outlook": {"imap_host": "outlook.office365.com", "imap_port": 993, "imap_ssl": True},
    "163": {"imap_host": "imap.163.com", "imap_port": 993, "imap_ssl": True},
}


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    type: str = Field(pattern="^(sms|email|api)$")

    # email 专用
    preset: str | None = None
    imap_host: str | None = Field(default=None, max_length=200)
    imap_port: int | None = Field(default=None, ge=1, le=65535)
    imap_ssl: bool = True
    # SSL 证书校验：默认开启；自签证书的私有邮件服务器可显式关闭
    imap_verify_tls: bool = True
    email_account: str | None = None
    email_password: str | None = None
    poll_interval: int = Field(default=120, ge=30, le=86400)
    folder: str = "INBOX"

    # api/email 通用 Logo（在线地址，可选）
    logo_url: str | None = Field(default=None, max_length=1024)
    # API 来源的消息类型：sms（手机/短信硬件）→ channel=sms；notify（服务通知）→ channel=api
    kind: str = Field(default="notify", pattern="^(sms|notify)$")

    @model_validator(mode="after")
    def apply_preset_and_validate(self):
        if self.type == "email":
            if self.preset and self.preset in EMAIL_PRESETS:
                for k, v in EMAIL_PRESETS[self.preset].items():
                    setattr(self, k, v)
            if not self.imap_host or not self.email_account or not self.email_password:
                raise ValueError("邮箱接入需要 imap_host、email_account、email_password")
        return self


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    is_active: bool | None = None
    # 编辑时可改消息类型（短信/通知来源）：同步来源类型与绑定设备 kind
    type: str | None = Field(default=None, pattern="^(sms|api)$")

    imap_host: str | None = Field(default=None, max_length=200)
    imap_port: int | None = Field(default=None, ge=1, le=65535)
    imap_ssl: bool | None = None
    imap_verify_tls: bool | None = None
    email_account: str | None = None
    email_password: str | None = None
    poll_interval: int | None = Field(default=None, ge=30, le=86400)
    folder: str | None = None

    # Logo 相关：置 URL 则改用 URL；置空字符串清除（含上传文件）
    logo_url: str | None = Field(default=None, max_length=1024)


class SourceOut(BaseModel):
    id: int
    name: str
    type: str
    # 旧版 token 推送通道已废弃，不再下发该凭据
    imap_host: str | None
    imap_port: int | None
    imap_ssl: bool
    imap_verify_tls: bool = True
    email_account: str | None
    poll_interval: int
    folder: str
    is_active: bool
    # 系统来源（种子事件等）：普通用户不下发；管理员可见且只能启停
    is_system: bool = False
    last_seen_at: datetime | None
    last_poll_at: datetime | None
    created_at: datetime
    message_count: int = 0
    unread_count: int = 0
    # 已解析可直接用于 <img src> 的 Logo 地址（上传文件或外链）
    logo: str | None = None
    # logo 来源类型：file（本地上传）/ url（在线地址）/ None
    logo_kind: str | None = None

    model_config = {"from_attributes": True}


class EmailTestIn(BaseModel):
    preset: str | None = None
    imap_host: str | None = Field(default=None, max_length=200)
    imap_port: int | None = Field(default=None, ge=1, le=65535)
    imap_ssl: bool = True
    imap_verify_tls: bool = True
    email_account: str
    email_password: str
    folder: str = "INBOX"

    @model_validator(mode="after")
    def apply_preset(self):
        if self.preset and self.preset in EMAIL_PRESETS:
            for k, v in EMAIL_PRESETS[self.preset].items():
                setattr(self, k, v)
        if not self.imap_host:
            raise ValueError("缺少 imap_host")
        return self
