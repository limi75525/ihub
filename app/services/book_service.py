"""书架解析服务：TXT 章节切分、EPUB 章节抽取与 HTML 清洗、封面提取。

输出统一为 {title, author, cover_bytes|None, chapters:[{title, html}]}，
章节内容为清洗后的 HTML（保留段落/标题/强调等，剔除脚本与事件属性）。
"""

import hashlib
import html as html_mod
import re
import shutil
import zipfile
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path

from app.core.config import settings
from app.core import data_dirs

# TXT 章节标题行：第X章/节/卷/回/部/集、序章、楔子、前后记、Chapter N 等
_TXT_CHAPTER_RE = re.compile(
    r"^\s{0,8}("
    r"第\s*[0-9〇零一二三四五六七八九十百千万两]+\s*[章节卷回部集篇]"
    r"|序章|楔子|前言|后记|尾声|终章|番外[之三四]?"
    r"|Chapter\s+\d+"
    r").{0,60}$"
)
_TXT_CHUNK_CHARS = 15000  # 无章节标记时的兜底切块大小

# EPUB 解压炸弹防护：zip 条目解压后大小无天然上限（1MB 压缩包可解出数十 GB）。
# 导入前按 central directory 预检（不读数据，零开销），资源服务时再限长读取兜底。
MAX_EPUB_ENTRY = 100 * 1024 * 1024  # 单条目解压后上限
MAX_EPUB_TOTAL = 300 * 1024 * 1024  # 全部条目解压后总量上限
MAX_EPUB_ASSET = 10 * 1024 * 1024  # epub_asset 单次读取上限（超限按资源缺失处理）


def epub_guard(path: Path) -> None:
    """EPUB 导入前校验 zip 条目解压后大小；超限抛 ValueError（调用方转 400）。"""
    try:
        with zipfile.ZipFile(path) as zf:
            total = 0
            for info in zf.infolist():
                if info.file_size > MAX_EPUB_ENTRY:
                    raise ValueError(f"单文件 {info.filename} 解压后超过 100MB")
                total += info.file_size
            if total > MAX_EPUB_TOTAL:
                raise ValueError("解压后总体积超过 300MB")
    except zipfile.BadZipFile:
        return  # 非 zip（加密/损坏 EPUB）交给解析阶段报错


NL = chr(10)

# 清洗时保留的标签；img 保留 src/alt，其余属性一律剔除（防事件注入）
_ALLOWED_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "br", "hr", "blockquote",
    "em", "strong", "b", "i", "u", "s", "sup", "sub",
    "ul", "ol", "li", "img", "figure", "figcaption", "center", "div", "span",
}
_DROP_TAGS = {"script", "style", "link", "meta", "head", "iframe", "video", "audio", "object", "svg"}
# HTML 空元素（无闭合标记，如 <link>/<meta>）：直接丢弃但不能计入 drop_depth，
# 否则深度永不清零，其后整章内容会被静默丢弃
_DROP_VOID_TAGS = {"link", "meta"}


def _detect_decode(raw: bytes) -> str:
    """TXT 编码探测：BOM → utf-8 → gbk → big5 → latin-1 兜底。"""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", errors="replace")


