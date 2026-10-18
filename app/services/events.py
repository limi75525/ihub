"""进程内 SSE 事件总线。

ingest / 轮询在非事件循环线程中写库，publish 会把事件安全地投递回主循环。
"""

import asyncio
import json
import logging

logger = logging.getLogger(__name__)


class EventBroker:
    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue] = set()

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, event: dict) -> None:
        if self._loop is None or not self._subscribers:
            return
        payload = json.dumps(event, ensure_ascii=False, default=str)

        async def _put_all() -> None:
            for q in list(self._subscribers):
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(payload)

        try:
            asyncio.get_running_loop()
            self._loop.create_task(_put_all())
        except RuntimeError:
            try:
                asyncio.run_coroutine_threadsafe(_put_all(), self._loop)
            except RuntimeError:
                # 事件循环已关闭（uvicorn 收到 SIGTERM 后的关机阶段）：
                # 调度/ingest 线程的 publish 不可再投递，静默丢弃——
                # 若不捕获，create_message 已 commit 后抛 500，设备会无谓重试
                pass


broker = EventBroker()
