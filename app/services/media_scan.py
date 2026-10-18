"""NAS 媒体库增量扫描共享引擎（音乐 / 影视）。

两端扫描的骨架完全一致，仅「解析单文件」「落库/清理钩子」不同：

- 状态存 system_settings 的 `<prefix>_scan_state` JSON 键；进程内单例锁防并发发起
- os.walk + followlinks=False（rglob 在 py3.12 会跟进符号链接目录，链接环让扫描空转）
- 未变化的文件跳过解析（增量关键；默认比对 mtime+size，可经 signature/row_signature 钩子扩展）；解析进度按时间节流回写
- 解析结果落库：新增 / 更新 / 删除三类，一并清理被替换或下线的附属文件（如内嵌封面）

"""

import json as jsonlib
import logging
import os
import threading
import time
from pathlib import Path

from app.db.session import SessionLocal
from app.models.system_setting import get_setting_db, set_setting

logger = logging.getLogger(__name__)

# 僵死阈值：进程重启/扫描线程被杀会让 running 永久残留，超过 2 小时视为僵死，允许重新发起
STUCK_SECONDS = 7200


class ScanStateStore:
    """扫描状态（system_settings 单个 JSON 键）的读写与发起。"""

    def __init__(self, state_key: str) -> None:
        self._key = state_key
        self._lock = threading.Lock()

    def read(self) -> dict:
        db = SessionLocal()
        try:
            raw = get_setting_db(db, self._key, "")
            return jsonlib.loads(raw) if raw else {}
        except Exception:
            return {}
        finally:
            db.close()

    def write(self, **kv) -> None:
        state = self.read()
        state.update(kv)
        set_setting(self._key, jsonlib.dumps(state))

    def begin(self) -> tuple[bool, dict]:
        """发起扫描：已在运行且未僵死返回 (False, 当前状态)，否则置运行态返回 (True, {})。"""
        with self._lock:
            state = self.read()
            started_at = int(state.get("started_at") or 0)
            stuck = state.get("running") and started_at and (time.time() - started_at > STUCK_SECONDS)
            if state.get("running") and not stuck:
                return False, state
            self.write(
                running=True, phase="listing", total=0, seen=0, added=0, updated=0,
                removed=0, error="", started_at=int(time.time()), finished_at=0,
            )
        return True, {}


def reset_stale_scan(state_key: str, label: str) -> None:
    """进程启动即代表上一次扫描线程已不存在；把残留的 running 状态标记为中断，
    避免 /scan 以「已在运行」为由拒绝启动、状态页永远显示 running。"""
    db = SessionLocal()
    try:
        raw = get_setting_db(db, state_key, "")
        if not raw:
            return
        state = jsonlib.loads(raw)
        if not state.get("running"):
            return
        state.update(
            running=False,
            phase="interrupted",
            error="进程重启，扫描中断",
            finished_at=int(time.time()),
        )
        set_setting(state_key, jsonlib.dumps(state))
        logger.warning("检测到上次进程遗留的%s扫描运行态，已复位为 interrupted", label)
    except Exception:
        logger.exception("复位%s扫描状态失败", label)
    finally:
        db.close()


def walk_media_files(root: Path, exts: set[str], skip_name=None) -> list[Path]:
    """收集媒体文件；skip_name(文件名) 为真则跳过（影视跳隐藏文件与 sample 片段）。"""
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # followlinks=False + 显式剔除链接目录：rglob 在 py3.12（NAS 镜像）会跟进符号链接目录，
        # 遇到链接环会让扫描线程空转（只有 2h 僵死兜底），链到库外的媒体也会被收元数据
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for fn in filenames:
            if skip_name is not None and skip_name(fn):
                continue
            p = Path(dirpath) / fn
            if p.suffix.lower() in exts:
                files.append(p)
    return files


def run_media_scan(
    *,
    store: ScanStateStore,
    model,
    root: Path,
    files: list[Path],
    parse,
    apply_meta,
    force_parse: bool = False,
    need_update=None,
    on_remove=None,
    done_extra: dict | None = None,
    signature=None,
    row_signature=None,
) -> None:
    """扫描主体（在线程中运行；独立会话）。

    - parse(path, rel, st) -> dict | None：返回模型字段字典（None = 本次未变化不落库）
    - apply_meta(row, meta)：把 meta 写入已存在的行（音乐在此顺带清理被替换的旧封面）
    - force_parse：忽略 mtime 全量重解析（音乐扫描器版本升级时用）
    - need_update(row, meta) -> bool：额外判定是否需要更新（None = 拿到 meta 即更新）
    - on_remove(row)：文件已从磁盘消失、行即将删除时的附属文件清理钩子
    - signature(path, st) / row_signature(row)：增量比对键（默认视频文件 mtime+size）。
      影视把同名 NFO 的时间戳折进签名：NFO 被刮削器重写时也会重新解析
    """
    sig_of = signature or (lambda p, st: (int(st.st_mtime), st.st_size))
    row_sig_of = row_signature or (lambda row: (row.mtime, row.size))
    db = SessionLocal()
    try:
        store.write(phase="scanning", total=len(files), seen=0)
        existing = {t.path: t for t in db.query(model).all()}
        found: dict[str, dict | None] = {}
        last_touch = 0.0
        for i, p in enumerate(files):
            rel = p.relative_to(root).as_posix()
            try:
                st = p.stat()
                row = existing.get(rel)
                if not force_parse and row is not None and row_sig_of(row) == sig_of(p, st):
                    found[rel] = None  # 未变化：复用库中记录，不重新解析
                else:
                    found[rel] = parse(p, rel, st)
            except OSError:
                continue
            now = time.monotonic()
            if i % 25 == 0 or now - last_touch > 2.0:
                last_touch = now
                store.write(seen=i + 1)
        added = updated = 0
        for rel, meta in found.items():
            if meta is None:
                continue
            row = existing.get(rel)
            if row is None:
                db.add(model(**meta))
                added += 1
            elif need_update is None or need_update(row, meta):
                apply_meta(row, meta)
                updated += 1
        removed = 0
        for rel, row in existing.items():
            if rel not in found:
                if on_remove is not None:
                    on_remove(row)
                db.delete(row)
                removed += 1
        db.commit()
        store.write(
            running=False, phase="done", seen=len(files), added=added, updated=updated,
            removed=removed, finished_at=int(time.time()), error="", **(done_extra or {}),
        )
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        try:
            store.write(running=False, phase="error", error=str(e)[:512], finished_at=int(time.time()))
        except Exception:
            # 写状态失败（磁盘满/DB 持续锁死）不能再抛：否则 running=True 永久残留
            logger.exception("媒体扫描状态回写失败（原扫描错误：%s）", e)
    finally:
        db.close()
