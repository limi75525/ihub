"""进程内 TTL 结果缓存（单 worker 前提；重启即失效）。

「重采样、轻变化」的值（上游曲库/影视库计数、容器计数）用短 TTL 防抖：
TTL 窗口内的重复请求直接复用上次结果，采样失败由调用方决定降级值（一律计 0）。
"""

import threading
import time


class TTLCache:
    def __init__(self, ttl: float) -> None:
        self._ttl = ttl
        self._data: dict[str, tuple[float, object]] = {}

    def get(self, key: str):
        """命中且未过期则返回值，否则 None。注意用 `is not None` 判断——
        缓存值本身可能是 0（空库计数），按真值判断会把命中当成未命中。"""
        hit = self._data.get(key)
        if hit and time.time() - hit[0] < self._ttl:
            return hit[1]
        return None

    def put(self, key: str, value) -> None:
        self._data[key] = (time.time(), value)

    def clear(self) -> None:
        self._data.clear()


class LockedTTLCache:
    """带锁的按 key 记时缓存（替代各模块手写的「dict+Lock+(time, value)」套件）。

    与 TTLCache 的差异：每 key 各自记录写入时间（长驻缓存按条目滚动过期，而非整表
    共用一个 TTL 起点）、所有操作持锁、支持按键谓词批量失效。TTL 传 None 表示
    条目不过期（仍可用 peek 拿原始时间戳自行判断）。

    读取分两档：
    - `get`：命中且未过期返回 (True, value)，否则 (False, None)，过期条目顺带剔除；
    - `peek`：返回原始条目 (at, value) 或 None——供「过期后仍要取旧值兜底」的
      调用方（如种子封面历史：拉新失败时回退上一份数据），由调用方自行比对 TTL。
    """

    def __init__(self, ttl: float | None = None) -> None:
        self._ttl = ttl
        self._lock = threading.Lock()
        self._data: dict = {}

    def get(self, key):
        """命中且未过期返回 (True, value)；未命中/已过期返回 (False, None)。
        注意 value 可能是合法的 0/空容器，必须用 ok 标志判断而非真值。"""
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                return False, None
            at, value = hit
            if self._ttl is not None and time.time() - at >= self._ttl:
                del self._data[key]
                return False, None
            return True, value

    def peek(self, key):
        """返回原始条目 (at, value)；无条目返回 None（已过期条目也照常返回）。"""
        with self._lock:
            hit = self._data.get(key)
            return None if hit is None else hit

    def put(self, key, value, *, at: float | None = None) -> None:
        """写入一条；at 可指定数据产生时间（对齐原手写缓存的写入语义）。"""
        with self._lock:
            self._data[key] = (time.time() if at is None else at, value)

    def invalidate(self, key) -> None:
        with self._lock:
            self._data.pop(key, None)

    def invalidate_where(self, predicate) -> int:
        """失效所有满足 predicate(key) 的条目，返回剔除数量（原「遍历匹配键前缀再 pop」模式）。"""
        with self._lock:
            stale = [k for k in self._data if predicate(k)]
            for k in stale:
                del self._data[k]
            return len(stale)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
