"""上传文件的读取 / 落盘辅助。

图片类上传入口（用户头像、头像库 Logo、接入服务 Logo、导航 Logo、站点品牌、登录背景）
共用「按上限读取 + mkdir + 随机文件名写盘」；
后缀白名单、大小上限与错误文案属于各入口的业务差异，保留在调用方。
"""

import secrets
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.core.config import settings


async def read_limited(file: UploadFile, limit: int, size_error: str) -> bytes:
    """按上限读取（多读 1 字节探测超限）：避免先整段读进内存再判断大小。

    空文件统一报「文件为空」；调用方若还要做 SVG 清洗，清洗后需自行再判一次空。
    """
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(400, size_error)
    if not data:
        raise HTTPException(400, "文件为空")
    return data


def random_name(prefix: str, ext: str) -> str:
    """随机后缀文件名：<prefix>_<8位hex><ext>（防覆盖；不含用户可控内容）。"""
    return f"{prefix}_{secrets.token_hex(4)}{ext}"


def save_bytes(rel_dir: str, filename: str, data: bytes) -> str:
    """写入 DATA_DIR/<rel_dir>/<filename>，返回入库用的相对路径。"""
    d = Path(settings.DATA_DIR) / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_bytes(data)
    return f"{rel_dir}/{filename}"


def save_unique(rel_dir: str, prefix: str, ext: str, data: bytes) -> str:
    """按随机文件名落盘，返回入库用的相对路径。"""
    return save_bytes(rel_dir, random_name(prefix, ext), data)
