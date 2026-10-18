"""内存级限流（进程内存，重启即清零；多 worker 部署时各自独立计数）。

三种形态：

- `LockoutCounter`：失败计数 → 达阈值锁定一段时间（登录：用户名维度 5 次锁 15 分钟、
  IP 维度 15 分钟 20 次锁 15 分钟）；两维度的细节差异由构造参数显式保留。
- `WindowCounter`：窗口计数，成功失败都计（注册 30 次/10 分钟/IP；验证码 30 次/5 分钟/IP）。
- `SlidingWindowLimiter`：窗口内按调用次数限流，被拒的调用不计数也不续期
  （设备推送 30 次/分钟/IP）。

条目上限：这些键可被任意字符串/近乎无限的源地址填充，超出 MAX_ENTRIES 时先清过期条目，
仍超则驱逐最旧（限流精度短暂降级，可接受）——防内存被刷爆。
"""

import threading
import time

_MAX_FAILS = 5
_LOCK_SECONDS = 15 * 60

# 用户名计数窗口：窗口内失败累计，超过窗口未再失败即清零（避免半年前的一次失败参与锁定）
_USER_WINDOW = 15 * 60
# 内存表条目上限
_MAX_ENTRIES = 10000

_IP_WINDOW = 15 * 60
_IP_MAX_FAILS = 20

_lock = threading.Lock()


