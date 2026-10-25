"""系统通知 API：顶栏铃铛的列表 / 未读数 / 已读标记。"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.notification import Notification
from app.models.user import User
from app.services.notify_service import unread_count

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _out(n: Notification) -> dict:
    return {
        "id": n.id,
        "type": n.type,
        "title": n.title,
        "body": n.body,
        "link": n.link or "",
        "created_at": n.created_at.isoformat() if n.created_at else "",
        "read": n.read_at is not None,
    }


@router.get("")
def list_notifications(
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(Notification.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "items": [_out(n) for n in rows],
        "unread": unread_count(db, user.id),
    }


@router.get("/unread")
def unread(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"count": unread_count(db, user.id)}


class ReadIn(BaseModel):
    ids: list[int] = []
    all: bool = False


@router.post("/read")
def mark_read(
    body: ReadIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.read_at.is_(None),
    )
    if body.all:
        rows = q.all()
    else:
        rows = q.filter(Notification.id.in_(body.ids)).all() if body.ids else []
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    for n in rows:
        n.read_at = now
    db.commit()
    return {"ok": True, "read": len(rows)}
