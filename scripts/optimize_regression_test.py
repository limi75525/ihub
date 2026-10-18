"""iHub 优化专项回归：无需第三方依赖（标准库 urllib + zipfile），针对本机运行中的实例。

用法（与冒烟测试相同，先起临时实例）：
    IHUB_DATA_DIR=./.smoke-data IHUB_SECRET_KEY=smoketest \
        .venv/Scripts/python -m uvicorn app.main:app --port 18766
    .venv/Scripts/python scripts/optimize_regression_test.py http://127.0.0.1:18766

覆盖：
  1. 书架排序：在读的书排最前（按进度更新时间），未读按入库时间倒序在后
  2. 文件库目录：mkdir -p 建目录 / 目录过滤 / 分片上传进目录 / 批量移动 /
     重命名级联（子孙目录+文件） / 空目录才能删 / 路径归一化与越权
  3. 头像库导出→导入 round-trip：库图引用（.jpeg/.gif 后缀）随包导出并可完整导回
"""
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from io import BytesIO

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18766").rstrip("/")

passed = failed = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  [ok]   {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} {detail}")


def call(method: str, path: str, body=None, token: str | None = None, raw_body: bytes | None = None,
         content_type: str | None = None):
    """返回 (status, 解析后的 JSON 或 bytes)"""
    data = raw_body if raw_body is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", content_type or "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            payload = resp.read()
            status = resp.status
    except urllib.error.HTTPError as e:
        payload = e.read()
        status = e.code
    try:
        return status, json.loads(payload.decode())
    except (ValueError, UnicodeDecodeError):
        return status, payload


def register(username: str):
    st, body = call("POST", "/api/v1/auth/register", {"username": username, "password": "reg-pass-123"})
    assert st == 200, f"register {username} failed: {st} {body}"
    return body["access_token"], body.get("media_key", "")


def chunked_upload(token: str, name: str, content: bytes, origin: str = "library", dir_path: str | None = None):
    """走分片管道上传一个文件，返回 finish 响应条目。"""
    body = {"name": name, "size": len(content), "origin": origin}
    if dir_path is not None:
        body["dir"] = dir_path
    st, r = call("POST", "/api/v1/transfer/upload/init", body, token=token)
    assert st == 200, f"upload init failed: {st} {r}"
    uid = r["uploadId"]
    chunk = r.get("chunkSize") or 4 * 1024 * 1024
    i, off = 0, 0
    while off < len(content) or i == 0:
        st, r2 = call("PUT", f"/api/v1/transfer/upload/{uid}/chunk/{i}", raw_body=content[off:off + chunk],
                      token=token, content_type="application/octet-stream")
        assert st == 200, f"chunk {i} failed: {st} {r2}"
        off += chunk
        i += 1
        if off >= len(content):
            break
    st, r3 = call("POST", f"/api/v1/transfer/upload/{uid}/finish", token=token)
    assert st == 200, f"finish failed: {st} {r3}"
    return r3["item"]