class LockoutCounter:
    """失败计数 → 达阈值锁定：state = [fail_count, locked_until, window_start]。"""

    def __init__(
        self,
        *,
        window: float,
        max_fails: int,
        lock_seconds: float,
        locked_message: str,
        reset_window_on_lock: bool = False,
        reset_expired_in_check: bool = False,
    ) -> None:
        self._window = window
        self._max_fails = max_fails
        self._lock_seconds = lock_seconds
        # 文案模板，{minutes} 为剩余锁定分钟数
        self._locked_message = locked_message
        self._reset_window_on_lock = reset_window_on_lock
        self._reset_expired_in_check = reset_expired_in_check
        self._state: dict[str, list[float]] = {}

    def _evict(self, now: float) -> None:
        """清理已解锁且窗口过期的条目（调用方须持锁）。"""
        for k in [k for k, v in self._state.items() if v[1] <= now and now - v[2] > self._window]:
            self._state.pop(k, None)
        if len(self._state) > _MAX_ENTRIES:
            for k, _v in sorted(self._state.items(), key=lambda kv: kv[1][2])[
                : len(self._state) - _MAX_ENTRIES
            ]:
                self._state.pop(k, None)

    def check(self, key: str) -> None:
        if not key:
            return
        now = time.time()
        with _lock:
            state = self._state.get(key)
            if state:
                _count, locked_until, window_start = state
                if locked_until > now:
                    remaining = int(locked_until - now)
                    raise PermissionError(self._locked_message.format(minutes=remaining // 60 + 1))
                if self._reset_expired_in_check and now - window_start > self._window:
                    self._state.pop(key, None)
            self._evict(now)

    def record_failure(self, key: str) -> None:
        if not key:
            return
        now = time.time()
        with _lock:
            state = self._state.get(key)
            if state is None or now - state[2] > self._window:
                self._state[key] = [1, 0.0, now]
            else:
                state[0] += 1
                if state[0] >= self._max_fails:
                    state[1] = now + self._lock_seconds
                    if self._reset_window_on_lock:
                        state[0] = 0
                        state[2] = now
            self._evict(now)

    def clear(self, key: str) -> None:
        if not key:
            return
        with _lock:
            self._state.pop(key, None)


class WindowCounter:
    """窗口计数限流（成功失败都计）：check 与 record 分离，调用方先 check 再在成功后 record。"""

    def __init__(self, *, window: float, max_count: int, message: str) -> None:
        self._window = window
        self._max = max_count
        self._message = message  # 文案模板，{minutes} 为窗口剩余分钟数
        self._state: dict[str, list[float]] = {}  # key -> [count, window_start]

    def _evict(self, now: float) -> None:
        """清理过期窗口条目；仍超限时按窗口起点驱逐最旧（大量伪造源 IP 时防内存膨胀）。"""
        if len(self._state) <= _MAX_ENTRIES:
            return
        for k in [k for k, v in self._state.items() if now - v[1] > self._window]:
            self._state.pop(k, None)
        if len(self._state) > _MAX_ENTRIES:
            for k, _v in sorted(self._state.items(), key=lambda kv: kv[1][1])[
                : len(self._state) - _MAX_ENTRIES
            ]:
                self._state.pop(k, None)

    def check(self, key: str) -> None:
        if not key:
            return
        now = time.time()
        with _lock:
            state = self._state.get(key)
            if state:
                count, window_start = state
                if now - window_start > self._window:
                    self._state.pop(key, None)
                elif count >= self._max:
                    remaining = int(self._window - (now - window_start))
                    raise PermissionError(self._message.format(minutes=remaining // 60 + 1))
            self._evict(now)

    def record(self, key: str = "") -> None:
        if not key:
            return
        now = time.time()
        with _lock:
            state = self._state.get(key)
            if state is None or now - state[1] > self._window:
                self._state[key] = [1, now]
            else:
                state[0] += 1
            self._evict(now)


class SlidingWindowLimiter:
    """窗口内按调用次数限流：达上限即拒绝；被拒的调用不计数、不续期窗口。"""

    def __init__(self, *, window: float, max_hits: int, message: str) -> None:
        self._window = window
        self._max = max_hits
        self._message = message
        self._hits: dict[str, list[float]] = {}

    def _evict(self, now: float) -> None:
        """超限时先清过期条目，仍超则整表重置（精度短暂降级，防无限源地址灌内存）。"""
        if len(self._hits) <= _MAX_ENTRIES:
            return
        for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= self._window]:
            self._hits.pop(k, None)
        if len(self._hits) > _MAX_ENTRIES:
            self._hits.clear()

    def hit(self, key: str) -> None:
        """记一次调用；窗口内已达上限则抛 PermissionError。"""
        if not key:
            return
        now = time.time()
        with _lock:
            self._evict(now)
            hits = [t for t in self._hits.get(key, []) if now - t < self._window]
            if len(hits) >= self._max:
                raise PermissionError(self._message)
            hits.append(now)
            self._hits[key] = hits


# ---- 登录失败：用户名维度（reset_window_on_lock：锁定后窗口起点重置）
# + IP 维度（reset_expired_in_check：check 时顺手清窗口过期条目） ----
_USER_FAILS = LockoutCounter(
    window=_USER_WINDOW,
    max_fails=_MAX_FAILS,
    lock_seconds=_LOCK_SECONDS,
    locked_message="尝试次数过多，请 {minutes} 分钟后重试",
    reset_window_on_lock=True,
)
_IP_FAILS = LockoutCounter(
    window=_IP_WINDOW,
    max_fails=_IP_MAX_FAILS,
    lock_seconds=_LOCK_SECONDS,
    locked_message="该网络尝试次数过多，请 {minutes} 分钟后重试",
    reset_expired_in_check=True,
)


def check_login_allowed(username: str) -> None:
    _USER_FAILS.check(username)


def check_ip_allowed(ip: str) -> None:
    """IP 维度限流：窗口内失败过多则整 IP 拒绝登录（换用户名也无法绕过）。"""
    _IP_FAILS.check(ip)


def record_login_failure(username: str, ip: str = "") -> None:
    _USER_FAILS.record_failure(username)
    if ip:
        _IP_FAILS.record_failure(ip)


def record_login_success(username: str, ip: str = "") -> None:
    _USER_FAILS.clear(username)
    if ip:
        _IP_FAILS.clear(ip)


# ---- 注册限流：/auth/register 未认证且要跑 bcrypt（约 100ms CPU/次），无限流可被刷 CPU/灌账号 ----
# 成功与失败都计数（换用户名绕不过）；30 次/10 分钟/IP 对正常自部署绰绰有余，
# 同时给安全探针/冒烟测试（同 IP 连续注册多账号）留出余量。
_REG = WindowCounter(
    window=10 * 60,
    max_count=30,
    message="注册过于频繁，请 {minutes} 分钟后再试",
)


def check_register_allowed(ip: str) -> None:
    _REG.check(ip)


def record_register(ip: str = "") -> None:
    _REG.record(ip)


# ---- 验证码签发限流：/auth/captcha 未认证且要跑 PIL 渲染（CPU），且签发槽位
# _MAX_STORED=200 有限——不限流可高频刷签发把他人「展示中待提交」的验证码挤出存储 ----
_CAPTCHA = WindowCounter(
    window=5 * 60,
    max_count=30,
    message="验证码获取过于频繁，请 {minutes} 分钟后再试",
)


def check_captcha_allowed(ip: str) -> None:
    _CAPTCHA.check(ip)


def record_captcha(ip: str = "") -> None:
    _CAPTCHA.record(ip)


# ---- 设备推送限流：/ingest/* 未认证入口，防在线枚举 8 位设备码 ----
INGEST_LIMITER = SlidingWindowLimiter(
    window=60.0,
    max_hits=30,
    message="请求过于频繁，请稍后再试",
)
