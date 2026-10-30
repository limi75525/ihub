"""图标库（开源品牌图标）本地资源管理。

设计要点（2026-10-30 用户拍板）：
- **不随 iHub 发布**：图标库由管理员在「头像库 → 图标库」里下载后才可用，实例级共享。
- **来源必须可追溯**：每个库带 name / license / source_url / version，展示时标明出处，
  存储的图标地址自描述（`/api/v1/brand/icon/{lib}/{slug}`），任何位置都能反解来源。
- **两种存储形态**：simple-icons 只有「单路径 + 品牌色」，入库时抽取 path 数据后按需上色
  （体积小、可换色）；devicon 与自定义包保留原始 SVG 文件。
- **安全**：解包只放行 .svg/.json，拒绝绝对路径与 ..，限制总量；自定义下载仅 http(s)。
"""
from __future__ import annotations

import html as _html
import io
import json
import logging
import re
import shutil
import tarfile
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlparse

from app.core import data_dirs
from app.core.config import settings

logger = logging.getLogger(__name__)

ROOT = data_dirs.BRAND_ICONS
MANIFEST = "manifest.json"

# 内置可下载库（图标本体不随仓库发布，只有介绍与下载地址）
BUILTIN_LIBS: dict[str, dict] = {
    "simple-icons": {
        "name": "Simple Icons",
        "kind": "path",
        "license": "CC0-1.0",
        "license_url": "https://github.com/simple-icons/simple-icons/blob/develop/LICENSE.md",
        "source_url": "https://github.com/simple-icons/simple-icons",
        "homepage": "https://simpleicons.org",
        "description": "3400+ 品牌图标，单色路径，可自由着色",
        "approx_mb": 15,
        "registry": "simple-icons",
        "icon_dir": "icons",
        "meta_file": "data/simple-icons.json",
    },
    "devicon": {
        "name": "Devicon",
        "kind": "file",
        "license": "MIT",
        "license_url": "https://github.com/devicons/devicon/blob/master/LICENSE",
        "source_url": "https://github.com/devicons/devicon",
        "homepage": "https://devicon.dev",
        "description": "657 个开发技术图标，含官方彩色原版",
        "approx_mb": 40,
        "registry": "devicon",
        "icon_dir": "icons",
        "meta_file": "devicon.json",
        "original_only": True,
    },
}

MIRRORS = ("https://registry.npmmirror.com", "https://registry.npmjs.org")

MAX_DOWNLOAD_BYTES = 120 * 1024 * 1024
MAX_SVG_BYTES = 300 * 1024
MAX_ICONS = 6000
MAX_UNPACK_BYTES = 400 * 1024 * 1024

_HEX_RE = re.compile(r"^[0-9A-Fa-f]{3,8}$")
_SVG_PATH_RE = re.compile(r'<path[^>]*\bd="([^"]+)"')
_SVG_TITLE_RE = re.compile(r"<title>([^<]*)</title>")
_SVG_FILL_RE = re.compile(r'fill="(#[0-9A-Fa-f]{3,8})"')


def _root() -> Path:
    p = Path(settings.DATA_DIR) / ROOT
    p.mkdir(parents=True, exist_ok=True)
    return p


def _lib_dir(lib_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,48}", lib_id or ""):
        raise ValueError("非法图标库标识")
    return _root() / lib_id


# ---------------- 别名表（随 iHub 发布） ----------------

_ALIAS_LOCK = threading.Lock()
_ALIAS_CACHE: dict | None = None


def aliases() -> dict:
    """随包发布的中文别名/域名表，按库分组。文件缺失时返回空表（不影响功能）。"""
    global _ALIAS_CACHE
    with _ALIAS_LOCK:
        if _ALIAS_CACHE is not None:
            return _ALIAS_CACHE
        path = Path(__file__).resolve().parent.parent / "assets" / "brand_aliases.json"
        try:
            _ALIAS_CACHE = json.loads(path.read_text(encoding="utf-8")).get("entries") or {}
        except (OSError, ValueError):
            logger.warning("图标别名表缺失或损坏：%s", path)
            _ALIAS_CACHE = {}
        return _ALIAS_CACHE


# ---------------- 清单读写 ----------------

