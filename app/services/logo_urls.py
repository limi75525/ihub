"""站内媒体展示地址：本地文件（logo_path/cover_path）优先，附 mtime 版本号防缓存；
否则回退外链 URL。

头像库（分组/规则）、接入服务、用户头像、站点品牌等所有「上传文件 or 外链」的
展示地址共用同一口径；版本号用 core.fsutil.safe_mtime（并发换图不抛错，接口不 500）。
"""

from pathlib import Path

from app.core.config import settings
from app.core.fsutil import safe_mtime


def file_url(
    path_rel: str | None,
    endpoint: str,
    fallback_url: str | None = None,
    *,
    require_file: bool = False,
) -> str | None:
    """path_rel 有值 → `<endpoint>?v=<mtime>`；否则原样返回 fallback_url。

    require_file=True 时文件缺失（mtime=0）也回退 fallback_url——站点 Logo / 用户头像
    语义：设置里残留的已删文件路径不应下发一个必然 404 的地址。
    """
    if not path_rel:
        return fallback_url
    v = safe_mtime(Path(settings.DATA_DIR) / path_rel)
    if require_file and not v:
        return fallback_url
    return f"{endpoint}?v={v}"
