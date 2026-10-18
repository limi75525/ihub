"""SSE 实时事件流。前端可用 fetch 流式读取（带 Authorization 头）或 EventSource?token=。"""

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.core.deps import get_current_user
from app.db.session import SessionLocal
from app.models.user import User
from app.services.events import broker

router = APIRouter(tags=["sse"])


def _sse_user(request: Request) -> User:
    """SSE 鉴权专用：用短会话校验完立即关闭。

    FastAPI 的 yield 依赖（get_db）在流式响应结束后才关闭会话——每个 SSE 连接
    会占住一个连接池连接直到断开，第 16 个并发连接起全站 DB 请求排队 30s 超时。
    这里鉴权后马上归还连接，流式阶段只用已加载的 user.id / user.role。
    """
    db = SessionLocal()
    try:
        return get_current_user(request, db=db)
    finally:
        db.close()


@router.get("/events")
async def events(
    request: Request,
    user: User = Depends(_sse_user),
):
    queue = broker.subscribe()

    async def gen():
        try:
            yield "event: connected\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                # 只投递当前用户的事件
                try:
                    evt = json.loads(payload)
                except ValueError:
                    continue
                # 严格按用户隔离：缺失 user_id 的事件一律不投递，避免未来新事件
                # 漏带 user_id 时把内容广播给所有连接（跨用户泄露）
                if evt.get("audience") == "admins":
                    # 全局事件（如容器监控事件）不带 user_id，只投递给管理员
                    if user.role != "admin":
                        continue
                elif evt.get("user_id") != user.id:
                    continue
                yield f"data: {payload}\n\n"
        finally:
            broker.unsubscribe(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