def load_manifest(lib_id: str) -> dict | None:
    path = _lib_dir(lib_id) / MANIFEST
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def list_libs() -> list[dict]:
    """内置库（含未安装）+ 已安装的自定义库。"""
    out: list[dict] = []
    for lib_id, spec in BUILTIN_LIBS.items():
        man = load_manifest(lib_id)
        out.append({
            "id": lib_id,
            "name": spec["name"],
            "kind": spec["kind"],
            "license": spec["license"],
            "license_url": spec["license_url"],
            "source_url": spec["source_url"],
            "homepage": spec["homepage"],
            "description": spec["description"],
            "approx_mb": spec["approx_mb"],
            "builtin": True,
            "installed": bool(man),
            "version": (man or {}).get("version", ""),
            "icon_count": (man or {}).get("icon_count", 0),
            "installed_at": (man or {}).get("installed_at", ""),
            "size": _dir_size(_lib_dir(lib_id)) if man else 0,
        })
    for child in sorted(_root().iterdir()):
        if not child.is_dir() or child.name in BUILTIN_LIBS:
            continue
        man = load_manifest(child.name)
        if not man:
            continue
        out.append({
            "id": child.name,
            "name": man.get("name") or child.name,
            "kind": man.get("kind", "file"),
            "license": man.get("license", ""),
            "license_url": man.get("license_url", ""),
            "source_url": man.get("source_url", ""),
            "homepage": man.get("homepage", ""),
            "description": man.get("description", ""),
            "approx_mb": 0,
            "builtin": False,
            "installed": True,
            "version": man.get("version", ""),
            "icon_count": man.get("icon_count", 0),
            "installed_at": man.get("installed_at", ""),
            "size": _dir_size(child),
        })
    return out


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except OSError:
        return total
    return total


def remove_lib(lib_id: str) -> bool:
    d = _lib_dir(lib_id)
    if not d.is_dir():
        return False
    shutil.rmtree(d, ignore_errors=True)
    _index_bust(lib_id)
    return True


# ---------------- 下载与解包 ----------------

