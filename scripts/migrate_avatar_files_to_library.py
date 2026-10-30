"""头像库 → 文件库 迁移 + Excel 清单导出（一次性运维脚本，可在本地与 NAS 容器内运行）。

做两件事：
1. 把头像库自带的 Logo 文件（data/logos/ 下的上传/缓存文件）复制进所属用户的文件库
   （data/transfer/<uid>/ + transfer_items 行，kind=image），并把分组/规则的 logo_path
   改为指向文件库副本（与「从文件库选择」同语义，引用而非重复存储）；
2. 生成 Excel（.xlsx）清单：企业名称 / 短信号码 / 邮箱地址 / 昵称 / 在线 Logo 地址 / Logo 文件名。

兼容新旧两代表结构：
- 新：logo_groups + logo_rules(group_id, signature, account)；
- 旧：logo_rules(phone, signature, email, nickname) 单表。
已在文件库中的引用（logo_path 以 transfer/ 开头）不重复迁移。

用法（NAS 容器内）：docker exec ihub python scripts/migrate_avatar_files_to_library.py
可选：--out <路径> 指定 Excel 输出位置（默认 <DATA_DIR>/头像库清单-<时间戳>.xlsx）。
"""

import argparse
import mimetypes
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DATA_DIR = None  # 启动时由 app 配置注入


def _log(msg: str) -> None:
    print(msg, flush=True)


# ---------------- xlsx 生成（零依赖：zip + 内联字符串） ----------------

_XLSX_HEADER_STYLE = 1  # styles.xml 中加粗字体


def _col_letter(idx: int) -> str:
    # 1 -> A, 2 -> B ...（清单列数远小于 26 的倍数层级，简单实现足够）
    s = ""
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def _xml_escape(v: str) -> str:
    return (
        v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def write_xlsx(path: Path, header: list[str], rows: list[list[str]]) -> None:
    import zipfile

    cells_xml = []
    for r_idx, row in enumerate([header] + rows, start=1):
        cells = []
        for c_idx, val in enumerate(row, start=1):
            ref = f"{_col_letter(c_idx)}{r_idx}"
            style = ' s="1"' if r_idx == 1 else ""
            cells.append(
                f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{_xml_escape(str(val))}</t></is></c>'
            )
        cells_xml.append(f'<row r="{r_idx}">{"".join(cells)}</row>')

    sheet1 = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(cells_xml)}</sheetData>"
        '<cols><col min="1" max="1" width="24" customWidth="1"/>'
        '<col min="2" max="5" width="28" customWidth="1"/></cols>'
        "</worksheet>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="头像库清单" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels_root = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    rels_workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        "</Types>"
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
        '<cellXfs count="2"><xf fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
        "</styleSheet>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels_root)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", rels_workbook)
        zf.writestr("xl/worksheets/sheet1.xml", sheet1)
        zf.writestr("xl/styles.xml", styles)


# ---------------- 迁移逻辑 ----------------

_EXT_CONTENT_TYPE = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
}


def _guess_content_type(path: Path) -> str:
    return _EXT_CONTENT_TYPE.get(path.suffix.lower()) or (mimetypes.guess_type(str(path))[0] or "application/octet-stream")


def _owned_logo_file(rel: str | None) -> Path | None:
    """头像库自有文件（data/logos/ 下）才需要迁移；文件库引用（transfer/）与外链不动。"""
    if not rel:
        return None
    rel = rel.replace("\\", "/")
    if not rel.startswith("logos/"):
        return None
    p = (Path(DATA_DIR) / rel).resolve()
    try:
        p.relative_to(Path(DATA_DIR).resolve())
    except ValueError:
        return None
    return p if p.is_file() else None


def _into_library(cur, uid: int, src: Path) -> str:
    """把 src 复制进用户文件库（同内容同名去重），返回新的相对路径。"""
    target_rel = f"transfer/{uid}/{src.name}"
    target = Path(DATA_DIR) / target_rel
    row = cur.execute(
        "SELECT id FROM transfer_items WHERE user_id=? AND file_path=?", (uid, target_rel)
    ).fetchone()
    if row is None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(src, target)
        cur.execute(
            "INSERT INTO transfer_items (user_id, kind, content, file_name, file_size, content_type, file_path, created_at) "
            "VALUES (?, 'image', '', ?, ?, ?, ?, ?)",
            (
                uid,
                src.name,
                src.stat().st_size,
                _guess_content_type(src),
                target_rel,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "+00:00",
            ),
        )
        _log(f"  已迁入文件库：{src.name}（用户 {uid}）")
    else:
        _log(f"  文件库已存在同名副本，跳过复制：{src.name}")
    return target_rel


