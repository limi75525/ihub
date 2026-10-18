"""媒体库 NFO（Kodi / Emby / Jellyfin 风格 XML）解析：电影、剧集、单集、季。

NAS 刮削工具（tinyMediaManager、nas-tools 等）会在媒体文件旁写 NFO：
- 电影：`<视频同名>.nfo` 或目录内 `movie.nfo`，根元素 `<movie>`
- 单集：`<视频同名>.nfo`，根元素 `<episodedetails>`
- 剧集：剧集目录（或季目录的上级）`tvshow.nfo`，根元素 `<tvshow>`
- 季：季目录内 `season.nfo` / `seasonNN.nfo` / `<季目录名>.nfo`，根元素 `<season>`
  （作为剧集级字段的兜底：季简介填 series_plot、季年份供 TMDB 匹配，优先级低于 tvshow.nfo）

解析原则：字段缺失/脏数据按空处理，单条坏 NFO 不中断扫描；读取限 2MB
（XML 实体膨胀防护）；评分兼容 `<rating>8.7</rating>` 与新版
`<ratings><rating><value>8.7</value></rating></ratings>` 两种写法。
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_NFO_BYTES = 2 * 1024 * 1024
MAX_ACTORS = 24
MAX_PLOT = 1200
MAX_NAMES = 8


def _local(tag: str) -> str:
    """剥命名空间前缀（个别工具会给根元素加 ns）与大小写差异。"""
    return tag.rsplit("}", 1)[-1].lower()


def read_element(path: Path) -> ET.Element | None:
    """读取并解析 NFO；任何失败（超限/编码/损坏 XML）返回 None，绝不抛出。"""
    try:
        if path.stat().st_size > MAX_NFO_BYTES:
            logger.warning("NFO 超过大小上限，跳过：%s", path.name)
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        return ET.fromstring(raw)
    except (ET.ParseError, ValueError):
        pass
    # 声明与字节编码不符（GBK 内容配 UTF-8 声明等）：按 UTF-8 容错解码再试一次
    text = raw.decode("utf-8", "replace")
    if text.lstrip().startswith("<?xml"):
        text = text.split("?>", 1)[-1]
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        logger.warning("NFO 解析失败，跳过：%s", path.name)
        return None


def _clean(node: ET.Element | None, limit: int = 0) -> str:
    if node is None or not node.text:
        return ""
    text = " ".join(node.text.replace("\r", "").split())
    return text[:limit] if limit else text


def _text(el: ET.Element, tag: str, limit: int = 0) -> str:
    for child in el:
        if _local(child.tag) == tag:
            return _clean(child, limit)
    return ""


def _plot(el: ET.Element) -> str:
    for child in el:
        if _local(child.tag) in ("plot", "outline") and child.text:
            raw = child.text.replace("\r", "").strip()
            if raw:
                return raw[:MAX_PLOT]
    return ""


def _rating(el: ET.Element) -> float:
    """评分（0~10）；100 分制/异常值一律忽略。"""
    candidates = [_text(el, "rating")]
    for ratings in el:
        if _local(ratings.tag) != "ratings":
            continue
        for sub in ratings:
            if _local(sub.tag) != "rating":
                continue
            candidates.append(_text(sub, "value"))
            candidates.append(_clean(sub))
    for raw in candidates:
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if 0 < value <= 10:
            return round(value, 1)
    return 0.0


def _year(el: ET.Element) -> int:
    raw = _text(el, "year")
    if not raw:
        raw = _text(el, "premiered")[:4] or _text(el, "releasedate")[:4]
    try:
        value = int(raw)
    except ValueError:
        return 0
    return value if 1900 <= value <= 2100 else 0


def _runtime_min(el: ET.Element) -> int:
    try:
        value = int(_text(el, "runtime"))
    except ValueError:
        return 0
    return value if 1 <= value <= 1000 else 0


def _names(el: ET.Element, tag: str) -> str:
    """多个子元素文本去重后按逗号连接（导演等扁平字段）。"""
    seen: list[str] = []
    for child in el:
        if _local(child.tag) != tag:
            continue
        name = _clean(child, 256)
        if name and name not in seen:
            seen.append(name)
        if len(seen) >= MAX_NAMES:
            break
    return ",".join(seen)


def _actors(el: ET.Element) -> str:
    """演员表存紧凑 JSON：[[姓名, 角色, 头像URL], ...]；只保留 http(s) 头像（本地路径无意义）。"""
    out: list[list[str]] = []
    for child in el:
        if _local(child.tag) != "actor":
            continue
        name = _text(child, "name", 128)
        if not name:
            continue
        role = _text(child, "role", 128)
        thumb = _text(child, "thumb", 512)
        if thumb and not thumb.startswith(("http://", "https://")):
            thumb = ""
        out.append([name, role, thumb])
        if len(out) >= MAX_ACTORS:
            break
    return json.dumps(out, ensure_ascii=False) if out else ""


def _tmdb_id(el: ET.Element) -> str:
    """TMDB 编号：只保留纯数字（拼进上游 URL 前必须过这一关，防路径注入）。"""
    for tag in ("tmdbid", "tmdb_id"):
        value = _text(el, tag, 32)
        if value.isdigit():
            return value
    for child in el:
        if _local(child.tag) == "uniqueid" and (child.get("type") or "").lower() == "tmdb":
            value = _clean(child, 32)
            if value.isdigit():
                return value
    return ""


def _image_ref(el: ET.Element, tag: str) -> str:
    """NFO 里的海报/剧照引用；只取本地文件名（URL 不落库，服务端不做远程拉取）。"""
    node = None
    for child in el:
        if _local(child.tag) == tag:
            node = child
            break
    if node is None:
        return ""
    text = _clean(node, 512)
    if not text:
        # Emby/Kodi 两种写法：<fanart>url</fanart> 与 <fanart><thumb>url</thumb></fanart>
        text = _text(node, "thumb", 512)
    if not text or "://" in text or text.startswith("//"):
        return ""
    return text


def parse_movie(el: ET.Element) -> dict:
    """电影 NFO → 模型字段（title/original_title/plot/year/rating/genres/directors/actors/runtime_min/图片引用）。"""
    return {
        "title": _text(el, "title", 512),
        "original_title": _text(el, "originaltitle", 512),
        "plot": _plot(el),
        "year": _year(el),
        "rating": _rating(el),
        "genres": _names(el, "genre")[:256],
        "directors": _names(el, "director")[:512],
        "actors": _actors(el),
        "runtime_min": _runtime_min(el),
        "poster_ref": _image_ref(el, "poster"),
        "fanart_ref": _image_ref(el, "fanart"),
        "tmdb_id": _tmdb_id(el),
    }


def parse_episode(el: ET.Element) -> dict:
    """单集 NFO → ep_title/plot/rating/runtime_min（剧名不取自 NFO，保持文件名分组稳定）。"""
    return {
        "ep_title": _text(el, "title", 512),
        "plot": _plot(el),
        "rating": _rating(el),
        "runtime_min": _runtime_min(el),
    }


def parse_tvshow(el: ET.Element) -> dict:
    """剧集 NFO → 系列级字段（series_* 前缀落在每条分集行上供聚合适配；tmdbid 供在线补全）。

    series_title / series_original_title 不进数据库（只作标题自动匹配的候选）。
    """
    return {
        "series_plot": _plot(el),
        "series_rating": _rating(el),
        "series_genres": _names(el, "genre")[:256],
        "series_tmdb_id": _tmdb_id(el),
        "series_title": _text(el, "title", 512),
        "series_original_title": _text(el, "originaltitle", 512),
    }


def parse_season(el: ET.Element) -> dict:
    """季 NFO（Emby/Jellyfin 风格 `<season>`）→ 剧集级兜底字段。

    series_plot 与 tvshow.nfo 同键（合并时 tvshow 优先，季简介只在剧集缺简介时生效）；
    season_title/season_year 只用于标题自动匹配与年份守卫，不落库。
    """
    return {
        "series_plot": _plot(el),
        "series_year": _year(el),
        "season_title": _text(el, "title", 512),
    }


def nfo_sig(path: Path | None) -> str:
    """NFO 增量签名（mtime_ns:size）；无 NFO 为空串，用于「视频没动但 NFO 被重写」的重新解析。"""
    if path is None:
        return ""
    try:
        st = path.stat()
    except OSError:
        return ""
    return f"{st.st_mtime_ns}:{st.st_size}"


def parse_file(path: Path) -> dict:
    """读文件并按根元素分派解析；无法识别/损坏返回空 dict。"""
    el = read_element(path)
    if el is None:
        return {}
    tag = _local(el.tag)
    if tag == "episodedetails":
        return parse_episode(el)
    if tag == "tvshow":
        return parse_tvshow(el)
    if tag == "season":
        return parse_season(el)
    if tag == "movie":
        return parse_movie(el)
    return {}
