import secrets
import shutil
import json as jsonlib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.fsutil import data_file, safe_mtime_ns
from app.core.sqlutil import like_prefix
from app.core.timeutil import as_utc
from app.core.deps import get_current_user, get_media_user
from app.db.session import get_db
from app.models.logo_rule import LogoRule
from app.models.transfer_dir import TransferDir
from app.models.transfer_item import TransferItem
from app.models.user import User

router = APIRouter(prefix="/transfer", tags=["transfer"])

MAX_TEXT_LEN = 10_000
from app.models.system_setting import get_int_setting
from app.core import data_dirs

ATTACH_MIN_MB, ATTACH_MAX_MB = 1, 2048


def max_file_size() -> int:
    """单附件大小上限（MB），可在 设置 → 系统 → 附件上传限制 配置。
    同时约束文件快传与文件库上传（同一条上传管道）。"""
    return get_int_setting("transfer_max_mb", 512, ATTACH_MIN_MB, ATTACH_MAX_MB) * 1024 * 1024
MAX_BATCH_FILES = 20
CHUNK_SIZE = 4 * 1024 * 1024  # 分片 4MB：绕开反代请求体限制，失败只需重传单片
# 半成品分片的空闲保留时间（按目录 mtime 计空闲时长；正在上传的目录 mtime 持续刷新不会误清）。
# TTL 不能太长：失败/中断的上传会占住「单用户 10 会话」名额，用户重试只会一直 429。
UPLOAD_TTL = 2 * 3600


def _upload_tmp_root() -> Path:
    d = Path(settings.DATA_DIR) / data_dirs.TMP
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cleanup_stale_uploads() -> None:
    """清理超过 TTL 的半成品分片目录（每次 init 时低频触发）。"""
    import time

    root = _upload_tmp_root()
    now = time.time()
    try:
        for d in root.iterdir():
            if d.is_dir() and now - d.stat().st_mtime > UPLOAD_TTL:
                for f in d.iterdir():
                    f.unlink(missing_ok=True)
                d.rmdir()
    except OSError:
        pass


def _item_out(t: TransferItem) -> dict:
    out = {
        "id": t.id,
        "kind": t.kind,
        "content": t.content,
        "file_name": t.file_name,
        "file_size": t.file_size,
        "content_type": t.content_type,
        "origin": t.origin or "share",
        "dir_path": t.dir_path or "",
        "created_at": as_utc(t.created_at).isoformat(),
    }
    if t.kind in ("file", "image"):
        # URL 带纳秒 mtime 版本号：transfer_items 无 AUTOINCREMENT，删除最大 id 行后新上传会
        # 复用同一 id，同一 URL 先后挂过两个文件——版本号让内容替换后 URL 随之变化，浏览器
        # 不再用旧缓存的图（缩略图/预览显示上一个文件的串图，下载绕过缓存反而正确）。
        v = safe_mtime_ns(Path(settings.DATA_DIR) / t.file_path) if t.file_path else 0
        out["url"] = f"/api/v1/transfer/{t.id}/file?v={v}"
    return out


def _own_item(db: Session, user: User, item_id: int) -> TransferItem:
    t = db.query(TransferItem).filter(TransferItem.id == item_id, TransferItem.user_id == user.id).first()
    if not t:
        raise HTTPException(404, "快传条目不存在")
    return t


def _safe_remove(rel_path: str):
    path = data_dirs.resolve_rel(rel_path)
    if path and path.is_file():
        path.unlink(missing_ok=True)


# ---------------- 文件库目录（逻辑目录：物理存储始终平铺在 transfer/<uid>/） ----------------

DIR_SEG_MAX = 64        # 单级目录名长度
DIR_PATH_MAX = 256      # 整条路径长度（与 dir_path 列宽一致）
DIR_MAX_DEPTH = 8       # 目录嵌套层数
MAX_DIRS_PER_USER = 200  # 每用户目录数上限（与 nav 200 同思路）


def _norm_dir_path(v: str | None) -> str:
    """归一化目录路径：'a//b/' → 'a/b'；根目录返回 ''；拒绝 .. 与空段。"""
    segs: list[str] = []
    for seg in str(v or "").replace("\\", "/").split("/"):
        seg = seg.strip()
        if not seg or seg == ".":
            continue
        if seg == "..":
            raise HTTPException(400, "目录名不合法")
        if len(seg) > DIR_SEG_MAX:
            raise HTTPException(400, f"目录名过长（最多 {DIR_SEG_MAX} 字符）")
        segs.append(seg)
    if len(segs) > DIR_MAX_DEPTH:
        raise HTTPException(400, f"目录层级最多 {DIR_MAX_DEPTH} 层")
    path = "/".join(segs)
    if len(path) > DIR_PATH_MAX:
        raise HTTPException(400, "目录路径过长")
    return path


