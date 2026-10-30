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


    timestamp: int | None = None

    def get_content(self) -> str:
        return self.content or self.msg or self.text or ""

    def get_sender(self) -> str:
        return self.sender or self.from_ or ""
