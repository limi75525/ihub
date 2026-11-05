"""消息出参序列化（messages 列表/详情与 sources 最近消息共用）。

从 api/v1/messages.py 下沉：sources.py 也要把 Message 组装成同样的出参结构，
路由层互相 import 私有函数违反依赖方向。
"""

from __future__ import annotations

from app.core.timeutil import as_utc
from app.models.message import Message


def _loads_json(raw, default):
    """容忍脏数据：单条记录的 JSON 损坏不应让整个列表接口 500。"""
    import json
    try:
        value = json.loads(raw or "")
    except (ValueError, TypeError):
        return default
    return value if isinstance(value, type(default)) else default


def message_out(m: Message, source_name: str = "", source_logo: str | None = None, detail: bool = False, avatar: str | None = None) -> dict:
    atts = _loads_json(m.attachments, [])
    d = {
        "id": m.id,
        "source_id": m.source_id,
        "source_name": source_name,
        "source_logo": source_logo,
        "channel": m.channel,
        "sender": m.sender or "",
        "recipient": m.recipient or "",
        "title": m.title or "",
        # 列表仅做摘要截断减小载荷；详情必须返回全文（截断的纯文本邮件在详情页表现为「内容不完整」）
        "content_text": (m.content_text or "") if detail else (m.content_text or "")[:400],
        "content_html": m.content_html,
        "has_html": bool(m.content_html),
        "attachments": [
            {
                "filename": a.get("filename", ""),
                "size": a.get("size", 0),
                "content_type": a.get("content_type", ""),
            }
            for a in atts
        ],
        "extra": _loads_json(m.extra, {}),
        "avatar": avatar,
        "is_read": m.is_read,
        "is_starred": bool(m.is_starred),
        "is_pinned": bool(m.is_pinned),
        "received_at": as_utc(m.received_at),
        "created_at": as_utc(m.created_at),
    }
    if not detail:
        d.pop("content_html")
    return d


