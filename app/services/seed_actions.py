"""PT 资源操作的临时上下文。

MoviePilot 返回的搜索上下文包含站点 Cookie、User-Agent 与下载直链，
这些字段只允许留在服务端。对前端下发不透明的 op_id，执行下载/订阅时
再按登录用户取回原始上下文，避免 passkey 出现在浏览器或日志里。
"""
from __future__ import annotations

import secrets
import threading
import time
from typing import Any

# 搜索结果只在短时间内可操作，过期后让前端重新搜索。
_TTL_SECONDS = 30 * 60
_MAX_ENTRIES = 2000
_STORE: dict[str, tuple[int, float, dict[str, Any]]] = {}
_LOCK = threading.Lock()


def _prune_locked(now: float) -> None:
    expired = [token for token, (_, expires, _) in _STORE.items() if expires <= now]
    for token in expired:
        _STORE.pop(token, None)
    while len(_STORE) >= _MAX_ENTRIES:
        # dict 保持插入顺序，超限时淘汰最早写入的上下文。
        _STORE.pop(next(iter(_STORE)))


def stash(user_id: int, context: dict[str, Any]) -> str:
    """保存原始 MP 上下文，返回不透明引用。"""
    token = secrets.token_urlsafe(24)
    now = time.time()
    with _LOCK:
        _prune_locked(now)
        _STORE[token] = (int(user_id), now + _TTL_SECONDS, context)
    return token


def get(user_id: int, token: str) -> dict[str, Any] | None:
    """取回当前用户自己的上下文；过期、不存在或越权都返回 None。"""
    now = time.time()
    with _LOCK:
        entry = _STORE.get(token)
        if not entry:
            return None
        owner, expires, context = entry
        if expires <= now:
            _STORE.pop(token, None)
            return None
        if owner != int(user_id):
            return None
        return context


def discard(token: str) -> None:
    with _LOCK:
        _STORE.pop(token, None)


def cache_size() -> int:
    with _LOCK:
        return len(_STORE)