def _user_dir_count(db: Session, user_id: int) -> int:
    return db.query(TransferDir.id).filter(TransferDir.user_id == user_id).count()


def _get_dir(db: Session, user: User, path: str) -> TransferDir | None:
    if not path:
        return None
    return (
        db.query(TransferDir)
        .filter(TransferDir.user_id == user.id, TransferDir.path == path)
        .first()
    )


def _own_dir(db: Session, user: User, dir_id: int) -> TransferDir:
    d = db.get(TransferDir, dir_id)
    if not d or d.user_id != user.id:
        raise HTTPException(404, "目录不存在")
    return d


def _dir_out(d: TransferDir) -> dict:
    segs = d.path.split("/")
    return {"id": d.id, "path": d.path, "name": segs[-1], "depth": len(segs) - 1}


@router.get("/dirs")
def list_dirs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """目录列表（含空目录），按路径排序供前端按父子关系展示。
    附带 file_count/dir_count（含子目录累计），供中/大视图卡片展示。"""
    rows = (
        db.query(TransferDir)
        .filter(TransferDir.user_id == user.id)
        .order_by(TransferDir.path.asc())
        .all()
    )
    from sqlalchemy import func

    file_groups = (
        db.query(TransferItem.dir_path, func.count(TransferItem.id))
        .filter(
            TransferItem.user_id == user.id,
            TransferItem.kind.in_(("file", "image")),
        )
        .group_by(TransferItem.dir_path)
        .all()
    )
    file_counts: dict[str, int] = {p or "": int(n) for p, n in file_groups}
    all_paths = [d.path for d in rows]

    def _stats(path: str) -> tuple[int, int]:
        files = sum(n for p, n in file_counts.items() if p == path or p.startswith(path + "/"))
        subdirs = sum(1 for p in all_paths if p != path and p.startswith(path + "/"))
        return files, subdirs

    out = []
    for d in rows:
        item = _dir_out(d)
        item["file_count"], item["dir_count"] = _stats(d.path)
        out.append(item)
    return {"items": out}


class DirCreate(BaseModel):
    path: str


