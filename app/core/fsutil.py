"""文件 stat 的竞态安全封装。

`int(path.stat().st_mtime) if path.is_file() else 0` 在 is_file 通过后文件被
并发删除/替换（换头像、重传 Logo 与列表渲染并发）时会抛 FileNotFoundError →
接口 500。缓存版本号场景下丢失一次 mtime 无害，统一回退 0。
"""

from pathlib import Path


def safe_mtime(path: str | Path) -> int:
    try:
        return int(Path(path).stat().st_mtime)
    except OSError:
        return 0


def safe_mtime_ns(path: str | Path) -> int:
    """纳秒精度版本号：秒级 mtime 在「同一秒内删除再上传」场景下不变（URL 缓存版本失效）。"""
    try:
        return Path(path).stat().st_mtime_ns
    except OSError:
        return 0


def data_file(root: str | Path, rel: str | None) -> Path | None:
    """DATA_DIR 内的 DB 相对路径 → resolve 后的绝对路径；空值/越界返回 None。

    rel（logo_path/cover_path/avatar_path 等）正常由服务端生成文件名写入，
    不会越界；万一 DB 被写入恶意相对路径（"../../x"），文件响应前在此拦下。
    与 messages/navlinks/recycle 已有的 resolve+relative_to 同一语义，收敛为共享实现。
    """
    if not rel:
        return None
    try:
        base = Path(root).resolve()
        p = (base / rel).resolve()
        p.relative_to(base)
    except (ValueError, OSError):
        return None
    return p