class _Sanitizer(HTMLParser):
    """重建白名单 HTML：剔除脚本/样式与全部事件属性；img 保留 src/alt。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.drop_depth = 0
        self.first_heading = ""

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _DROP_VOID_TAGS:
            return
        if tag in _DROP_TAGS or self.drop_depth:
            if tag in _DROP_TAGS:
                self.drop_depth += 1
            return
        if tag == "img":
            src = dict(attrs).get("src") or ""
            if src and not src.strip().lower().startswith(("data:", "http://", "https://")):
                alt = html_mod.escape(dict(attrs).get("alt") or "", quote=True)
                self.out.append(f'<img src="{html_mod.escape(src, quote=True)}" alt="{alt}" />')
            return
        if tag in _ALLOWED_TAGS:
            if tag in ("h1", "h2", "h3") and not self.first_heading:
                # 标题文本在 handle_data 里补记
                self._pending_heading_tag = tag
            el_id = html_mod.escape(dict(attrs).get("id") or "", quote=True)
            self.out.append(f"<{tag} id=\"{el_id}\">" if el_id else f"<{tag}>")

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if tag == "br" or tag == "hr":
            self.out.append(f"<{tag} />")
        elif tag == "img":
            self.handle_starttag("img", attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _DROP_VOID_TAGS:
            return
        if tag in _DROP_TAGS:
            self.drop_depth = max(0, self.drop_depth - 1)
            return
        if self.drop_depth:
            return
        if tag in _ALLOWED_TAGS and tag not in ("br", "hr", "img"):
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if self.drop_depth:
            return
        if getattr(self, "_pending_heading_tag", None):
            self.first_heading = data.strip()[:120]
            self._pending_heading_tag = None
        self.out.append(html_mod.escape(data))


def sanitize_html(raw: str | bytes) -> tuple[str, str]:
    """清洗 HTML，返回 (清洗后 HTML, 首个标题文本)。"""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    parser = _Sanitizer()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        return f"<p>{html_mod.escape(re.sub(r'<[^>]+>', ' ', raw))[:20000]}</p>", ""
    out = "".join(parser.out)
    # 规整空段落
    out = re.sub(r"<p>(\s|&nbsp;)*</p>", "", out)
    return out.strip(), parser.first_heading


def text_to_html(text: str) -> str:
    """纯文本 → 段落 HTML。"""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\r\n\s*\r\n", text) if p.strip()]
    if not paras:
        paras = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(f"<p>{html_mod.escape(p)}</p>" for p in paras)


def parse_txt(raw: bytes, fallback_title: str) -> dict:
    """TXT 切章：按章节标题行切分；无标记时按字数兜底切块。"""
    text = _detect_decode(raw).replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    marks: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _TXT_CHAPTER_RE.match(line.strip())
        if m:
            marks.append((i, line.strip()[:120]))
    chapters: list[dict] = []
    if len(marks) >= 2:
        for n, (start, title) in enumerate(marks):
            end = marks[n + 1][0] if n + 1 < len(marks) else len(lines)
            body = "\n".join(lines[start + 1 : end]).strip("\n")
            chapters.append({"title": title, "html": text_to_html(body)})
    else:
        flat = text.strip("\n")
        total = len(flat)
        if total <= _TXT_CHUNK_CHARS * 2:
            chapters = [{"title": fallback_title or "正文", "html": text_to_html(flat)}]
        else:
            pos, n = 0, 1
            while pos < total:
                end = min(pos + _TXT_CHUNK_CHARS, total)
                if end < total:  # 在切块尾部找段落边界，避免断句
                    brk = flat.rfind("\n", end - 500, end)
                    if brk > pos:
                        end = brk
                seg = flat[pos:end].strip("\n")
                if seg:
                    chapters.append({"title": f"第 {n} 节", "html": text_to_html(seg)})
                    n += 1
                pos = end
    if not chapters:
        chapters = [{"title": fallback_title or "正文", "html": text_to_html(text)}]
    return {"title": fallback_title, "author": "", "cover_bytes": None, "chapters": chapters}


def _split_by_anchors(cleaned: str, anchors: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """按 TOC 锚点把整篇清洗后的 HTML 切成段：返回 [(标题, HTML)]。

    首个锚点之前的零散内容（如部分扉页标题）作为独立段保留（用文档级标题）。
    段首自身的标题元素移除，避免与阅读器章节标题重复。
    """
    positions: list[tuple[int, str]] = []
    for aid, title in anchors:
        m = re.search(rf'<[a-z0-9]+[^>]*id="{re.escape(aid)}"', cleaned)
        if m:
            positions.append((m.start(), title.strip()[:120]))
    if len(positions) < 2:
        return []
    positions.sort()
    segments: list[tuple[str, str]] = []

    head = cleaned[: positions[0][0]].strip()
    if re.sub(r"<[^>]+>", "", head).strip():
        segments.append(("", head))

    for i, (pos, title) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(cleaned)
        seg = cleaned[pos:end].strip()
        # 去掉段首自身的标题元素（id 所在的 h1-h6），标题已由阅读器页眉展示
        seg = re.sub(r"^<h[1-6][^>]*>.*?</h[1-6]>\s*", "", seg, count=1, flags=re.S | re.I)
        if seg:
            segments.append((title, seg))
    return segments if len(segments) >= 2 else []


def parse_epub(path: Path) -> dict:
    """EPUB 抽章：spine 顺序遍历，标题取 TOC → 首个标题 → 文件名。"""
    import ebooklib
    from ebooklib import epub

    book = epub.read_epub(str(path), options={"ignore_ncx": False})
    meta_title = (book.get_metadata("DC", "title") or [[""]])[0][0] or path.stem
    meta_author = (book.get_metadata("DC", "creator") or book.get_metadata("DC", "author") or [[""]])[0][0] or ""

    # TOC：href → 标题
    href_titles: dict[str, str] = {}

    def flatten(items):
        for it in items:
            if isinstance(it, tuple):
                sub_title, children = it
                href = getattr(sub_title, "href", None) or getattr(sub_title, "content", "")
                if href:
                    href_titles[Path(href).as_posix().lstrip("./")] = sub_title.title or ""
                flatten(children)
            else:
                href = getattr(it, "href", None)
                if href:
                    href_titles[Path(href).as_posix().lstrip("./")] = it.title or ""

    try:
        flatten(book.toc)
    except Exception:
        pass

    # 封面：ITEM_COVER 类型 → OPF cover 元数据 → 文件名含 cover 的图片
    cover_bytes = None
    try:
        cover_item = next(iter(book.get_items_of_type(ebooklib.ITEM_COVER)), None)
        if cover_item is None:
            cover_meta = book.get_metadata("OPF", "cover")
            if cover_meta:
                cover_item = book.get_item_with_id(cover_meta[0][0])
        if cover_item is None:
            for it in book.get_items_of_type(ebooklib.ITEM_IMAGE):
                if "cover" in it.get_name().lower():
                    cover_item = it
                    break
        if cover_item is not None:
            cover_bytes = cover_item.get_content()
    except Exception:
        cover_bytes = None

    chapters: list[dict] = []

    # TOC 有序条目：(文档基础路径, 锚点|None, 标题)——Section 提供文档级标题，叶子提供锚点标题
    toc_entries: list[tuple[str, str | None, str]] = []

    def collect(items):
        for it in items:
            if isinstance(it, tuple):
                sec, children = it
                href = getattr(sec, "href", None)
                if href:
                    base, _, anchor = href.partition("#")
                    toc_entries.append(
                        (Path(base).as_posix().lstrip("./"), anchor or None, sec.title or "")
                    )
                collect(children)
            else:
                href = getattr(it, "href", None)
                if href:
                    base, _, anchor = href.partition("#")
                    toc_entries.append(
                        (Path(base).as_posix().lstrip("./"), anchor or None, it.title or "")
                    )

    try:
        collect(book.toc)
    except Exception:
        pass

    spine_docs = [book.get_item_with_id(idref) for idref, _linear in (book.spine or [])]
    # spine 缺失/异常时兜底：按文件顺序取全部文档
    spine_docs = [d for d in spine_docs if d is not None] or list(
        book.get_items_of_type(ebooklib.ITEM_DOCUMENT)
    )
    for item in spine_docs:
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        name = item.get_name()
        lname = name.lower()
        if lname in ("nav.xhtml", "toc.ncx") or "nav" in (getattr(item, "properties", None) or []):
            continue  # 跳过目录页文档
        if "cover" in Path(name).stem.lower():
            continue  # 封面页：书架卡片已展示封面，不作为章节

        body = b""
        try:
            body = item.get_body_content()
        except Exception:
            content = item.get_content() or b""
            m = re.search(rb"<body[^>]*>(.*)</body>", content, re.S | re.I)
            body = m.group(1) if m else content
        cleaned, heading = sanitize_html(body)
        text_len = len(re.sub(r"<[^>]+>", "", cleaned))
        if not text_len and not cleaned:
            continue

        base = Path(name).as_posix().lstrip("./")
        doc_entries = [(a, t) for (h, a, t) in toc_entries if h == base and a]
        doc_title = next(
            (t for (h, a, t) in toc_entries if h == base and not a and t),
            heading or Path(name).stem or f"第 {len(chapters) + 1} 节",
        )

        # 长文档且 TOC 提供锚点：按锚点拆成小章节（读起来才有章节感）
        segments = (
            _split_by_anchors(cleaned, doc_entries)
            if doc_entries and text_len > 4000
            else None
        )
        if segments:
            for seg_title, seg_html in segments:
                chapters.append({"title": (seg_title or doc_title).strip()[:120], "html": seg_html})
        else:
            chapters.append({"title": doc_title.strip()[:120], "html": cleaned or "<p></p>"})
    if not chapters:
        chapters = [{"title": meta_title or "正文", "html": "<p>（本书没有可解析的章节内容）</p>"}]
    return {"title": meta_title, "author": meta_author, "cover_bytes": cover_bytes, "chapters": chapters}


def save_cover(book_id: int, cover_bytes: bytes) -> str | None:
    """封面落盘 data/book_covers/，返回相对路径；内容为空返回 None。"""
    if not cover_bytes or len(cover_bytes) < 64:
        return None
    d = Path(settings.DATA_DIR) / data_dirs.BOOK_COVERS
    d.mkdir(parents=True, exist_ok=True)
    ext = ".png" if cover_bytes[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg"
    name = f"book_{book_id}_{hashlib.sha1(cover_bytes).hexdigest()[:10]}{ext}"
    (d / name).write_bytes(cover_bytes)
    return f"book_covers/{name}"


def epub_asset(path: Path, asset: str) -> bytes | None:
    """从 EPUB 内读取媒体资源（路径归一化后需精确/后缀匹配 zip 条目）。"""
    asset = asset.replace("\\", "/").lstrip("./")
    if ".." in asset.split("/"):
        return None
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            base = Path(path.name).parent.as_posix()
            candidates = [asset]
            if base and base != ".":
                candidates.append(f"{base}/{asset}")
            # 部分书籍 href 与 zip 目录大小写不一致，做一次不敏感匹配
            lowered = {n.lower(): n for n in names}

            def _read_limited(name: str) -> bytes | None:
                # 限长读取：恶意 EPUB 的单条目可解压出数十 GB，zf.read 会整体进内存
                with zf.open(name) as f:
                    data = f.read(MAX_EPUB_ASSET + 1)
                return data if len(data) <= MAX_EPUB_ASSET else None

            for cand in candidates:
                real = lowered.get(cand.lower())
                if real:
                    return _read_limited(real)
            tail = asset.rsplit("/", 1)[-1].lower()
            for n in names:
                if n.lower().endswith("/" + tail) or n.lower() == tail:
                    return _read_limited(n)
    except (zipfile.BadZipFile, OSError, KeyError):
        return None
    return None


# ---------------- 其他格式 ----------------

def parse_pdf(path: Path, fallback_title: str = "") -> dict:
    """PDF：不做重排阅读，只提取元数据；阅读页用内嵌 PDF 查看器打开原文件。"""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    # 扫描版/无 /Info 字典的 PDF：metadata 返回 None（不能用 or {}，{} 没有 .title 属性会炸）
    meta = reader.metadata
    title = (str(meta.title).strip() if meta and meta.title else "") or fallback_title or path.stem
    author = (str(meta.author).strip() if meta and meta.author else "")[:128]
    return {"title": title[:256], "author": author, "cover_bytes": None, "chapters": []}


def parse_fb2(path: Path) -> dict:
    """FB2（XML）：按 <title> 段落切章，提取内嵌封面（base64 binary）。"""
    import base64
    import xml.etree.ElementTree as ET

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    try:
        root = ET.parse(str(path)).getroot()
    except ET.ParseError:
        # 容错：个别文件命名空间前缀未声明（如 l:href），去掉 xmlns 声明后按无命名空间解析
        raw = path.read_text(encoding="utf-8", errors="replace")
        # 容错：未声明前缀的属性（如 l:href）——先去掉 xmlns 声明，再剥属性前缀
        raw = re.sub(r'\sxmlns(:\w+)?="[^"]*"', '', raw)
        raw = re.sub(r'\s(\w+):(\w+)=' , r' \2=', raw)
        root = ET.fromstring(raw)
    title = author = ""
    cover_bytes = None
    for desc in root.iter():
        if local(desc.tag) == "description":
            for el in desc.iter():
                t = local(el.tag)
                if t == "book-title" and el.text and not title:
                    title = el.text.strip()
                elif t == "first-name" and el.text:
                    author = el.text.strip()
                elif t == "last-name" and el.text:
                    author = (author + " " + el.text.strip()).strip()
                elif t == "coverpage":
                    for img in el.iter():
                        if local(img.tag) == "image":
                            href = next(
                                (v for k, v in img.attrib.items() if local(k) == "href"), ""
                            ).lstrip("#")
                            if href:
                                for bin_el in root.iter():
                                    if local(bin_el.tag) == "binary" and bin_el.attrib.get("id") == href:
                                        try:
                                            cover_bytes = base64.b64decode(bin_el.text or "")
                                        except Exception:
                                            cover_bytes = None
                                        break
                if title and author and cover_bytes:
                    break

    chapters = []
    for body in root.iter():
        if local(body.tag) != "body":
            continue
        cur_title, parts = None, []
        for el in body.iter():
            t = local(el.tag)
            if t == "title":
                ttext = " ".join(x.strip() for x in el.itertext() if x.strip())
                if ttext and cur_title is not None:
                    if parts:
                        chapters.append({"title": cur_title or f"第 {len(chapters) + 1} 节", "html": text_to_html(NL.join(parts))})
                        parts = []
                cur_title = ttext[:120]
            elif t == "p":
                text = "".join(x.strip() for x in el.itertext())
                if text:
                    parts.append(text)
        if parts:
            chapters.append({"title": cur_title or f"第 {len(chapters) + 1} 节", "html": text_to_html(NL.join(parts))})
        break  # 只取正文 body（第二个 body 是脚注）
    if not chapters:
        chapters = [{"title": title or "正文", "html": "<p>（本书没有可解析的章节内容）</p>"}]
    return {"title": title or path.stem, "author": author, "cover_bytes": cover_bytes, "chapters": chapters}


def parse_epub_fallback_html(html_path: Path, fallback_title: str) -> dict:
    """mobi 库解包出 HTML 产物（EPUB 生成失败时）的兜底解析。

    先按 <mbp:pagebreak> 切原始 HTML 再逐段清洗（清洗会剥掉该标记，所以必须先切）；
    单段过长再按 h1-h3 标题二次拆分；每段标题取段内首个短文本行，否则「第 N 节」。
    """
    raw = html_path.read_text(encoding="utf-8", errors="replace")
    chunks = [
        c for c in (x.strip() for x in re.split(r"<mbp:pagebreak[^>]*/?>", raw, flags=re.I))
        if re.sub(r"<[^>]+>", "", c).strip()
    ]
    if len(chunks) <= 1:
        cleaned, heading = sanitize_html(raw)
        chunks = split_by_headings(cleaned) if heading or cleaned else [raw]
    chapters = []
    for i, chunk in enumerate(chunks):
        seg_html, seg_heading = sanitize_html(chunk)
        if not re.sub(r"<[^>]+>", "", seg_html).strip():
            continue
        # 段内首个短段落（<40 字）视为章节标题
        first_p = re.search(r"<p[^>]*>(.*?)</p>", seg_html, re.S | re.I)
        title = ""
        if first_p:
            ptext = re.sub(r"<[^>]+>", "", first_p.group(1)).strip()
            if 0 < len(ptext) <= 40:
                title = ptext
        t = seg_heading or title or (f"第 {i + 1} 节" if len(chunks) > 1 else "正文")
        chapters.append({"title": t[:120], "html": seg_html})
    if not chapters:
        chapters = [{"title": fallback_title or "正文", "html": f"<p>{html_mod.escape(fallback_title)}</p>"}]
    return {"title": fallback_title, "author": "", "cover_bytes": None, "chapters": chapters}


def split_by_headings(html: str, min_chars: int = 6000) -> list[str]:
    """无结构的整本 HTML 按 h1-h3 标题边界拆分（返回原始 HTML 片段列表）；
    标题太少或正文过短时返回单块。"""
    marks = [
        (m.start(), re.sub(r"<[^>]+>", "", m.group(0)).strip()[:120])
        for m in re.finditer(r"<h[1-3][^>]*>.*?</h[1-3]>", html, flags=re.S | re.I)
    ]
    if len(marks) < 2:
        return [html]
    positions = [pos for pos, _ in marks]
    head = html[: positions[0]].strip()
    segments = []
    if re.sub(r"<[^>]+>", "", head).strip():
        segments.append(head)
    for i, pos in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(html)
        seg = html[pos:end].strip()
        if seg:
            segments.append(seg)
    return segments if len(segments) >= 2 else [html]


def parse_mobi(path: Path, fallback_title: str = "") -> dict:
    """MOBI/AZW3：mobi 库自动转换（临时目录优先 EPUB，其次 HTML），再走对应解析。"""
    import tempfile

    from mobi import extract

    tmp, out = extract(str(path))  # 返回 (临时目录, 产物路径)：EPUB 优先，退回 HTML
    try:
        out_path = Path(out)
        if out_path.suffix.lower() == ".epub":
            result = parse_epub(out_path)
        else:
            result = parse_epub_fallback_html(out_path, fallback_title or path.stem)
        if not result["title"]:
            result["title"] = fallback_title or path.stem
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