def main() -> int:
    global DATA_DIR
    ap = argparse.ArgumentParser(description="头像库 Logo 文件迁入文件库 + Excel 清单")
    ap.add_argument("--out", default="", help="Excel 输出路径（默认 <DATA_DIR>/头像库清单-<时间戳>.xlsx）")
    ap.add_argument("--dry-run", action="store_true", help="只生成清单，不迁移文件")
    args = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.core.config import settings

    DATA_DIR = Path(settings.DATA_DIR)
    db_path = DATA_DIR / "ihub.db"
    if not db_path.exists():
        _log(f"未找到数据库：{db_path}")
        return 1
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cols = {r[1] for r in cur.execute("PRAGMA table_info(logo_rules)").fetchall()}
    new_schema = "account" in cols
    _log(f"数据库：{db_path}（{'新版分组结构' if new_schema else '旧版单表结构'}）")

    rows_out: list[list[str]] = []  # Excel 数据行
    moved = 0

    if new_schema:
        groups = {
            g["id"]: g
            for g in cur.execute(
                "SELECT * FROM logo_groups WHERE is_deleted=0"
            ).fetchall()
        }
        rules = cur.execute("SELECT * FROM logo_rules WHERE is_deleted=0").fetchall()
        rules_by_group: dict[int, list] = {}
        for r in rules:
            rules_by_group.setdefault(r["group_id"], []).append(r)

        for gid, g in groups.items():
            uid = g["user_id"]
            g_name = (g["name"] or "").replace(f"~del{gid}", "")
            g_logo_url = g["logo_url"]
            g_logo_path = g["logo_path"]
            # 分组默认头像文件 → 文件库
            src = _owned_logo_file(g_logo_path)
            new_path = None
            if src is not None:
                new_path = None if args.dry_run else _into_library(cur, uid, src)
                moved += 1
                if not args.dry_run and new_path:
                    cur.execute("UPDATE logo_groups SET logo_path=? WHERE id=?", (new_path, gid))
            rules = rules_by_group.get(gid, [])
            if not rules:
                rows_out.append([g_name, "", "", "", g_logo_url or "", Path(g_logo_path or "").name])
            for r in rules:
                sig, acct = r["signature"] or "", r["account"] or ""
                phone = "" if "@" in acct else acct
                email = acct if "@" in acct else ""
                r_src = _owned_logo_file(r["logo_path"])
                r_new = None
                if r_src is not None:
                    r_new = None if args.dry_run else _into_library(cur, r["user_id"], r_src)
                    moved += 1
                    if not args.dry_run and r_new:
                        cur.execute("UPDATE logo_rules SET logo_path=? WHERE id=?", (r_new, r["id"]))
                # 头像归属：规则精确头像优先，否则企业默认
                online = (r["logo_url"] or g_logo_url or "") if not (r["logo_path"] or g_logo_path or r_new) else (r["logo_url"] or "")
                logo_rel = r_new or r["logo_path"] or g_logo_path or ""
                rows_out.append([g_name, phone, email, sig, online, Path(logo_rel).name if logo_rel else ""])
    else:
        for r in cur.execute("SELECT * FROM logo_rules WHERE is_deleted=0").fetchall():
            uid = r["user_id"]
            name = (r["signature"] or r["nickname"] or r["phone"] or r["email"] or "未命名").strip()
            src = _owned_logo_file(r["logo_path"])
            new_path = None
            if src is not None:
                new_path = None if args.dry_run else _into_library(cur, uid, src)
                moved += 1
                if not args.dry_run and new_path:
                    cur.execute("UPDATE logo_rules SET logo_path=? WHERE id=?", (new_path, r["id"]))
            logo_rel = new_path or r["logo_path"] or ""
            rows_out.append(
                [
                    name,
                    r["phone"] or "",
                    r["email"] or "",
                    r["nickname"] or "",
                    r["logo_url"] or "",
                    Path(logo_rel).name if logo_rel else "",
                ]
            )

    con.commit()
    _log(f"迁移完成：共处理 {moved} 个 Logo 文件" + ("（dry-run 未实际写入）" if args.dry_run else ""))

    out = Path(args.out) if args.out else DATA_DIR / f"头像库清单-{datetime.now().strftime('%Y%m%d-%H%M')}.xlsx"
    write_xlsx(out, ["企业名称", "短信号码", "邮箱地址", "昵称/显示名", "在线Logo地址", "Logo文件（文件库）"], rows_out)
    _log(f"Excel 清单已生成：{out.resolve()}（{len(rows_out)} 条）")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
