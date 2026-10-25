"""系统通知服务：顶栏铃铛的数据源（notifications 表）。

- 事件源统一从 notify_service.create 走：种子事件（seed_events 后台线程）、
  登录提醒（auth.login）、扫描完成（music/video 扫描线程）、后台服务失败
  （janitor/扫描/转媒体 worker）、站点离线（janitor 每日巡检）、版本更新（调度任务）。
- 与消息中心完全解耦：不再生成「种子」系统来源，也不再写 messages 表。
- 每条通知创建后经 SSE broker 广播 notification.new；前端收到后刷新未读数
  （事件不携带内容，各端各自拉取自己的未读数，无越权泄露）。
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.notification import Notification
from app.models.user import User
from app.services.events import broker

logger = logging.getLogger(__name__)


def create(
    db: Session,
    *,
    user_ids: list[int],
    type: str,
    title: str,
    body: str = "",
    link: str = "",
    dedup_key: str = "",
) -> int:
    """给指定用户创建系统通知；dedup_key 命中已存在记录时跳过（幂等）。

    返回实际创建的条数。创建后广播 notification.new（无内容，仅提醒刷新）。
    """
    user_ids = [uid for uid in dict.fromkeys(user_ids) if uid]
    if not user_ids or not title:
        return 0
    created = 0
    for uid in user_ids:
        if dedup_key:
            exists = (
                db.query(Notification.id)
                .filter(
                    Notification.user_id == uid,
                    Notification.type == type,
                    Notification.dedup_key == dedup_key,
                )
                .first()
            )
            if exists:
                continue
        db.add(
            Notification(
                user_id=uid,
                type=type[:32],
                title=title[:256],
                body=body or "",
                link=link or "",
                dedup_key=dedup_key[:160],
            )
        )
        created += 1
    if created:
        db.commit()
        try:
            # SSE 端点按 user_ids 精确投递（事件本身无内容，各端自行拉取未读，无泄露面）
            broker.publish({"type": "notification.new", "user_ids": user_ids})
        except Exception:
            logger.exception("通知 SSE 广播失败")
    return created


def admin_ids(db: Session) -> list[int]:
    return [
        uid
        for (uid,) in db.query(User.id)
        .filter(User.role == "admin", User.is_active.is_(True), User.is_deleted.is_(False))
        .all()
    ]


def notify_admins(db: Session, *, type: str, title: str, body: str = "", link: str = "", dedup_key: str = "") -> int:
    return create(db, user_ids=admin_ids(db), type=type, title=title, body=body, link=link, dedup_key=dedup_key)


def service_failed(db: Session, scope: str, error: str) -> int:
    """后台服务运行失败通知：按 天 + scope 去重，避免反复失败刷屏。"""
    from datetime import datetime, timezone

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return notify_admins(
        db,
        type="service_failed",
        title="后台服务运行失败",
        body=f"{scope} 运行失败：{error[:400]}",
        dedup_key=f"service:{scope}:{day}",
    )


def unread_count(db: Session, user_id: int) -> int:
    return (
        db.query(Notification.id)
        .filter(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
        )
        .count()
    )


def background_notify_admins(*, type: str, title: str, body: str = "", link: str = "", dedup_key: str = "") -> None:
    """线程/调度任务里的便捷入口：自建会话通知管理员，异常只记日志。"""
    try:
        db = SessionLocal()
        try:
            notify_admins(db, type=type, title=title, body=body, link=link, dedup_key=dedup_key)
        finally:
            db.close()
    except Exception:
        logger.exception("系统通知写入失败 type=%s", type)
