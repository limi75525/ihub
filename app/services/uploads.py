"""上传文件的读取 / 落盘辅助。

图片类上传入口（用户头像、头像库 Logo、接入服务 Logo、导航 Logo、站点品牌、登录背景）
共用「按上限读取 + mkdir + 随机文件名写盘」；
后缀白名单、大小上限与错误文案属于各入口的业务差异，保留在调用方。
"""

import re
import secrets
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings
from app.core.errors import UpstreamError


async def read_limited(file: UploadFile, limit: int, size_error: str) -> bytes:
    """按上限读取（多读 1 字节探测超限）：避免先整段读进内存再判断大小。

    空文件统一报「文件为空」；调用方若还要做 SVG 清洗，清洗后需自行再判一次空。
    """
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise UpstreamError(size_error, 400)
    if not data:
        raise UpstreamError("文件为空", 400)
    return data


def random_name(prefix: str, ext: str) -> str:
    """随机后缀文件名：<prefix>_<8位hex><ext>（防覆盖；不含用户可控内容）。"""
    return f"{prefix}_{secrets.token_hex(4)}{ext}"


def save_bytes(rel_dir: str, filename: str, data: bytes) -> str:
    """写入 DATA_DIR/<rel_dir>/<filename>，返回入库用的相对路径。"""
    d = Path(settings.DATA_DIR) / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_bytes(data)
    return f"{rel_dir}/{filename}"


def save_unique(rel_dir: str, prefix: str, ext: str, data: bytes) -> str:
    """按随机文件名落盘，返回入库用的相对路径。"""
    return save_bytes(rel_dir, random_name(prefix, ext), data)


# ---------------- 跨入口共用的图片上传 / SVG 清洗 / 头像落盘 ----------------
# 从 api/v1/auth.py 下沉：users/logos/navlinks/recycle 等路由都要用，
# 路由层互相 import 私有函数违反依赖方向。

import html as html_mod

ALLOWED_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
}

MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 兜底默认 2MB；实际以 设置 → 系统 的 avatar_max_mb 为准（1-20MB）