def _http_get(url: str, timeout: int = 120) -> bytes:
    import urllib.error
    import urllib.request

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("只支持 http(s) 下载地址")
    req = urllib.request.Request(url, headers={"User-Agent": "iHub-brand-icons/1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        length = resp.headers.get("Content-Length")
        if length and int(length) > MAX_DOWNLOAD_BYTES:
            raise ValueError("图标库包超过大小上限")
        buf = io.BytesIO()
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            buf.write(chunk)
            if buf.tell() > MAX_DOWNLOAD_BYTES:
                raise ValueError("图标库包超过大小上限")
        return buf.getvalue()


def _resolve_tarball(pkg: str, version_hint: str = "") -> tuple[str, str]:
    """返回 (版本, tarball 地址)，按镜像顺序尝试。"""
    last: Exception | None = None
    for base in MIRRORS:
        try:
            meta = json.loads(_http_get(f"{base}/{quote(pkg)}/latest", timeout=30))
            version = str(meta.get("version") or version_hint or "")
            tarball = (meta.get("dist") or {}).get("tarball") or f"{base}/{pkg}/-/{pkg}-{version}.tgz"
            return version, tarball
        except Exception as e:  # noqa: BLE001 逐个镜像回退
            last = e
    raise RuntimeError(f"无法获取 {pkg} 的下载地址：{last}")


def _safe_member(name: str) -> str | None:
    p = PurePosixPath(name.replace("\\", "/")).as_posix()
    if p.startswith("/") or ".." in p.split("/"):
        return None
    return p


def _extract_tar(data: bytes) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    total = 0
    try:
        tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except tarfile.TarError:
        raise ValueError("不是有效的 tgz 包")
    with tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            name = _safe_member(member.name)
            if not name or not name.lower().endswith((".svg", ".json", ".md", ".txt")):
                continue
            if member.size > MAX_SVG_BYTES * 4:
                continue
            fh = tf.extractfile(member)
            if not fh:
                continue
            blob = fh.read()
            total += len(blob)
            if total > MAX_UNPACK_BYTES:
                raise ValueError("解包后体积超过上限")
            files[name] = blob
    return files


def _extract_zip(data: bytes) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    total = 0
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("不是有效的 zip 包")
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = _safe_member(info.filename)
            if not name or not name.lower().endswith((".svg", ".json", ".md", ".txt")):
                continue
            if info.file_size > MAX_SVG_BYTES * 4:
                continue
            blob = zf.read(info)
            total += len(blob)
            if total > MAX_UNPACK_BYTES:
                raise ValueError("解包后体积超过上限")
            files[name] = blob
    return files


def _norm_title(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (text or "").lower())


def _registrable(host: str) -> str:
    """粗略取可注册域名（够用即可）：保留最后两段，处理 .com.cn 这类两段后缀。"""
    host = (host or "").strip().lower().lstrip(".")
    if not host:
        return ""
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("com", "net", "org", "gov", "edu") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _domain_index(icons: dict, slug_field: str = "t") -> dict[str, str]:
    """从 source 推断 域名 → slug；只保留域名主标签与 slug/标题高度相似的对。"""
    out: dict[str, str] = {}
    for slug, meta in icons.items():
        src = str(meta.get("s") or "")
        if not src:
            continue
        host = urlparse(src).netloc.lower()
        if not host or "github" in host or "wikipedia" in host or "wikimedia" in host:
            continue
        reg = _registrable(host)
        if not reg:
            continue
        label = _norm_title(reg.split(".")[0])
        ns = _norm_title(slug)
        nt = _norm_title(meta.get("t") or "")
        if not label or len(label) < 3:
            continue
        if label == ns or label == nt or (ns and len(ns) >= 3 and ns in label) or (label in ns and len(label) >= 4):
            out.setdefault(reg, slug)
    return out


def _build_simple_icons(files: dict[str, bytes], version: str) -> dict:
    """simple-icons：抽取单路径数据，按需上色。"""
    meta_blob = None
    for name, blob in files.items():
        if name.endswith("data/simple-icons.json"):
            meta_blob = blob
            break
    if meta_blob is None:
        raise ValueError("包内缺少 data/simple-icons.json")
    metas = json.loads(meta_blob.decode("utf-8"))
    icons: dict[str, dict] = {}
    for item in metas:
        slug = str(item.get("slug") or "").strip()
        if not slug:
            continue
        svg = files.get(f"package/icons/{slug}.svg")
        if svg is None:
            for name, blob in files.items():  # 兼容不同打包层级
                if name.endswith(f"/icons/{slug}.svg"):
                    svg = blob
                    break
        if svg is None:
            continue
        text = svg.decode("utf-8", "replace")
        m = _SVG_PATH_RE.search(text)
        if not m:
            continue
        entry = {"t": item.get("title") or slug, "h": (item.get("hex") or "").lstrip("#"), "d": m.group(1)}
        aka = (item.get("aliases") or {}).get("aka") or []
        if aka:
            entry["a"] = [str(x) for x in aka][:6]
        if item.get("source"):
            entry["s"] = str(item["source"])[:300]
        icons[slug] = entry
        if len(icons) >= MAX_ICONS:
            break
    return {
        "kind": "path",
        "version": version,
        "icons": icons,
        "domains": _domain_index(icons),
    }


def _build_devicon(files: dict[str, bytes], version: str) -> dict:
    """devicon：只保留 original 彩色原版文件。"""
    meta_blob = None
    for name, blob in files.items():
        if name.endswith("devicon.json"):
            meta_blob = blob
            break
    if meta_blob is None:
        raise ValueError("包内缺少 devicon.json")
    metas = json.loads(meta_blob.decode("utf-8"))
    icons: dict[str, dict] = {}
    saved: dict[str, bytes] = {}
    for item in metas:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        variants = (item.get("versions") or {}).get("svg") or []
        pick = "original" if "original" in variants else (variants[0] if variants else "")
        if not pick:
            continue
        target = ""
        for fname, blob in files.items():
            if fname.endswith(f"/{name}/{name}-{pick}.svg") or fname.endswith(f"/{name}-{pick}.svg"):
                target = fname
                icons[name] = {
                    "t": item.get("name") or name,
                    "h": (item.get("color") or "").lstrip("#"),
                    "f": f"icons/{name}.svg",
                    "a": [str(x) for x in (item.get("altnames") or [])][:6],
                }
                saved[f"icons/{name}.svg"] = blob
                break
        if not target:
            continue
        if len(icons) >= MAX_ICONS:
            break
    return {
        "kind": "file",
        "version": version,
        "icons": icons,
        "domains": _domain_index(icons),
        "files": saved,
    }


# ---------------- 安装 ----------------

_TASKS: dict[str, dict] = {}
_TASK_LOCK = threading.Lock()


def _task_set(task_id: str, **kw) -> None:
    with _TASK_LOCK:
        task = _TASKS.setdefault(task_id, {})
        task.update(kw)
        task["updated_at"] = int(time.time())


def task_state(task_id: str) -> dict:
    with _TASK_LOCK:
        return dict(_TASKS.get(task_id) or {})


def install_builtin(lib_id: str, task_id: str) -> None:
    """后台线程：下载内置库并入库。"""
    spec = BUILTIN_LIBS.get(lib_id)
    if not spec:
        _task_set(task_id, state="error", error="未知图标库")
        return
    _task_set(task_id, state="running", phase="download", message="正在获取下载地址")
    try:
        version, tarball = _resolve_tarball(spec["registry"])
        _task_set(task_id, phase="download", message=f"正在下载 {spec['name']} {version}")
        blob = _http_get(tarball)
        _task_set(task_id, phase="extract", message="正在解包")
        files = _extract_tar(blob)
        _task_set(task_id, phase="build", message="正在建立索引")
        built = _build_simple_icons(files, version) if spec["kind"] == "path" else _build_devicon(files, version)
        if not built["icons"]:
            raise ValueError("包内没有可用图标")
        _write_lib(lib_id, spec, built, task_id)
        _task_set(task_id, state="done", phase="done", message=f"已安装 {len(built['icons'])} 个图标")
    except Exception as e:  # noqa: BLE001 任务失败回传给前端
        logger.exception("安装图标库失败：%s", lib_id)
        _task_set(task_id, state="error", error=str(e)[:300])


def install_from_url(lib_id: str, name: str, url: str, task_id: str, *, license_name: str = "", source_url: str = "") -> None:
    """后台线程：从自定义链接下载 zip 并入库。"""
    _task_set(task_id, state="running", phase="download", message="正在下载")
    try:
        blob = _http_get(url, timeout=180)
        if not blob[:2] == b"PK":
            raise ValueError("下载内容不是 zip 包")
        _task_set(task_id, phase="extract", message="正在解包")
        files = _extract_zip(blob)
        _task_set(task_id, phase="build", message="正在建立索引")
        manifest = _build_custom(files, name, license_name=license_name, source_url=source_url)
        if not manifest["icons"]:
            raise ValueError("包内没有找到 SVG 图标")
        final_name = name or manifest.get("pkg_name") or lib_id
        final_license = license_name or manifest.get("pkg_license") or ""
        final_source = source_url or manifest.get("pkg_source") or url
        spec = {
            "name": final_name,
            "kind": manifest["kind"],
            "license": final_license or "未声明",
            "license_url": final_source,
            "source_url": final_source,
            "homepage": final_source,
            "description": "自定义链接导入的图标库",
        }
        _write_lib(lib_id, spec, manifest, task_id)
        _task_set(task_id, state="done", phase="done", message=f"已安装 {len(manifest['icons'])} 个图标")
    except Exception as e:  # noqa: BLE001 任务失败回传
        logger.exception("从链接安装图标库失败：%s", url)
        _task_set(task_id, state="error", error=str(e)[:300])


def install_from_zip(
    lib_id: str,
    name: str,
    data: bytes,
    *,
    license_name: str = "",
    source_url: str = "",
    fallback_name: str = "",
) -> dict:
    """自定义图标库（手动上传 / 自定义链接共用）。

    库名优先级：调用方显式指定 > 包内 manifest.json 的 name > 上传文件名（fallback_name）。
    """
    files = _extract_zip(data)
    manifest = _build_custom(files, name, license_name=license_name, source_url=source_url)
    if not manifest["icons"]:
        raise ValueError("包内没有找到 SVG 图标")
    final_name = name or manifest.get("pkg_name") or fallback_name or lib_id
    final_license = license_name or manifest.get("pkg_license") or ""
    final_source = source_url or manifest.get("pkg_source") or ""
    spec = {
        "name": final_name,
        "kind": manifest["kind"],
        "license": final_license or "未声明",
        "license_url": final_source,
        "source_url": final_source,
        "homepage": final_source,
        "description": "自定义导入的图标库",
        "kind_hint": "custom",
    }
    _write_lib(lib_id, spec, manifest, "")
    return {"id": lib_id, "icon_count": len(manifest["icons"])}


def _read_pkg_manifest(files: dict[str, bytes]) -> dict | None:
    """自定义包内可选的 manifest.json：声明库名/许可/来源与每个图标的别名、域名。

    取层级最浅的那个（包根优先）；解析失败按「没有清单」处理，不阻断导入。
    """
    candidates = sorted(
        (name for name in files if name.lower().endswith("manifest.json")),
        key=lambda n: n.count("/"),
    )
    for name in candidates:
        try:
            data = json.loads(files[name].decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", (text or "").lower()).strip("-")
    return slug


def _build_custom(files: dict[str, bytes], name: str, *, license_name: str = "", source_url: str = "") -> dict:
    """自定义图标库：裸 SVG 文件夹即可导入；附 manifest.json 时按清单声明标题/别名/域名。"""
    pkg = _read_pkg_manifest(files)
    declared = (pkg or {}).get("icons")
    declared = declared if isinstance(declared, dict) else {}

    svg_files = {f: b for f, b in files.items() if f.lower().endswith(".svg")}
    by_stem: dict[str, str] = {}
    for fname in svg_files:
        by_stem.setdefault(_slugify(PurePosixPath(fname).stem), fname)

    icons: dict[str, dict] = {}
    saved: dict[str, bytes] = {}
    domains: dict[str, str] = {}

    def add(slug: str, fname: str, meta: dict | None) -> None:
        blob = svg_files.get(fname)
        if not slug or not blob or slug in icons or len(icons) >= MAX_ICONS:
            return
        text = blob.decode("utf-8", "replace")
        meta = meta or {}
        title = str(meta.get("title") or "").strip()
        if not title:
            hit = _SVG_TITLE_RE.search(text)
            title = hit.group(1).strip() if hit else PurePosixPath(fname).stem
        hexval = str(meta.get("hex") or "").lstrip("#")
        if not hexval:
            fill = _SVG_FILL_RE.search(text)
            hexval = fill.group(1).lstrip("#") if fill else ""
        entry = {"t": title[:80], "h": hexval, "f": f"icons/{slug}.svg"}
        zh = [str(x).strip() for x in (meta.get("zh") or []) if str(x).strip()][:8]
        if zh:
            entry["zh"] = zh
        aka = [str(x).strip() for x in (meta.get("aliases") or []) if str(x).strip()][:8]
        if aka:
            entry["a"] = aka
        icons[slug] = entry
        saved[entry["f"]] = blob
        for dom in meta.get("domains") or []:
            key = _registrable(str(dom))
            if key:
                domains.setdefault(key, slug)

    if declared:
        for raw_slug, meta in declared.items():
            slug = _slugify(str(raw_slug))
            meta = meta if isinstance(meta, dict) else {}
            fname = str(meta.get("file") or "").lstrip("./")
            if fname not in svg_files:
                fname = by_stem.get(slug, "")
            add(slug, fname, meta)
    else:
        for fname in svg_files:
            add(_slugify(PurePosixPath(fname).stem), fname, None)

    return {
        "kind": "file",
        "version": str((pkg or {}).get("version") or "custom")[:32],
        "icons": icons,
        "domains": domains,
        "files": saved,
        "imported_from_manifest": bool(declared),
        "pkg_name": str((pkg or {}).get("name") or "")[:64],
        "pkg_license": str((pkg or {}).get("license") or "")[:64],
        "pkg_source": str((pkg or {}).get("source") or "")[:300],
    }


def _write_lib(lib_id: str, spec: dict, built: dict, task_id: str) -> None:
    target = _lib_dir(lib_id)
    tmp = target.with_suffix(".tmp")
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    if built["kind"] == "file":
        icons_dir = tmp / "icons"
        icons_dir.mkdir(parents=True, exist_ok=True)
        for rel, blob in (built.get("files") or {}).items():
            out = tmp / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(blob)
    manifest = {
        "id": lib_id,
        "name": spec["name"],
        "kind": built["kind"],
        "license": spec.get("license") or "",
        "license_url": spec.get("license_url") or "",
        "source_url": spec.get("source_url") or "",
        "homepage": spec.get("homepage") or "",
        "description": spec.get("description") or "",
        "version": built.get("version") or "",
        "icon_count": len(built["icons"]),
        "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "icons": built["icons"],
        "domains": built.get("domains") or {},
    }
    (tmp / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    tmp.rename(target)
    _index_bust(lib_id)
    if task_id:
        _task_set(task_id, icon_count=len(built["icons"]))


# ---------------- 索引与检索 ----------------

_INDEX_LOCK = threading.Lock()
_INDEX: dict[str, dict] = {}


def _index_bust(lib_id: str | None = None) -> None:
    with _INDEX_LOCK:
        if lib_id is None:
            _INDEX.clear()
        else:
            _INDEX.pop(lib_id, None)


def _lib_index(lib_id: str) -> dict | None:
    with _INDEX_LOCK:
        cached = _INDEX.get(lib_id)
    if cached is not None:
        return cached or None
    man = load_manifest(lib_id)
    if not man:
        with _INDEX_LOCK:
            _INDEX[lib_id] = {}
        return None
    zh_table = (aliases().get(lib_id) or {})
    by_title: dict[str, str] = {}
    by_alias: dict[str, str] = {}
    by_domain: dict[str, str] = {}
    alias_items: dict[str, list[str]] = {}
    for slug, meta in man.get("icons", {}).items():
        by_title.setdefault(_norm_title(meta.get("t") or slug), slug)
        by_title.setdefault(_norm_title(slug), slug)
        names: list[str] = []
        for aka in meta.get("a") or []:
            by_alias.setdefault(_norm_title(aka), slug)
            names.append(str(aka))
        # 自定义库可在 manifest.json 里给每个图标写 zh 别名；内置库用随包中文表
        for zh in list(meta.get("zh") or []) + list((zh_table.get(slug) or {}).get("zh") or []):
            by_alias.setdefault(_norm_title(zh), slug)
            names.append(str(zh))
        for dom in (zh_table.get(slug) or {}).get("domains") or []:
            by_domain.setdefault(_registrable(dom), slug)
        if names:
            alias_items[slug] = names
    for dom, slug in (man.get("domains") or {}).items():
        by_domain.setdefault(dom, slug)
    index = {
        "man": man,
        "by_title": by_title,
        "by_alias": by_alias,
        "by_domain": by_domain,
        "alias_items": alias_items,
        "zh": zh_table,
    }
    with _INDEX_LOCK:
        _INDEX[lib_id] = index
    return index


def installed_ids() -> list[str]:
    return [x["id"] for x in list_libs() if x["installed"]]


def _ver_token(man: dict) -> str:
    """库内容版本：安装时间戳去掉非数字。图标响应带 7 天缓存，URL 必须随库更新而变化。"""
    raw = str(man.get("installed_at") or "")
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits[:14]


def icon_url(lib_id: str, slug: str, color: str = "", ver: str = "") -> str:
    base = f"/api/v1/brand/icon/{lib_id}/{quote(slug)}"
    params = []
    if color:
        params.append(f"c={color}")
    if ver:
        params.append(f"v={ver}")
    return f"{base}?{'&'.join(params)}" if params else base


def search(q: str, lib: str | None = None, limit: int = 60, offset: int = 0) -> dict:
    """按名称/别名/域名搜索已安装图标库；结果带来源信息用于归属标注。"""
    needle = _norm_title(q)
    items: list[dict] = []
    for lid in installed_ids():
        if lib and lid != lib:
            continue
        idx = _lib_index(lid)
        if not idx:
            continue
        man = idx["man"]
        icons = man.get("icons", {})
        hits: list[str] = []
        if not needle:
            hits = list(icons.keys())
        else:
            for slug, meta in icons.items():
                blob = _norm_title(f"{slug} {meta.get('t') or ''}")
                if needle in blob:
                    hits.append(slug)
                    continue
                if idx["by_alias"].get(needle) == slug:
                    hits.append(slug)
                    continue
                if any(needle in _norm_title(a) for a in idx["alias_items"].get(slug, ())):
                    hits.append(slug)
        for slug in hits:
            meta = icons[slug]
            items.append({
                "lib": lid,
                "slug": slug,
                "title": meta.get("t") or slug,
                "hex": meta.get("h") or "",
                "url": icon_url(lid, slug, ver=_ver_token(man)),
                "license": man.get("license") or "",
                "source": man.get("name") or lid,
            })
    items.sort(key=lambda x: (len(x["title"]), x["title"].lower()))
    total = len(items)
    page = items[offset: offset + limit]
    return {"items": page, "total": total, "offset": offset, "limit": limit}


def _score_domain(host: str, idx: dict) -> tuple[int, str] | None:
    reg = _registrable(host)
    if not reg:
        return None
    slug = idx["by_domain"].get(reg)
    if slug:
        return 100, slug
    label = _norm_title(reg.split(".")[0])
    if not label:
        return None
    for key, value in idx["by_domain"].items():
        if key.split(".")[0] == label:
            return 90, value
    slug2 = idx["by_title"].get(label)
    if slug2:
        return 85, slug2
    return None


def suggest(name: str = "", url: str = "", limit: int = 5) -> dict:
    """导航/企业名 → 图标候选。返回按分数降序；调用方据最高分决定是否自动预选。"""
    host = ""
    if url:
        raw = url.strip()
        if "://" not in raw:
            raw = "http://" + raw
        host = urlparse(raw).netloc.split("@")[-1]
    needle = _norm_title(name)
    candidates: dict[tuple[str, str], tuple[int, dict]] = {}

    def push(lid: str, slug: str, score: int, reason: str) -> None:
        idx = _lib_index(lid)
        if not idx:
            return
        meta = idx["man"]["icons"].get(slug)
        if not meta:
            return
        key = (lid, slug)
        prev = candidates.get(key)
        if not prev or score > prev[0]:
            candidates[key] = (score, {
                "lib": lid,
                "slug": slug,
                "title": meta.get("t") or slug,
                "hex": meta.get("h") or "",
                "url": icon_url(lid, slug, ver=_ver_token(idx["man"])),
                "license": idx["man"].get("license") or "",
                "source": idx["man"].get("name") or lid,
                "score": score,
                "reason": reason,
            })

    for lid in installed_ids():
        idx = _lib_index(lid)
        if not idx:
            continue
        if host:
            hit = _score_domain(host, idx)
            if hit:
                push(lid, hit[1], hit[0], "域名")
        if needle:
            slug = idx["by_alias"].get(needle)
            if slug:
                push(lid, slug, 95, "别名")
            slug = idx["by_title"].get(needle)
            if slug:
                push(lid, slug, 90, "名称")
            if len(needle) >= 3:
                for key, slug2 in idx["by_title"].items():
                    if len(key) >= 3 and (needle in key or key in needle):
                        push(lid, slug2, 70, "近似")
                        break

    ordered = sorted(candidates.values(), key=lambda x: -x[0])
    items = [meta for _, meta in ordered[:limit]]
    return {
        "items": items,
        "auto": bool(items) and items[0]["score"] >= 90,
        "matched": bool(items),
    }


def icon_bytes(lib_id: str, slug: str, color: str = "") -> tuple[bytes, str]:
    """返回 (内容, mime)。simple-icons 按需上色，其余直接回原文件。"""
    man = load_manifest(lib_id)
    if not man:
        raise FileNotFoundError("图标库未安装")
    meta = (man.get("icons") or {}).get(slug)
    if not meta:
        raise FileNotFoundError("图标不存在")
    fill = ""
    if color and _HEX_RE.match(color):
        fill = color
    elif meta.get("h") and _HEX_RE.match(str(meta["h"])):
        fill = str(meta["h"])
    if man.get("kind") == "path":
        d = (meta.get("d") or "").replace('"', "")
        hexval = f"#{fill}" if fill else "currentColor"
        # 标题必须 XML 转义：品牌名里带 & < > " 的（1&1、H&M 等）不转义就是非法 SVG
        title = _html.escape(str(meta.get("t") or slug), quote=True)
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" role="img" '
            f'aria-label="{title}"><title>{title}</title>'
            f'<path fill="{hexval}" d="{d}"/></svg>'
        )
        return svg.encode("utf-8"), "image/svg+xml"
    path = _lib_dir(lib_id) / str(meta.get("f") or "")
    if not path.is_file():
        raise FileNotFoundError("图标文件缺失")
    return path.read_bytes(), "image/svg+xml"


def usage_breakdown() -> dict[str, int]:
    """统计各库被引用次数（用于卸载前提醒），由 API 层注入 DB 查询结果。"""
    return {}
