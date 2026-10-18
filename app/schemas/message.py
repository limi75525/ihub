from datetime import datetime

from pydantic import BaseModel, Field


class AttachmentOut(BaseModel):
    filename: str
    size: int
    content_type: str = ""


class MessageOut(BaseModel):
    id: int
    source_id: int
    source_name: str = ""
    source_logo: str | None = None
    channel: str
    sender: str
    recipient: str = ""
    title: str
    content_text: str
    has_html: bool = False
    attachments: list[AttachmentOut] = []
    extra: dict = {}
    is_read: bool
    is_starred: bool = False
    is_pinned: bool = False
    avatar: str | None = None
    received_at: datetime
    created_at: datetime


class MessageDetailOut(MessageOut):
    content_html: str | None = None


class MessageListOut(BaseModel):
    total: int
    unread: int
    items: list[MessageOut]


class BatchActionIn(BaseModel):
    action: str = Field(pattern="^(read|unread|delete|star|unstar|pin|unpin)$")
    ids: list[int] = Field(min_length=1, max_length=500)


class MessageIngestIn(BaseModel):
    title: str | None = None
    content: str = Field(min_length=1, max_length=100000)
    sender: str | None = None
    extra: dict | None = None
    timestamp: int | None = None  # Unix 秒级时间戳，可选


class SmsIngestIn(BaseModel):
    # 兼容 SmsForwarder 常用模板字段别名
    content: str | None = Field(default=None, max_length=100000)
    msg: str | None = Field(default=None, max_length=100000)
    text: str | None = Field(default=None, max_length=100000)
    sender: str | None = None
    from_: str | None = Field(default=None, alias="from")
    device: str | None = None
    slot: str | None = None
    timestamp: int | None = None

    def get_content(self) -> str:
        return self.content or self.msg or self.text or ""

    def get_sender(self) -> str:
        return self.sender or self.from_ or ""