@router.post("/dirs")
def create_dir(body: DirCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """新建目录（mkdir -p 语义：缺失的父目录一并创建）。"""
    path = _norm_dir_path(body.path)
    if not path:
        raise HTTPException(400, "目录名不能为空")
    segs = path.split("/")
    if _user_dir_count(db, user.id) >= MAX_DIRS_PER_USER:
        raise HTTPException(400, f"目录数量已达上限（{MAX_DIRS_PER_USER} 个）")
    created: list[TransferDir] = []
    for i in range(1, len(segs) + 1):
        prefix = "/".join(segs[:i])
        if _get_dir(db, user, prefix):
            continue
        d = TransferDir(user_id=user.id, path=prefix)
        db.add(d)
        created.append(d)
    db.commit()
    return {"ok": True, "created": [_dir_out(d) for d in created]}


class DirRename(BaseModel):
    name: str


@router.patch("/dirs/{dir_id}")
def rename_dir(dir_id: int, body: DirRename, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """重命名目录（仅最后一级）：子孙目录与目录内文件的路径前缀同步更新。"""
    d = _own_dir(db, user, dir_id)
    name = _norm_dir_path(body.name)
    if not name or "/" in name:
        raise HTTPException(400, "目录名不合法")
    parent = d.path.rsplit("/", 1)[0] if "/" in d.path else ""
    new_path = f"{parent}/{name}" if parent else name
    if new_path == d.path:
        return {"ok": True}
    if _get_dir(db, user, new_path):
        raise HTTPException(409, "同名目录已存在")
    old = d.path
    d.path = new_path
    # 子孙目录与目录内文件同步改前缀（前缀匹配：path == old 或 old 开头）
    like = like_prefix(old + "/")
    for row in (
        db.query(TransferDir)
        .filter(
            TransferDir.user_id == user.id,
            TransferDir.path != old,
            TransferDir.path.like(like, escape="\\"),
        )
        .all()
    ):
        row.path = new_path + row.path[len(old):]
    for row in (
        db.query(TransferItem)
        .filter(
            TransferItem.user_id == user.id,
            # 目录内的文件 = dir_path 恰好等于旧路径，或位于其子路径下
            or_(
                TransferItem.dir_path == old,
                TransferItem.dir_path.like(like, escape="\\"),
            ),
        )
        .all()
    ):
        row.dir_path = new_path + row.dir_path[len(old):]
    db.commit()
    return {"ok": True, "path": new_path}


@router.delete("/dirs/{dir_id}")
def delete_dir(dir_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """删除目录：仅允许删除空目录（无子目录且无文件），文件需先移走或删除。"""
    d = _own_dir(db, user, dir_id)
    has_sub = (
        db.query(TransferDir.id)
        .filter(
            TransferDir.user_id == user.id,
            TransferDir.path.like(like_prefix(d.path + "/"), escape="\\"),
        )
        .first()
    )
    if has_sub:
        raise HTTPException(400, "目录下还有子目录，请先删除子目录")
    has_file = (
        db.query(TransferItem.id)
        .filter(TransferItem.user_id == user.id, TransferItem.dir_path == d.path)
        .first()
    )
    if has_file:
        raise HTTPException(400, "目录内还有文件，请先移走或删除")
    db.delete(d)
    db.commit()
    return {"ok": True}


class MoveIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)
    dir: str = ""


@router.post("/move")
def move_items(body: MoveIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """批量移动文件到目录（dir="" 移回根目录）。仅文件/图片参与（文本条目无目录概念）。"""
    target = _norm_dir_path(body.dir)
    if target and not _get_dir(db, user, target):
        raise HTTPException(404, "目录不存在")
    rows = (
        db.query(TransferItem)
        .filter(
            TransferItem.id.in_(body.ids),
            TransferItem.user_id == user.id,
            TransferItem.kind.in_(("file", "image")),
        )
        .all()
    )
    moved = 0
    for t in rows:
        if t.dir_path != target:
            t.dir_path = target
            moved += 1
    db.commit()
    return {"ok": True, "moved": moved}


@router.get("")
def list_items(
    limit: int = 100,
    origin: str = "",
    dir: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """文件列表。dir 过滤：缺省/空 = 全部（旧客户端兼容）；"/" = 根目录；否则为目录路径。
    搜索场景传 dir="" 即可跨目录检索。"""
    limit = max(1, min(limit, 200))
    q = db.query(TransferItem).filter(TransferItem.user_id == user.id)
    # origin 过滤：share=快传卡只看快传来源，library=文件库；不传则全部返回（旧客户端兼容）
    if origin in ("share", "library"):
        q = q.filter(TransferItem.origin == origin)
    if dir:
        path = "" if dir == "/" else _norm_dir_path(dir)
        if path and not _get_dir(db, user, path):
            raise HTTPException(404, "目录不存在")
        q = q.filter(TransferItem.dir_path == path)
    rows = (
        q.order_by(TransferItem.created_at.desc(), TransferItem.id.desc())
        .limit(limit)
        .all()
    )
    return {"items": [_item_out(t) for t in rows]}


@router.post("/text")
def send_text(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    content = (body or {}).get("content", "")
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(400, "内容不能为空")
    if len(content) > MAX_TEXT_LEN:
        raise HTTPException(400, f"文本过长，最多 {MAX_TEXT_LEN} 字符")
    t = TransferItem(user_id=user.id, kind="text", content=content)
    db.add(t)
    db.commit()
    return {"ok": True, "item": _item_out(t)}


def _safe_suffix(name: str | None) -> str:
    """从文件名提取扩展名，白名单校验。

    Windows 上 Path('a.png:x').suffix == '.png:x'（NTFS ADS 语法），
    放任下去会写出带备用数据流的隐藏文件；统一只接受 [字母数字] 组成的短后缀。
    """
    import re as _re

    suffix = Path(name or "").suffix[:16]
    return suffix if _re.fullmatch(r"\.[A-Za-z0-9]{1,15}", suffix) else ""


def _copy_upload(f, dest: Path, limit: int, name: str) -> int:
    """把上传文件流式落盘（同步，由调用方放线程池）；超限中断并抛 400。

    用 f.file（SpooledTemporaryFile）读取：与 await f.read 同一底层句柄与游标，
    但整段复制在 worker 线程里执行，不阻塞事件循环。
    """
    limit_mb = limit // 1024 // 1024
    size = 0
    with dest.open("wb") as out:
        while True:
            chunk = f.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise HTTPException(400, f"「{name}」超过单文件 {limit_mb}MB 限制")
            out.write(chunk)
    return size


@router.post("/files")
async def upload_files(
    files: list[UploadFile],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not files:
        raise HTTPException(400, "未选择文件")
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(400, f"一次最多上传 {MAX_BATCH_FILES} 个文件")
    dest_dir = Path(settings.DATA_DIR) / data_dirs.TRANSFER / str(user.id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    limit = await run_in_threadpool(max_file_size)
    created: list[TransferItem] = []
    current: Path | None = None
    try:
        try:
            for f in files:
                if f.size and f.size > limit:
                    raise HTTPException(400, f"「{f.filename}」超过单文件 {limit // 1024 // 1024}MB 限制")
                kind = "image" if (f.content_type or "").startswith("image/") else "file"
                filename = f"{secrets.token_hex(8)}{_safe_suffix(f.filename)}"
                current = dest_dir / filename
                size = await run_in_threadpool(_copy_upload, f, current, limit, f.filename or filename)
                t = TransferItem(
                    user_id=user.id,
                    kind=kind,
                    file_name=(f.filename or filename)[:512],
                    file_size=size,
                    content_type=(f.content_type or "")[:128],
                    file_path=f"transfer/{user.id}/{filename}",
                )
                db.add(t)
                created.append(t)
            db.commit()
        except Exception:
            # 批量中途失败：回滚未提交的行，并回收本次已落盘的文件（含当前半成品），
            # 否则会留下无行引用的孤儿文件永久占用磁盘
            db.rollback()
            for t in created:
                try:
                    (Path(settings.DATA_DIR) / t.file_path).unlink(missing_ok=True)
                except OSError:
                    pass
            if current is not None:
                try:
                    current.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
    finally:
        for f in files:
            f.close()
    return {"ok": True, "items": [_item_out(t) for t in created]}


MAX_UPLOAD_SESSIONS_PER_USER = 10  # 单用户未 finish 的活跃上传会话上限（防弃单灌盘）


def _count_user_sessions(user_id: int) -> int:
    """统计某用户当前的分片上传会话数（_cleanup_stale_uploads 已把目录数控制在有限范围）。"""
    import json as _json

    root = _upload_tmp_root()
    n = 0
    try:
        for d in root.iterdir():
            if not d.is_dir():
                continue
            try:
                meta = _json.loads((d / "meta.json").read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            if meta.get("user_id") == user_id:
                n += 1
    except OSError:
        pass
    return n


@router.post("/upload/init")
def upload_init(
    body: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """分片上传第一步：登记上传，返回 upload_id。"""
    import secrets as _secrets
    import time as _time

    _cleanup_stale_uploads()
    name = str((body or {}).get("name", ""))[:512]
    # 来源标记：library=文件库上传（不进总览快传卡），默认 share=快传
    origin = str((body or {}).get("origin") or "share")
    if origin not in ("share", "library"):
        origin = "share"
    # 目标目录（文件库上传）：必须已存在；根目录传 ""。不存在直接拒绝，
    # 避免 finish 时才把文件落到无主目录上
    dir_path = _norm_dir_path(str((body or {}).get("dir") or ""))
    if dir_path and not _get_dir(db, user, dir_path):
        raise HTTPException(404, "目标目录不存在")
    try:
        size = int((body or {}).get("size") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "文件大小无效")
    if not name:
        raise HTTPException(400, "缺少文件名")
    if size > max_file_size():
        raise HTTPException(400, f"「{name}」超过单文件 {max_file_size() // 1024 // 1024}MB 限制")
    if _count_user_sessions(user.id) >= MAX_UPLOAD_SESSIONS_PER_USER:
        raise HTTPException(429, "上传任务过多，请先完成或等待已有任务超时")
    upload_id = _secrets.token_hex(8)
    d = _upload_tmp_root() / upload_id
    d.mkdir(parents=True, exist_ok=False)
    # 会话与创建者绑定：chunk/finish 校验同一用户，防止登录用户拿到的 id 被他人写片/接管合并
    meta = {
        "name": name, "size": size, "mtime": _time.time(), "user_id": user.id,
        "origin": origin, "dir": dir_path,
    }
    (d / "meta.json").write_text(jsonlib.dumps(meta), encoding="utf-8")
    return {"ok": True, "uploadId": upload_id, "chunkSize": CHUNK_SIZE}


def _own_upload(upload_id: str, user: User) -> Path:
    """校验上传会话归属。历史升级场景：meta 无 user_id 的旧会话在首次触达时补绑，
    24h TTL 内自然过渡，不做破坏性拒绝。"""
    if not upload_id or any(ch not in "0123456789abcdef" for ch in upload_id):
        raise HTTPException(400, "非法上传 ID")
    d = _upload_tmp_root() / upload_id
    if not d.is_dir():
        raise HTTPException(404, "上传任务不存在")
    try:
        meta = jsonlib.loads((d / "meta.json").read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise HTTPException(404, "上传任务不存在")
    owner = meta.get("user_id")
    if owner is None:
        meta["user_id"] = user.id
        try:
            (d / "meta.json").write_text(jsonlib.dumps(meta), encoding="utf-8")
        except OSError:
            pass
        return d
    if owner != user.id:
        # 与「上传任务不存在」同文案，不向非属主泄露会话存在性
        raise HTTPException(404, "上传任务不存在")
    return d


@router.put("/upload/{upload_id}/chunk/{index}")
async def upload_chunk(
    upload_id: str,
    index: int,
    request: Request,
    user: User = Depends(get_current_user),
):
    """上传单个分片：先校验声明大小再读，未认证流量打不到内存。"""
    d = _own_upload(upload_id, user)
    if index < 0:
        raise HTTPException(400, "非法分片序号")
    try:
        meta = jsonlib.loads((d / "meta.json").read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise HTTPException(404, "上传任务不存在")
    # 磁盘防线：声明大小（finish 时强制校验）同样约束分片阶段——否则攻击者可声明 1MB
    # 却按 4MB×10 万片灌满磁盘且永不调 finish（24h TTL 兜底前能写入数百 GB）。
    declared_size = meta.get("size") or 0
    # 允许的最大分片序号 = 片数-1；声明 1MB 的文件只有 1 片（index=0），第 2 片直接拒
    max_index = max(0, -(-declared_size // CHUNK_SIZE) - 1)  # ceil(size / CHUNK_SIZE) - 1
    if index > max_index:
        raise HTTPException(400, "分片序号超出文件大小")
    if not await run_in_threadpool(_chunk_fits, d, index, declared_size):
        raise HTTPException(400, "已收分片总量超出声明的文件大小")
    declared = request.headers.get("content-length")
    # isascii() 与 music.py 对齐：Unicode 数字（如 "²"）能过 isdigit 但 int() 会抛 ValueError
    if declared and not (declared.isascii() and declared.isdigit()):
        raise HTTPException(400, "非法 Content-Length")
    if declared and int(declared) > CHUNK_SIZE + 1024:
        raise HTTPException(413, "分片过大")
    # 边读边限：request.body() 会把整个请求体（含 chunked 无长度场景）缓冲进内存后才校验，
    # 认证用户可用超大分片瞬间吃满内存；改为流式读取，一旦超限立即中断。
    size = 0
    parts: list[bytes] = []
    async for piece in request.stream():
        size += len(piece)
        if size > CHUNK_SIZE + 1024:
            raise HTTPException(413, "分片过大")
        parts.append(piece)
    body = b"".join(parts)
    if not body:
        raise HTTPException(400, "分片为空")
    await run_in_threadpool(_store_chunk, d, index, body, declared_size)
    return {"ok": True}


def _chunk_fits(d: Path, index: int, declared_size: int) -> bool:
    """落这一片后是否仍在声明大小之内（先把即将被覆盖的旧片余量扣掉）。"""
    existing = (d / f"part_{index:06d}").exists()
    return _dir_bytes(d) - (CHUNK_SIZE if existing else 0) + CHUNK_SIZE <= declared_size + CHUNK_SIZE


def _store_chunk(d: Path, index: int, body: bytes, declared_size: int) -> None:
    """写入分片并复核会话总量（磁盘操作，线程池内执行）。"""
    path = d / f"part_{index:06d}"
    path.write_bytes(body)
    if _dir_bytes(d) > declared_size + CHUNK_SIZE:
        # 超声明上限：丢弃刚落的片，保持会话不超限
        path.unlink(missing_ok=True)
        raise HTTPException(400, "已收分片总量超出声明的文件大小")


def _dir_bytes(d: Path) -> int:
    """会话目录内分片总字节数（单片上限 4MB、片数受声明大小约束，遍历代价可忽略）。"""
    total = 0
    try:
        for f in d.glob("part_*"):
            total += f.stat().st_size
    except OSError:
        pass
    return total


@router.post("/upload/{upload_id}/finish")
def upload_finish(upload_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """合并分片并建条目（kind 按扩展名判定）。"""
    d = _own_upload(upload_id, user)
    try:
        meta = jsonlib.loads((d / "meta.json").read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise HTTPException(404, "上传任务不存在")
    name = meta.get("name") or "未命名文件"
    parts = sorted(d.glob("part_*"))
    if not parts:
        raise HTTPException(400, "没有收到任何分片")
    dest_dir = Path(settings.DATA_DIR) / data_dirs.TRANSFER / str(user.id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = secrets.token_hex(8) + _safe_suffix(name)
    dest = dest_dir / filename
    size = 0
    try:
        with dest.open("wb") as out:
            for part in parts:
                data = part.read_bytes()
                size += len(data)
                if size > max_file_size():
                    raise HTTPException(400, f"「{name}」超过单文件 {max_file_size() // 1024 // 1024}MB 限制")
                out.write(data)
    except BaseException:
        # 合并中断（超限 400 / 磁盘满 OSError 等）都清掉半成品与分片临时目录，
        # 不留不可见的磁盘垃圾（只清 HTTPException 的话，OSError 半成品会永久残留）
        dest.unlink(missing_ok=True)
        for part in parts:
            part.unlink(missing_ok=True)
        try:
            d.rmdir()
        except OSError:
            pass
        raise
    kind = "image" if dest.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg") else "file"
    origin = meta.get("origin")
    if origin not in ("share", "library"):
        origin = "share"
    # 目标目录随会话落库（init 时已校验存在；会话存活期间目录被删则回退根目录）
    dir_path = _norm_dir_path(str(meta.get("dir") or ""))
    if dir_path and not _get_dir(db, user, dir_path):
        dir_path = ""
    t = TransferItem(
        user_id=user.id,
        kind=kind,
        file_name=name,
        file_size=size,
        content_type="",
        file_path=f"transfer/{user.id}/{filename}",
        origin=origin,
        dir_path=dir_path,
    )
    db.add(t)
    db.commit()
    for part in parts:
        part.unlink(missing_ok=True)
    # rmtree 而非 rmdir：目录内可能残留意外文件（Windows 上 rmdir 偶发句柄延迟失败，
    # 残留目录会一直占住「单用户 10 会话」名额）；清理失败由 TTL 兜底
    shutil.rmtree(d, ignore_errors=True)
    return {"ok": True, "item": _item_out(t)}


@router.delete("/upload/{upload_id}")
def upload_abort(upload_id: str, user: User = Depends(get_current_user)):
    """放弃上传会话：立即删除分片目录、释放「单用户 10 会话」名额（失败/取消时前端调用，
    不再等 TTL）。归属校验与 _own_upload 同口径。"""
    d = _own_upload(upload_id, user)
    shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}


@router.get("/{item_id}/file")
def get_file(
    item_id: int,
    user: User = Depends(get_media_user),
    db: Session = Depends(get_db),
):
    """文件/图片读取：img 标签用 media_key，点击下载也走这里（响应带附件文件名）。"""
    t = db.query(TransferItem).filter(TransferItem.id == item_id, TransferItem.user_id == user.id).first()
    if not t or not t.file_path:
        raise HTTPException(404, "文件不存在")
    path = data_dirs.resolve_rel(t.file_path)
    if not path or not path.is_file():
        raise HTTPException(404, "文件不存在")
    # 长缓存安全：列表/上传响应里的 url 都带 mtime 版本号（见 _item_out），内容替换 URL 即变化
    return FileResponse(
        path,
        filename=t.file_name or path.name,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.delete("/{item_id}")
def delete_item(item_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = _own_item(db, user, item_id)
    if t.file_path:
        ref = (
            db.query(LogoRule.id)
            .filter(
                LogoRule.logo_path == t.file_path,
                LogoRule.user_id == user.id,
                LogoRule.is_deleted.is_(False),
            )
            .count()
        )
        if ref:
            raise HTTPException(400, "该文件正被头像库规则引用，请先在头像库中移除或更换图片")
    _safe_remove(t.file_path)
    db.delete(t)
    db.commit()
    return {"ok": True}
