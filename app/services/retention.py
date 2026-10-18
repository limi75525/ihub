"""历史消息定时清理：按系统设置保留天数删除本平台副本（不影响邮件源服务器）。"""

import logging
import threading
from datetime import datetime, timedelta, timezone

from app.db.session import SessionLocal
from app.models.message import Message
from app.models.system_setting import get_setting, set_setting
from app.services.ingest_service import delete_attachments

logger = logging.getLogger(__name__)

# 互斥：手动「立即清理」（后台线程）与调度器周期任务可能并发，删除本身幂等，
# 但没必要让两把大删除同时跑；拿不到锁的一方直接放弃本轮
_cleanup_lock = threading.Lock()


def get_retention_days() -> int:
    try:
        days = int(get_setting("retention_days", "0"))
    except (TypeError, ValueError):
        return 0
    return days if days > 0 else 0


def run_retention_cleanup() -> int | None:
    """删除 received_at 早于保留期限的消息，返回删除条数（未启用返回 0）。

    大库时单轮删除可能持续数十秒：调用方（设置页「立即清理」）应放到后台线程，
    不要在请求线程里同步等待。
    返回 None 仅表示「互斥锁被占、本轮未执行」（调度任务与手动清理并发时），
    与「执行了但没删东西」的 0 区分——延迟清理不能在未执行时清掉 pending 标记。
    """
    days = get_retention_days()
    if days <= 0:
        return 0
    if not _cleanup_lock.acquire(blocking=False):
        return None  # 已有清理在跑，本轮放弃（幂等，下轮调度会补齐）
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    db = SessionLocal()
    try:
        # 先回收附件目录，再删行：批量 delete 拿不到 attachments 字段
        expired = (
            db.query(Message.id, Message.attachments)
            .filter(Message.received_at < cutoff)
            .all()
        )
        for _id, atts in expired:
            delete_attachments(atts)
        deleted = (
            db.query(Message)
            .filter(Message.received_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
    finally:
        db.close()
        _cleanup_lock.release()
    if deleted:
        logger.info("定时清理：已删除 %s 条超过 %s 天的历史消息", deleted, days)
    return deleted


def get_pending_at() -> datetime | None:
    """短期化后待执行的延迟清理时间（未设置返回 None）。"""
    v = get_setting("retention_pending_at", "")
    if not v:
        return None
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def set_pending_at(at: datetime | None) -> None:
    set_setting("retention_pending_at", at.isoformat() if at else "")


def check_pending() -> bool:
    """到期则按当前保留天数执行延迟清理。返回是否执行了删除。"""
    at = get_pending_at()
    if not at or at > datetime.now(timezone.utc):
        return False
    deleted = run_retention_cleanup()
    if deleted is None:
        # 恰逢每日任务/手动清理持锁：本轮没真正执行，保留 pending 标记下轮再试，
        # 否则用户已确认要删的数据会被静默跳过
        return False
    set_pending_at(None)
    if deleted:
        logger.info("延迟清理：已删除 %s 条历史消息（10 分钟确认期结束）", deleted)
    return deleted > 0
