"""音乐中心标签解析：mutagen 读标签 + Pillow 提取内嵌封面。

从 api/v1/music.py 平移的纯解析层（读音频文件/写封面缓存，不碰路由逻辑）。
- mutagen / Pillow 都是可选依赖：缺失时标签解析降级为按文件名兜底，不抛异常；
- 封面哈希取自相对路径：同一路径重复扫描时复用/覆盖，不产生垃圾文件；
- 解压炸弹防护：_MAX_COVER_PIXELS 上限，超限封面直接跳过（认证后 DoS）。
"""

import hashlib
import io
import re
from pathlib import Path

from app.core import data_dirs
from app.core.config import settings as cfg

try:
    import mutagen
except ImportError:  # pragma: no cover
    mutagen = None

# 图片解码上限：4000 万像素（约 8000x5000）。服务端 Image.load() 是全量解码，
# 不设上限时一张几百 KB 的 PNG 可膨胀到数百 MB 内存（解压炸弹，认证后 DoS）
_MAX_COVER_PIXELS = 40_000_000

_YEAR_RE = re.compile(r"(\d{4})")


def _cover_dir() -> Path:
    d = Path(cfg.DATA_DIR) / data_dirs.MUSIC_COVERS
    d.mkdir(parents=True, exist_ok=True)
    return d


def _extract_cover(mf, rel: str) -> str:
    """提取内嵌封面到 data/music_covers/<hash>.<ext>，返回相对路径；无封面返回空。
    哈希取自相对路径：同一路径重复扫描时复用/覆盖，不产生垃圾文件。"""
    data = b""
    try:
        if hasattr(mf, "pictures") and mf.pictures:  # FLAC / APEv2
            data = mf.pictures[0].data or b""
        if not data and mf.tags:
            tags = mf.tags
            try:
                covr = tags["covr"]  # MP4/M4A（键查找大小写不敏感，dict.get 不可用）
                data = bytes(covr[0])
            except (KeyError, ValueError, IndexError, TypeError):
                # ID3（MP3）：APIC 的描述非空时 dict 键是 "APIC:<desc>"（iTunes 等工具常写
                # desc="cover"），tags["APIC"] / tags["APIC:"] 都取不到——用 getall 全取，
                # 多帧时优先 type=3（正面前封面）
                try:
                    pics = tags.getall("APIC")
                except Exception:
                    pics = []
                if pics:
                    front = next((p for p in pics if getattr(p, "type", 0) == 3), pics[0])
                    data = front.data or b""
    except Exception:
        return ""
    if len(data) < 64:
        return ""
    from PIL import Image  # 可选依赖：延迟导入，扫描时才需要

    name = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:24]
    ext = ".png" if data[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg"
    target = _cover_dir() / f"{name}{ext}"
    # 压到 300px 方边内，避免几 MB 的原封面拖累列表加载
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.width * im.height > _MAX_COVER_PIXELS:
                return ""  # 异常超大封面（解压炸弹形态）：跳过，不影响曲目入库
            im = im.convert("RGB") if ext == ".jpg" else im
            im.thumbnail((300, 300))
            im.save(target, quality=85)
    except Exception:
        return ""
    return f"music_covers/{target.name}"


def _read_tags(path: Path, rel: str) -> dict:
    title, artist, album, duration = "", "", "", 0.0
    album_artist = genre = ""
    year = track_no = disc_no = bitrate = sample_rate = 0
    cover_path = None
    note = ""
    if mutagen is not None:
        try:
            mf = mutagen.File(str(path))
            if mf is not None:
                duration = float(getattr(mf.info, "length", 0) or 0)
                bitrate = int(getattr(mf.info, "bitrate", 0) or 0) // 1000
                sample_rate = int(getattr(mf.info, "sample_rate", 0) or 0)
                tags = mf.tags or {}

                def first(*keys):
                    """按序取第一个非空标签。注意必须走 tags[k]（dict.get 匹配不到）；
                    mutagen 各容器对缺失键抛的异常不一（VComment 抛 ValueError，
                    ID3/MP4 抛 KeyError），两样都要接住。"""
                    for k in keys:
                        try:
                            v = tags[k]
                        except (KeyError, ValueError):
                            continue
                        if v:
                            return str(v[0] if isinstance(v, list) else v)
                    return ""

                def first_int(*keys):
                    raw = first(*keys)
                    m = re.search(r"\d+", raw)
                    return int(m.group()) if m else 0

                title = first("TIT2", "©nam", "TITLE")
                artist = first("TPE1", "©ART", "ARTIST")
                album = first("TALB", "©alb", "ALBUM")
                album_artist = first("TPE2", "aART", "ALBUMARTIST", "ALBUM ARTIST")
                genre = first("TCON", "©gen", "©gne", "GENRE")[:128]
                ym = _YEAR_RE.search(first("TDRC", "TDRL", "TDOR", "TYER", "©day", "DATE"))
                year = int(ym.group(1)) if ym else 0
                track_no = first_int("TRCK", "trkn", "TRACKNUMBER")
                disc_no = first_int("TPOS", "disk", "DISCNUMBER")
                cover_path = _extract_cover(mf, rel) or None
        except Exception as e:
            note = f"标签读取失败：{e}"
    stem = path.stem
    if not title:
        title = stem
        note = note or "无标题标签，按文件名识别"
    if not artist:
        artist = "未知歌手"
    if not album:
        album = "未知专辑"
    return {
        "path": rel,
        "title": title[:512],
        "artist": artist[:512],
        "album": album[:512],
        "album_artist": album_artist[:512],
        "genre": genre,
        "year": year,
        "track_no": track_no,
        "disc_no": disc_no,
        "duration": duration,
        "bitrate": bitrate,
        "sample_rate": sample_rate,
        "ext": path.suffix.lower()[:16],
        "size": path.stat().st_size,
        "mtime": int(path.stat().st_mtime),
        "cover_path": cover_path,
        "note": note[:512],
    }
