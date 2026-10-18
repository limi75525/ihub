"""进程内 TTL 结果缓存（单 worker 前提；重启即失效）。

「重采样、轻变化」的值（上游曲库/影视库计数、容器计数）用短 TTL 防抖：
TTL 窗口内的重复请求直接复用上次结果，采样失败由调用方决定降级值（一律计 0）。
"""

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
