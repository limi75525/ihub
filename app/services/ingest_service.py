"""统一消息入库：去重、附件落盘、SSE 推送。"""

import hashlib
import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.message import Message
from app.models.source import Source
from app.services.events import broker
from app.core import data_dirs

logger = logging.getLogger(__name__)

_FILENAME_SAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def compute_dedup_hash(
    source_id: int, sender: str, title: str, content: str, received_at: datetime
) -> str:
    # 分钟级桶：同一分钟内来源+发送者+内容一致视为重复（转发重试场景）
    bucket = received_at.astimezone(timezone.utc).strftime("%Y%m%d%H%M")
    raw = f"{source_id}|{sender}|{title}|{content[:2048]}|{bucket}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def save_attachments(
    source_id: int, dedup_hash: str, attachments: list[dict]
) -> list[dict]:
    """attachments: [{filename, data(bytes), content_type}] → 存盘后返回元信息列表"""
    saved = []
    if not attachments:
        return saved
    base = Path(settings.DATA_DIR) / data_dirs.ATTACHMENTS / str(source_id) / dedup_hash[:16]
    base.mkdir(parents=True, exist_ok=True)
    for att in attachments:
        filename = _FILENAME_SAFE.sub("_", att.get("filename") or "unnamed").strip() or "unnamed"
        path = base / filename
        try:
            path.write_bytes(att["data"])
        except OSError:
            logger.exception("附件写入失败: %s", path)
            continue
        saved.append(
            {
                "filename": filename,
                "size": len(att["data"]),
                "content_type": att.get("content_type", ""),
                "path": str(path.relative_to(settings.DATA_DIR)),
            }
        )
    return saved


def delete_attachments(attachments_json: str | None) -> None:
    """回收消息附件占用的磁盘目录（消息行被物理删除时调用，与 save_attachments 对称）。"""
    try:
        items = json.loads(attachments_json or "[]")
    except (ValueError, TypeError):
        return
    if not isinstance(items, list):
        return
    data_dir = Path(settings.DATA_DIR).resolve()
    dirs = set()
    for att in items:
        if not isinstance(att, dict):
            continue
        rel = str(att.get("path") or "")
        if not rel:
            continue
        path = (data_dir / rel).resolve()
        if path == data_dir or not path.is_relative_to(data_dir):
            logger.warning("附件路径越界，已跳过: %s", rel)
            continue
        try:
            if path.is_file():
                path.unlink()
                dirs.add(path.parent)
        except OSError:
            logger.warning("附件删除失败: %s", path)
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)


def create_message(
    db: Session,
    source: Source,
    *,
    channel: str,
    sender: str = "",
    recipient: str = "",
    title: str = "",
    content_text: str = "",
    content_html: str | None = None,
    received_at: datetime | None = None,
    extra: dict | None = None,
    attachments: list[dict] | None = None,
    dedup_hash: str | None = None,
) -> Message | None:
    """返回新建的 Message；重复消息返回 None。dedup_hash 可由调用方提供稳定键（如邮件 Message-ID）。"""
    received_at = received_at or datetime.now(timezone.utc)
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)
    received_at = received_at.astimezone(timezone.utc)

    if not dedup_hash:
        dedup_hash = compute_dedup_hash(source.id, sender, title, content_text, received_at)

    existing = (
        db.query(Message)
        .filter(Message.source_id == source.id, Message.dedup_hash == dedup_hash)
        .first()
    )
    if existing:
        return None

    att_meta = save_attachments(source.id, dedup_hash, attachments or [])

    msg = Message(
        user_id=source.user_id,
        source_id=source.id,
        channel=channel,
        sender=sender[:256],
        recipient=recipient[:256],
        title=(title or "")[:512],
        content_text=content_text,
        content_html=content_html,
        attachments=json.dumps(att_meta, ensure_ascii=False),
        extra=json.dumps(extra or {}, ensure_ascii=False),
        dedup_hash=dedup_hash,
        received_at=received_at,
    )
    source.last_seen_at = datetime.now(timezone.utc)
    db.add(msg)
    try:
        db.commit()
    except IntegrityError:
        # 并发重复推送（转发重试/离线补推）撞唯一约束：本进程刚落盘的附件成为孤儿，
        # 必须回收。只能按 att_meta 登记的**本进程写入的具体文件**逐个删除——
        # 并发窗口内另一请求可能已提交了同 dedup 前缀目录下的消息，整目录 rmtree
        # 会删掉它已提交消息的附件（文件按 dedup 前缀共享目录）。
        db.rollback()
        for att in att_meta:
            try:
                p = (Path(settings.DATA_DIR) / att["path"]).resolve()
                if p.is_relative_to(Path(settings.DATA_DIR).resolve()):
                    p.unlink(missing_ok=True)
            except OSError:
                logger.warning("孤儿附件回收失败: %s", att.get("path"))
        return None

    db.refresh(msg)
    broker.publish(
        {
            "type": "message.new",
            "user_id": msg.user_id,
            "message": {
                "id": msg.id,
                "source_id": msg.source_id,
                "channel": msg.channel,
                "sender": msg.sender,
                "title": msg.title,
                "content_text": (msg.content_text or "")[:200],
                "received_at": msg.received_at.isoformat(),
            },
        }
    )
    return msg
