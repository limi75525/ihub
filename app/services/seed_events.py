"""种子事件线程：下载完成 / 订阅完成 / 站点签到失败 → 消息中心。

- QB 没有推送能力，后台轮询 completed 列表，按 completion_on 水位检测新完成；
- MP 有通知中心（插件也会往这里写），轮询 /api/v1/message/notification，
  按通知 id 水位检测订阅完成与站点签到失败；
- 事件写入系统通知（notifications 表），顶栏铃铛展示；不再进消息中心、不再生成「种子」系统来源。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.seed_connection import SeedConnection
from app.models.user import User
from app.services import notify_service
from app.services.seed_service import (
    mp_client,
    qb_client,
)

logger = logging.getLogger(__name__)

_STOP = threading.Event()
_THREAD: threading.Thread | None = None
_LOCK = threading.Lock()
_LAST_QB: dict[int, float] = {}
_LAST_MP: dict[int, float] = {}

# 测试/联调可缩短间隔；生产默认 QB 15s / MP 300s。
# MP 轮询是常驻后台线程（页面不开也在跑），间隔放宽到 5 分钟，避免持续给
# 本来就吃力的 MP 增加请求；订阅/签到通知晚几分钟到达是可接受的代价。
QB_INTERVAL = max(2, int(os.getenv("IHUB_SEED_QB_INTERVAL", "15")))
MP_INTERVAL = max(2, int(os.getenv("IHUB_SEED_MP_INTERVAL", "300")))
LOOP_SECONDS = max(1, int(os.getenv("IHUB_SEED_LOOP_SECONDS", "5")))

_QB_BAD_STATES = {
    "allocating", "checkingdl", "checkingup", "downloading", "error",
    "forceddl", "missingfiles", "metadl", "moving", "queueddl",
    "stalleddl", "unknown",
}

_FAIL_RE = re.compile(r"登录或访问失败\s*[:：]\s*(\d+)")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _human_size(value: int) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{int(value)} B"


def _recipients(db: Session, event_kind: str) -> list[User]:
    """固定通知矩阵（2026-10-25 用户拍板，设置项已移除）：
    download_complete → 全体用户（普通用户只收种子下载成功）；
    download_failed / subscribe_complete / signin_failed → 仅管理员。
    刷流种子的完成与失败在轮询处已跳过，不会进通知。"""
    users = (
        db.query(User)
        .filter(User.is_active.is_(True), User.is_deleted.is_(False))
        .order_by(User.id.asc())
        .all()
    )
    if event_kind == "download_complete":
        return users
    return [u for u in users if u.role == "admin"]


def _notify(
    db: Session,
    *,
    event_kind: str,
    event_key: str,
    title: str,
    text: str,
    extra: dict,
) -> int:
    users = _recipients(db, event_kind)
    if not users:
        return 0
    link = str(extra.get("link") or "") if isinstance(extra, dict) else ""
    return notify_service.create(
        db,
        user_ids=[u.id for u in users],
        type=event_kind,
        title=title,
        body=text,
        link=link,
        dedup_key=f"seed:{event_kind}:{event_key}"[:160],
    )


def _is_brush_torrent(row: dict) -> bool:
    """刷流任务的种量太大且无人关注，完成时不进消息中心。"""
    text = f"{row.get('category') or ''} {row.get('tags') or ''}".lower()
    return "刷流" in text or "brush" in text


def _poll_qb(db: Session, conn: SeedConnection) -> None:
    client = qb_client(conn)
    if client.cooldown_remaining() > 0:
        # 登录冷却/封禁期间不再请求，也不覆盖 last_error（保留第一次的真实原因）
        return
    rows = client.torrents(filter="completed")
    completed = []
    max_completion = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            progress = float(row.get("progress") or 0)
            amount_left = int(row.get("amount_left") or 0)
        except (TypeError, ValueError):
            continue
        state = str(row.get("state") or "").strip().lower()
        completion = int(row.get("completion_on") or 0)
        max_completion = max(max_completion, completion)
        if (
            progress >= 1
            and amount_left <= 0
            and state not in _QB_BAD_STATES
            and not _is_brush_torrent(row)
        ):
            completed.append((completion, row))

    # 首次连接只建立水位，不补发历史完成事件；没有已完成种子时用当前时间，
    # 避免水位一直是 0、把之后第一颗完成的种子也当成历史吞掉。
    if not conn.last_completed_at:
        conn.last_completed_at = max_completion or int(time.time())
        conn.last_ok_at = _now()
        conn.last_error = ""
        db.commit()
        return

    new_rows = sorted(
        [(c, r) for c, r in completed if c > conn.last_completed_at],
        key=lambda x: x[0],
    )
    for completion, row in new_rows:
        name = str(row.get("name") or "未知种子")
        size = int(row.get("total_size") or row.get("size") or 0)
        ratio = float(row.get("ratio") or 0)
        text = f"《{name}》已下载完成\n大小：{_human_size(size)}\n分享率：{ratio:.2f}"
        _notify(
            db,
            event_kind="download_complete",
            event_key=f"qb:{conn.id}:{row.get('hash')}:{completion}",
            title="种子下载完成",
            text=text,
            extra={
                "kind": "download_complete",
                "hash": str(row.get("hash") or ""),
                "name": name,
                "link": f"#/seeds?tab=download&hash={row.get('hash') or ''}",
            },
        )
    conn.last_completed_at = max(conn.last_completed_at, max_completion)
    conn.last_ok_at = _now()
    conn.last_error = ""
    db.commit()

    # 下载失败/异常：errored 状态的种子（刷流种子失败也要报）
    try:
        errored_rows = client.torrents(filter="errored")
    except Exception:
        errored_rows = []
    for row in errored_rows:
        if not isinstance(row, dict):
            continue
        if _is_brush_torrent(row):
            continue
        state = str(row.get("state") or "").strip().lower()
        name = str(row.get("name") or "未知种子")
        _notify(
            db,
            event_kind="download_failed",
            event_key=f"qb:{conn.id}:{row.get('hash')}:{state}",
            title="种子下载异常",
            text=f"《{name}》下载异常（状态：{_QB_STATE_LABELS.get(state, state)}），请到下载页查看。",
            extra={
                "kind": "download_failed",
                "hash": str(row.get("hash") or ""),
                "name": name,
                "link": f"#/seeds?tab=download&hash={row.get('hash') or ''}",
            },
        )


def _signin_failure_count(text: str) -> int:
    match = _FAIL_RE.search(text or "")
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return 0
    # 兼容插件旧文案：只出现「失败」且没有明确的 0
    if "失败" in (text or "") and "失败: 0" not in (text or "") and "失败：0" not in (text or ""):
        return 1
    return 0


def _poll_mp(db: Session, conn: SeedConnection) -> None:
    client = mp_client(conn)
    notifications = []
    for page in (1, 2):
        batch = client.notifications(page=page, count=50)
        if not batch:
            break
        notifications.extend(batch)
        ids = [int(n.get("id") or 0) for n in batch if isinstance(n, dict)]
        if not ids or min(ids) <= conn.last_notification_id:
            break

    rows = []
    max_id = conn.last_notification_id
    for item in notifications:
        if not isinstance(item, dict):
            continue
        try:
            nid = int(item.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if nid <= 0:
            continue
        max_id = max(max_id, nid)
        rows.append((nid, item))

    if conn.last_notification_id == 0:
        # 没有历史通知时置 1（MP 通知 id 从 1 起），避免之后第一条通知被当历史吞掉
        conn.last_notification_id = max_id or 1
        conn.last_ok_at = _now()
        conn.last_error = ""
        db.commit()
        return

    for nid, item in sorted(rows, key=lambda x: x[0]):
        if nid <= conn.last_notification_id:
            continue
        mtype = str(item.get("mtype") or "")
        ctype = str(item.get("ctype") or item.get("content_type") or "")
        title = str(item.get("title") or "")
        text = str(item.get("text") or "")
        kind = ""
        extra: dict = {"kind": "", "mp_notification_id": nid}
        if ctype == "subscribeComplete" or (mtype == "订阅" and "完成" in title):
            kind = "subscribe_complete"
            extra.update({"kind": kind, "title": title, "link": "#/seeds?tab=subscription"})
        elif mtype == "站点" and ("签到" in title or "登录" in title):
            failures = _signin_failure_count(text)
            if failures > 0:
                kind = "signin_failed"
                extra.update({"kind": kind, "failures": failures, "link": "#/seeds?tab=sites"})
        if not kind:
            continue
        msg_title = "订阅完成" if kind == "subscribe_complete" else "站点签到失败"
        msg_text = (text or msg_title).strip()
        if len(msg_text) > 4000:
            msg_text = msg_text[:4000] + "…"
        _notify(
            db,
            event_kind=kind,
            event_key=f"mp:{conn.id}:{nid}",
            title=msg_title,
            text=msg_text,
            extra=extra,
        )
    conn.last_notification_id = max_id
    conn.last_ok_at = _now()
    conn.last_error = ""
    db.commit()


def _loop() -> None:
    while not _STOP.is_set():
        db = SessionLocal()
        try:
            conns = (
                db.query(SeedConnection)
                .filter(SeedConnection.enabled.is_(True))
                .order_by(SeedConnection.id.asc())
                .all()
            )
            now = time.monotonic()
            for conn in conns:
                try:
                    if conn.kind == "qbittorrent":
                        if now - _LAST_QB.get(conn.id, 0) < QB_INTERVAL:
                            continue
                        _LAST_QB[conn.id] = now
                        _poll_qb(db, conn)
                    elif conn.kind == "moviepilot":
                        if now - _LAST_MP.get(conn.id, 0) < MP_INTERVAL:
                            continue
                        _LAST_MP[conn.id] = now
                        _poll_mp(db, conn)
                except Exception as e:
                    db.rollback()
                    try:
                        conn.last_error = str(e)[:500]
                        db.commit()
                    except Exception:
                        db.rollback()
                    logger.warning("种子事件轮询失败 conn=%s kind=%s: %s", conn.id, conn.kind, e)
        except Exception:
            logger.exception("种子事件线程本轮异常")
        finally:
            db.close()
        _STOP.wait(LOOP_SECONDS)


def start_worker() -> None:
    global _THREAD
    with _LOCK:
        if _THREAD and _THREAD.is_alive():
            return
        # 首次启动不要在页面首载的同一波里再打 MP 通知接口：
        # 先把已启用的 MP 连接记为「刚轮询过」，第一次通知轮询推迟到 MP_INTERVAL（默认 5 分钟）。
        db = SessionLocal()
        try:
            now = time.monotonic()
            for (conn_id,) in (
                db.query(SeedConnection.id)
                .filter(
                    SeedConnection.kind == "moviepilot",
                    SeedConnection.enabled.is_(True),
                )
                .all()
            ):
                _LAST_MP.setdefault(conn_id, now)
        finally:
            db.close()
        _STOP.clear()
        _THREAD = threading.Thread(target=_loop, name="ihub-seed-events", daemon=True)
        _THREAD.start()
        logger.info("种子事件线程已启动")


def stop_worker() -> None:
    _STOP.set()
    with _LOCK:
        thread = _THREAD
    if thread and thread.is_alive():
        thread.join(timeout=3)


def sync_worker() -> None:
    """连接/设置变化后调用：没有启用的连接就停止。

    有连接时也不在这里启动——启动/保存连接时 qB 可能还没有建立会话，
    事件线程先登录会与页面请求抢会话（qB 新登录轮换 SID，旧客户端随后 403）。
    由 test_connection 成功或 seed_overview 成功后再显式 start_worker()。
    """
    db = SessionLocal()
    try:
        has_enabled = (
            db.query(SeedConnection.id)
            .filter(SeedConnection.enabled.is_(True))
            .first()
            is not None
        )
    finally:
        db.close()
    if not has_enabled:
        stop_worker()