def multipart_file(field: str, filename: str, content: bytes, ctype: str) -> tuple[bytes, str]:
    b = "----IHubRegressionBoundary"
    body = (
        f"--{b}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode() + content + f"\r\n--{b}--\r\n".encode()
    return body, f"multipart/form-data; boundary={b}"


def main() -> int:
    suffix = str(int(time.time()))

    print("== 1. 书架排序（在读优先）==")
    token, media_key = register(f"bk{suffix}")
    # 两本小 TXT：A 先入库、B 后入库（默认列表 B 在前）
    ta = f"书甲{suffix}".encode() + b" " + b"alpha " * 200
    tb = f"书乙{suffix}".encode() + b" " + b"beta " * 200
    item_a = chunked_upload(token, f"booka{suffix}.txt", ta)
    book_a = call("POST", "/api/v1/books/import", {"item_id": item_a["id"]}, token=token)[1]
    item_b = chunked_upload(token, f"bookb{suffix}.txt", tb)
    book_b = call("POST", "/api/v1/books/import", {"item_id": item_b["id"]}, token=token)[1]
    check("两本书导入成功", book_a.get("id") and book_b.get("id"), f"{book_a} {book_b}")
    st, books = call("GET", "/api/v1/books", token=token)
    check("默认排序：后入库的在前", [b["id"] for b in books] == [book_b["id"], book_a["id"]], str([b["id"] for b in books]))
    # 读旧书 A → A 排第一；再读新书 B → B 排第一（最近在读优先）
    call("PUT", f"/api/v1/books/{book_a['id']}/progress", {"chapter_idx": 0, "frac": 0.5}, token=token)
    time.sleep(0.05)
    _, books = call("GET", "/api/v1/books", token=token)
    check("读旧书后旧书排第一", books[0]["id"] == book_a["id"], str([b["id"] for b in books]))
    time.sleep(0.6)
    call("PUT", f"/api/v1/books/{book_b['id']}/progress", {"chapter_idx": 0, "frac": 0.2}, token=token)
    _, books = call("GET", "/api/v1/books", token=token)
    check("最近在读的书排第一", books[0]["id"] == book_b["id"], str([b["id"] for b in books]))

    print("== 2. 文件库目录 ==")
    token2, media_key2 = register(f"lib{suffix}")
    st, r = call("POST", "/api/v1/transfer/dirs", {"path": "photos/2024"}, token=token2)
    check("mkdir -p 建嵌套目录", st == 200 and len(r.get("created", [])) == 2, f"{st} {r}")
    st, r = call("GET", "/api/v1/transfer/dirs", token=token2)
    paths = [d["path"] for d in r["items"]]
    check("目录列表含两级", set(paths) == {"photos", "photos/2024"}, str(paths))
    st, r = call("POST", "/api/v1/transfer/dirs", {"path": "photos/2024/"}, token=token2)
    st, r = call("GET", "/api/v1/transfer/dirs", token=token2)
    check("重复创建幂等（路径归一化）", len(r["items"]) == 2, str([d["path"] for d in r["items"]]))
    st, _ = call("POST", "/api/v1/transfer/dirs", {"path": "../evil"}, token=token2)
    check("拒绝 .. 目录", st == 400, f"status={st}")
    st, _ = call("POST", "/api/v1/transfer/dirs", {"path": "a//b/./c"}, token=token2)
    check("归一化 a//b/./c 接受", st == 200, f"status={st}")
    st, r = call("GET", "/api/v1/transfer/dirs", token=token2)
    check("归一化后为 a/b/c", "a/b/c" in [d["path"] for d in r["items"]], str([d["path"] for d in r["items"]]))

    # 上传进目录 / 根目录
    sub_item = chunked_upload(token2, "in-sub.jpg", b"\xff\xd8\xffsub-jpeg-data", dir_path="photos/2024")
    check("分片上传带 dir 落到子目录", sub_item.get("dir_path") == "photos/2024", str(sub_item))
    root_item = chunked_upload(token2, "in-root.jpg", b"\xff\xd8\xffroot-jpeg-data")
    check("缺省上传到根目录", root_item.get("dir_path") == "", str(root_item))
    st, _ = call("POST", "/api/v1/transfer/upload/init", {"name": "x.jpg", "size": 10, "origin": "library", "dir": "nope"}, token=token2)
    check("上传到不存在目录被拒", st == 404, f"status={st}")

    st, r = call("GET", "/api/v1/transfer?limit=200&dir=%2F", token=token2)
    check("dir=/ 只看根目录", [i["id"] for i in r["items"]] == [root_item["id"]], str([i["id"] for i in r["items"]]))
    st, r = call("GET", "/api/v1/transfer?limit=200&dir=photos%2F2024", token=token2)
    check("dir=子目录 只看子目录", [i["id"] for i in r["items"]] == [sub_item["id"]], str([i["id"] for i in r["items"]]))
    st, r = call("GET", "/api/v1/transfer?limit=200", token=token2)
    check("不带 dir 返回全部（旧客户端兼容）", len(r["items"]) == 2, str(len(r["items"])))

    # 批量移动
    st, r = call("POST", "/api/v1/transfer/move", {"ids": [root_item["id"]], "dir": "photos"}, token=token2)
    check("批量移动到目录", st == 200 and r.get("moved") == 1, f"{st} {r}")
    st, r = call("GET", "/api/v1/transfer?limit=200&dir=photos", token=token2)
    check("移动后目录过滤可见", [i["id"] for i in r["items"]] == [root_item["id"]], str(r))
    st, r = call("POST", "/api/v1/transfer/move", {"ids": [root_item["id"]], "dir": "nope"}, token=token2)
    check("移动到不存在目录被拒", st == 404, f"status={st}")
    # 越权：他人目录不可见/不可移动
    st, _ = call("POST", "/api/v1/transfer/move", {"ids": [root_item["id"]], "dir": "photos"}, token=token)
    check("越权移动到他人目录被拒（目录不存在）", st == 404, f"status={st}")

    # 重命名级联：photos → pics（子孙目录与文件前缀同步）
    st, r = call("GET", "/api/v1/transfer/dirs", token=token2)
    photos_id = next(d["id"] for d in r["items"] if d["path"] == "photos")
    st, r = call("PATCH", f"/api/v1/transfer/dirs/{photos_id}", {"name": "pics"}, token=token2)
    check("重命名目录成功", st == 200 and r.get("path") == "pics", f"{st} {r}")
    st, r = call("GET", "/api/v1/transfer/dirs", token=token2)
    check("子孙目录前缀级联", "pics/2024" in [d["path"] for d in r["items"]], str([d["path"] for d in r["items"]]))
    st, r = call("GET", "/api/v1/transfer?limit=200&dir=pics", token=token2)
    check("目录内文件随重命名迁移", [i["id"] for i in r["items"]] == [root_item["id"]], str(r))
    st, r = call("GET", "/api/v1/transfer?limit=200&dir=pics%2F2024", token=token2)
    check("子目录内文件不受影响", [i["id"] for i in r["items"]] == [sub_item["id"]], str(r))

    # 删除规则：仅空目录可删
    st, r = call("GET", "/api/v1/transfer/dirs", token=token2)
    by_path = {d["path"]: d["id"] for d in r["items"]}
    st, _ = call("DELETE", f"/api/v1/transfer/dirs/{by_path['pics']}", token=token2)
    check("含子目录的目录不可删", st == 400, f"status={st}")
    st, _ = call("DELETE", f"/api/v1/transfer/dirs/{by_path['pics/2024']}", token=token2)
    check("含文件的目录不可删", st == 400, f"status={st}")
    call("DELETE", f"/api/v1/transfer/{sub_item['id']}", token=token2)
    st, _ = call("DELETE", f"/api/v1/transfer/dirs/{by_path['pics/2024']}", token=token2)
    check("清空文件后子目录可删", st == 200, f"status={st}")
    st, _ = call("DELETE", f"/api/v1/transfer/dirs/{by_path['pics']}", token=token2)
    check("仍含文件的父目录仍不可删", st == 400, f"status={st}")

    print("== 3. 头像库导出→导入 round-trip ==")
    # 库图引用两张：.jpeg（分组默认头像）与 .gif（规则精确头像）——历史上导入白名单漏掉这两个后缀
    g_item = chunked_upload(token2, "cover.jpeg", b"\xff\xd8\xfffake-jpeg-bytes")
    r_item = chunked_upload(token2, "sticker.gif", b"GIF89afake-gif-bytes")
    st, g = call("POST", "/api/v1/logos/groups", {"name": f"回归企业{suffix}", "library_file_id": g_item["id"]}, token=token2)
    check("建分组并引用库图", st in (200, 201) and g.get("logo_kind") == "file", f"{st} {g}")
    gid = g["id"]
    st, rule = call("POST", f"/api/v1/logos/groups/{gid}/rules",
                    {"signature": "回归签名", "account": "13800001234", "library_file_id": r_item["id"]}, token=token2)
    check("建规则并引用 gif 库图", st in (200, 201) and rule.get("logo_kind") == "file", f"{st} {rule}")
    rid = rule["id"]

    st, zbytes = call("GET", "/api/v1/logos/export", token=token2)
    check("导出 ZIP", st == 200 and zbytes[:2] == b"PK", f"status={st}")
    zf = zipfile.ZipFile(BytesIO(zbytes))
    names = zf.namelist()
    check("导出包含 manifest.json", "manifest.json" in names, str(names))
    check("导出包含 .jpeg 分组图（历史 bug：导入白名单曾漏 .jpeg）",
          any(n.startswith("images/group_") and n.endswith(".jpeg") for n in names), str(names))
    check("导出包含 .gif 规则图（历史 bug：导入白名单曾漏 .gif）",
          any(n.startswith("images/rule_") and n.endswith(".gif") for n in names), str(names))
    manifest = json.loads(zf.read("manifest.json"))
    check("manifest 为 v2 且含规则", manifest.get("version") == 2 and manifest["groups"][0]["rules"], str(manifest)[:200])

    # 删除分组（回收站开启 → 软删，不阻塞同名导入）后整包导回
    call("DELETE", f"/api/v1/logos/groups/{gid}", token=token2)
    up_body, up_ct = multipart_file("file", "ihub-avatars.zip", zbytes, "application/zip")
    st, r = call("POST", "/api/v1/logos/import", raw_body=up_body, token=token2, content_type=up_ct)
    check("整包导入成功", st == 200 and len(r.get("created", [])) == 1 and not r.get("skipped"), f"{st} {json.dumps(r)[:300]}")
    if r.get("created"):
        ng = r["created"][0]
        st2, logo_resp = call("GET", f"/api/v1/logos/groups/{ng['id']}/logo-file?token={media_key2}")
        check("导入后分组默认头像可读（.jpeg 落盘）", st2 == 200 and bytes(logo_resp) == b"\xff\xd8\xfffake-jpeg-bytes", f"status={st2}")
        nrules = ng.get("rules") or []
        ok_rule = False
        if nrules:
            st3, rlogo = call("GET", f"/api/v1/logos/rules/{nrules[0]['id']}/logo-file?token={media_key2}")
            ok_rule = st3 == 200 and bytes(rlogo) == b"GIF89afake-gif-bytes"
        check("导入后规则精确头像可读（.gif 落盘）", ok_rule, str(nrules))

    # 纯 JSON（v1 外链）导入仍可用
    v1 = json.dumps({"rules": [{"signature": "旧版企业", "phone": "12345", "logo_url": "https://a.favicon.im/x"}]}).encode()
    up_body, up_ct = multipart_file("file", "old.json", v1, "application/json")
    st, r = call("POST", "/api/v1/logos/import", raw_body=up_body, token=token2, content_type=up_ct)
    check("v1 纯 JSON 导入兼容", st == 200 and len(r.get("created", [])) == 1, f"{st} {json.dumps(r)[:200]}")

    print(f"\n通过 {passed} 项，失败 {failed} 项")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
