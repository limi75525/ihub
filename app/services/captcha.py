"""图形验证码：内存存储、一次性消费、5 分钟过期。

实现刻意保持轻量：字符集去掉易混淆字形，干扰线/噪点由 PIL 直接绘制。
登录/注册限流仍然生效，验证码仅作为额外的图形校验层。
"""
import base64
import hmac
import io
import random
import secrets
import threading
import time

from PIL import Image, ImageDraw, ImageFont

# 去掉易混淆的 0/O、1/l/I 等
_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_WIDTH, _HEIGHT = 132, 46
_CODE_LEN = 4
_TTL_SECONDS = 5 * 60
_MAX_STORED = 200

_store: dict[str, tuple[str, float]] = {}  # id -> (code, expire_ts)
_lock = threading.Lock()


def _load_font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # 旧版 Pillow 不支持 size 参数
        return ImageFont.load_default()


def issue() -> tuple[str, str]:
    """签发一个验证码，返回 (id, code)。"""
    code = "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LEN))  # 验证码用加密随机；噪点用 random 即可
    cid = secrets.token_hex(12)
    now = time.time()
    with _lock:
        # 顺带清理过期项
        expired = [k for k, (_, ts) in _store.items() if ts < now]
        for k in expired:
            _store.pop(k, None)
        _store[cid] = (code, now + _TTL_SECONDS)
        # 兜底：超出上限时淘汰最旧的一批
        if len(_store) > _MAX_STORED:
            for k in list(_store)[: len(_store) - _MAX_STORED]:
                _store.pop(k, None)
    return cid, code


def render(code: str) -> bytes:
    """绘制验证码 PNG，返回字节流（RGB，浅底深字 + 干扰线/噪点）。"""
    img = Image.new("RGB", (_WIDTH, _HEIGHT), (247, 248, 251))
    draw = ImageDraw.Draw(img)

    # 干扰线（低饱和灰）
    for _ in range(5):
        g = random.randint(140, 205)
        x0, y0 = random.randint(0, _WIDTH // 2), random.randint(0, _HEIGHT)
        draw.line(
            (x0, y0, random.randint(_WIDTH // 2, _WIDTH), random.randint(0, _HEIGHT)),
            fill=(g, g, g),
            width=1,
        )
    # 噪点
    for _ in range(140):
        g = random.randint(120, 220)
        x, y = random.randint(0, _WIDTH - 1), random.randint(0, _HEIGHT - 1)
        draw.point((x, y), fill=(g, g, g))

    # 逐字绘制：随机灰阶与纵向偏移
    font = _load_font(30)
    step = _WIDTH / (_CODE_LEN + 1)
    for i, ch in enumerate(code):
        v = random.randint(45, 110)
        x = int(step * (i + 0.5))
        y = random.randint(4, 12)
        draw.text((x, y), ch, font=font, fill=(v, v, v), anchor="ma")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def data_url(code: str) -> str:
    return "data:image/png;base64," + base64.b64encode(render(code)).decode()


def verify(cid: str | None, code: str | None) -> bool:
    """校验并消费（一次性）；无论成败都移除该 id。"""
    if not cid or not code:
        return False
    with _lock:
        item = _store.pop(cid, None)
    if not item:
        return False
    expect, expire_ts = item
    if time.time() > expire_ts:
        return False
    # 常数时间比较（验证码 4 位短码，== 的时序差异实际不可利用，但消除疑点成本为零）
    return hmac.compare_digest(code.strip().upper(), expect)