def avatar_upload_max_size() -> int:
    """个人头像上限与头像库同源（avatar_max_mb 设置），避免前端放行、后端拒绝的错位。"""
    from app.db.settings_repo import get_int_setting

    return get_int_setting("avatar_max_mb", MAX_AVATAR_SIZE // (1024 * 1024), 1, 20) * 1024 * 1024


def _deep_decode(value: str) -> str:
    """反复实体解码直到稳定（至多 5 轮），并去掉浏览器会忽略的空白控制符。

    浏览器解析 URL 属性时会剥掉 tab/换行，因此 `jav\\tascript:` 与实体编码
    `&#106;avascript:` 实际等价——必须在解码+归一化之后做判断才可靠。
    """
    text = value
    for _ in range(5):
        decoded = html_mod.unescape(text)
        if decoded == text:
            break
        text = decoded
    return re.sub(r"[\t\r\n\f\x00\s]", "", text)


_DANGEROUS_SCHEME = ("javascript:", "vbscript:", "data:text/html", "data:image/svg+xml")
# href/src 允许的 scheme 白名单（deep_decode 已去掉空白，统一小写判断）
_SAFE_ATTR_SCHEME = ("#", "/", "http:", "https:", "mailto:", "data:image/png", "data:image/jpeg",
                     "data:image/gif", "data:image/webp")
# 连同内容整体移除的危险元素（SMIL 动画可通过 attributeName=href 注入 javascript: 目标）
_SVG_DROP_TAGS = ("script", "animate", "set", "handler", "foreignobject", "iframe", "embed", "object")
_SCRIPT_ELEMENT_RE = re.compile(
    r"<\s*(?:" + "|".join(_SVG_DROP_TAGS) + r")\b[^>]*>.*?<\s*/\s*(?:" + "|".join(_SVG_DROP_TAGS) + r")\s*>|"
    r"<\s*(?:" + "|".join(_SVG_DROP_TAGS) + r")\b[^>]*/?>",
    re.IGNORECASE | re.DOTALL,
)
_ATTR_RE = re.compile(
    r"\s([a-zA-Z_:][-\w:.]*)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)"
)


def _svg_attr_name(name: str) -> str:
    return _deep_decode(name).lower()


def sanitize_svg(data: bytes) -> bytes:
    """SVG 是 XML 文档，可携带脚本与事件属性，同源直接访问会造成存储型 XSS。

    清洗策略（正则不可信时宁可整份拒绝）：
    1. 移除 script / SMIL 动画（animate/set/handler）/ foreignObject / 嵌入对象元素；
    2. 剥除 on* 事件属性；
    3. href/xlink:href/src 白名单放行（http/https/mailto/#/相对路径/data:image），
       其余一律移除——实体编码与 tab 混入的 javascript: 已在解码归一化后识别；
    4. 终检：对整份文档深度解码后仍出现 javascript:/vbscript: 目标 → 返回空字节
       （调用方按「文件为空」拒绝上传）。
    """
    text = data.decode("utf-8", "replace")
    text = _SCRIPT_ELEMENT_RE.sub("", text)

    def _clean_attrs(match: re.Match) -> str:
        name, raw_value = match.group(1), match.group(2)
        value = raw_value[1:-1] if raw_value[:1] in ("\"", "'") and raw_value[-1:] == raw_value[:1] else raw_value
        lname = _svg_attr_name(name)
        if lname.startswith("on"):
            return ""
        if lname in ("href", "xlink:href", "src"):
            probe = _deep_decode(value).lower()
            if probe.startswith(_DANGEROUS_SCHEME):
                return ""
            if not probe.startswith(_SAFE_ATTR_SCHEME):
                return ""
        return match.group(0)

    text = _ATTR_RE.sub(_clean_attrs, text)

    normalized = _deep_decode(text).lower()
    if re.search(r"=\s*[\"']?(javascript|vbscript)\s*:", normalized) or "<script" in normalized:
        return b""
    return text.encode("utf-8")


def media_file_headers(path: Path) -> dict:
    """SVG 文件加 Content-Disposition: attachment：<img> 展示不受影响，
    但直接在浏览器打开该 URL 时下载而非执行（防同源脚本运行）。"""
    if path.suffix.lower() == ".svg":
        return {"Content-Disposition": "attachment"}
    return {}


def _store_avatar(user, ext: str, data: bytes) -> str:
    """删除旧头像并落盘新文件（磁盘写，放线程池）；返回入库用的相对路径。"""
    from app.core import data_dirs

    if user.avatar_path:
        old = data_dirs.resolve_rel(user.avatar_path)
        if old:
            old.unlink(missing_ok=True)
    return save_bytes(data_dirs.AVATARS, f"ihub_user_avatars_{user.id}{ext}", data)


def avatar_url_for(user) -> str | None:
    """头像地址附带文件修改时间，更换头像后 URL 变化，规避浏览器缓存旧图。"""
    from app.core import data_dirs
    from app.core.fsutil import safe_mtime

    if not user.avatar_path:
        return None
    path = data_dirs.resolve_rel(user.avatar_path)
    v = safe_mtime(path) if path else None
    if not v:
        return None
    return f"/api/v1/users/avatar/{user.id}?v={v}"


async def apply_avatar_upload(user, file) -> None:
    """头像上传的公共校验与落盘（本人 /auth/avatar 与管理员 /users/{id}/avatar 共用）。

    只改 user.avatar_path，不提交事务——交由调用方决定何时 commit/refresh。
    """
    from fastapi import HTTPException, run_in_threadpool

    ext = ALLOWED_IMAGE_TYPES.get(file.content_type or "")
    if not ext:
        raise HTTPException(400, "仅支持 PNG / JPG / WebP / SVG / ICO 图片")
    # 设置读取（独立会话）与图片解码/落盘都不在事件循环里跑
    limit = await run_in_threadpool(avatar_upload_max_size)
    data = await read_limited(file, limit, f"头像不能超过 {limit // 1024 // 1024}MB（可在 设置 → 系统 → 附件上传限制 调整）")
    if ext == ".svg":
        data = await run_in_threadpool(sanitize_svg, data)
    if not data:
        raise HTTPException(400, "文件为空")
    user.avatar_path = await run_in_threadpool(_store_avatar, user, ext, data)
