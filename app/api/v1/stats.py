"""仪表盘统计。时区用 settings.TIMEZONE 计算"今日"。"""

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.timeutil import as_utc
from app.core.ttlcache import TTLCache
from app.db.session import get_db
from app.models.message import Message
from app.models.source import Source
from app.models.user import User

router = APIRouter(prefix="/stats", tags=["stats"])

logger = logging.getLogger(__name__)

_tz_cache: tuple[str, ZoneInfo] | None = None

# 总览用户卡「容器」计数缓存（list_containers 每次采样较重，30s 够用）
_DOCKER_COUNT_CACHE = TTLCache(30.0)


def _tz() -> ZoneInfo:
    """TIMEZONE 环境变量配置非法时回退 UTC（否则仪表盘每个请求都 500）。"""
    global _tz_cache
    if _tz_cache and _tz_cache[0] == settings.TIMEZONE:
        return _tz_cache[1]
    try:
        tz = ZoneInfo(settings.TIMEZONE)
    except Exception:
        logger.warning("非法时区配置 %r，统计回退 UTC", settings.TIMEZONE)
        tz = timezone.utc
    _tz_cache = (settings.TIMEZONE, tz)
    return tz


@router.get("")
def dashboard(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    tz = _tz()
    now_local = datetime.now(tz)
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    base = db.query(Message).filter(Message.user_id == user.id, Message.is_deleted.is_(False))

    total = base.with_entities(func.count(Message.id)).scalar() or 0
    unread = base.filter(Message.is_read.is_(False)).with_entities(func.count(Message.id)).scalar() or 0
    today = base.filter(Message.received_at >= today_start).with_entities(func.count(Message.id)).scalar() or 0

    # 渠道分布
    by_channel = dict(
        db.query(Message.channel, func.count(Message.id))
        .filter(Message.user_id == user.id, Message.is_deleted.is_(False))
        .group_by(Message.channel)
        .all()
    )

    # 近 7 天趋势（按天 + 渠道）：SQL 按本地日界（8 个 UTC 边界）分桶，
    # 只回「天数×渠道数」行，不再把一周的全部消息拉进 Python 聚合。
    # CASE 取首个为真的分支 → 条件必须从最新一天往旧排；越界的（早于一周/未来时间）落 ELSE 丢弃。
    day_keys = [(now_local - timedelta(days=6 - i)).date().isoformat() for i in range(7)]
    bounds = [
        (now_local - timedelta(days=6 - i))
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(timezone.utc)
        for i in range(8)
    ]
    bucket = case(*[(Message.received_at >= bounds[i], i) for i in range(6, -1, -1)], else_=-1).label("day_idx")
    trend_rows = (
        db.query(bucket, Message.channel, func.count(Message.id))
        .filter(
            Message.user_id == user.id,
            Message.received_at >= bounds[0],
            Message.received_at < bounds[7],
            Message.is_deleted.is_(False),
        )
        .group_by(bucket, Message.channel)
        .all()
    )
    days: dict[str, dict[str, int]] = {d: {"sms": 0, "email": 0, "api": 0} for d in day_keys}
    for idx, channel, n in trend_rows:
        if 0 <= idx < 7 and channel in days[day_keys[idx]]:
            days[day_keys[idx]][channel] += n

    # 来源统计
    sources = db.query(Source).filter(Source.user_id == user.id, Source.is_deleted.is_(False)).all()
    offline_minutes = settings.DEVICE_OFFLINE_MINUTES
    now_utc = datetime.now(timezone.utc)
    online = 0
    for s in sources:
        if s.type == "email":
            online += bool(s.is_active and s.last_poll_at)
        else:
            ref = as_utc(s.last_seen_at)
            if ref and (now_utc - ref).total_seconds() < offline_minutes * 60:
                online += 1

    # 左侧「消息未读」卡片数据源：仅未读、按时间倒序取最近 20 条（卡片固定显示约 10 行，超出滚动）
    latest = (
        base.filter(Message.is_read.is_(False))
        .order_by(Message.received_at.desc())
        .limit(20)
        .with_entities(Message)
        .all()
    )
    names = {s.id: s.name for s in sources}
    from app.api.v1.messages import _avatar_logo, _logo_rules, _match_logo

    # 头像库为企业分组双表模型：_logo_rules 返回 (规则列表, 分组映射)
    logo_rules, logo_groups = _logo_rules(db, user.id)

    return {
        "total": total,
        "unread": unread,
        "today": today,
        "by_channel": by_channel,
        "trend": [
            {"date": d, **days[d]} for d in sorted(days)
        ],
        "sources_total": len(sources),
        "sources_online": online,
        "unread_by_channel": {
            c: n
            for c, n in db.query(Message.channel, func.count(Message.id))
            .filter(Message.user_id == user.id, Message.is_read.is_(False), Message.is_deleted.is_(False))
            .group_by(Message.channel)
            .all()
        },
        "latest": [
            {
                "id": m.id,
                "channel": m.channel,
                "source_id": m.source_id,
                "source_name": names.get(m.source_id, ""),
                "sender": m.sender,
                "title": m.title,
                "content_text": (m.content_text or "")[:120],
                "is_read": m.is_read,
                # 来信方头像：只认头像库（LOGO 规则）匹配结果；未命中由前端回退平台 logo。
                # 接入服务的 logo 只在「接入服务」卡片展示，不能当作来信方头像
                "avatar": _avatar_logo(_match_logo(logo_rules, logo_groups, m), logo_groups),
                "received_at": as_utc(m.received_at).isoformat(),
            }
            for m in latest
        ],
        # 总览用户卡 8 项统计（两行：消息/影视/音乐/书籍 + 服务/容器/文件/导航）
        "hub": _hub_counts(user, db, sources, total),
    }


def _hub_counts(user: User, db: Session, sources: list[Source], total: int) -> dict:
    """总览 8 项聚合；上游/容器计数失败一律计 0，绝不拖垮 /stats。"""
    from app.api.v1.docker import monitor_enabled
    from app.api.v1.music import library_song_count
    from app.api.v1.video import library_video_count
    from app.models.book import Book
    from app.models.nav_link import NavLink
    from app.models.transfer_item import TransferItem
    from app.services import docker_service

    books_n = db.query(Book.id).filter(Book.user_id == user.id, Book.is_deleted.is_(False)).count()
    files_n = db.query(TransferItem.id).filter(TransferItem.user_id == user.id).count()
    navs_n = db.query(NavLink.id).filter(NavLink.user_id == user.id).count()

    containers_n = 0
    if user.role == "admin" and monitor_enabled(db):
        cached = _DOCKER_COUNT_CACHE.get("containers")
        if cached is not None:
            containers_n = cached
        else:
            try:
                # count_containers 只拉 /containers/json（毫秒级）；
                # 不能用 list_containers：逐容器采样 CPU/内存会把仪表盘拖到秒级
                containers_n = docker_service.count_containers()
                _DOCKER_COUNT_CACHE.put("containers", containers_n)
            except Exception:
                containers_n = 0

    return {
        "messages": total,
        "video": library_video_count(db),
        "music": library_song_count(db),
        "books": books_n,
        "services": len(sources),
        "containers": containers_n,
        "files": files_n,
        "navs": navs_n,
    }
