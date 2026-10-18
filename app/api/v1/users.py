"""管理员：用户管理。"""

import secrets

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_admin, get_media_user
from app.core.security import hash_password
from app.db.session import get_db
from app.models.source import Source
from app.models.user import User
from app.schemas.auth import MAX_PASSWORD_BYTES, UserOut

router = APIRouter(tags=["users"], prefix="/users")


def _user_out(user: User) -> UserOut:
    from app.api.v1.auth import avatar_url_for

    out = UserOut.model_validate(user)
    out.avatar_url = avatar_url_for(user)
    return out


class UserPatchIn(BaseModel):
    is_active: bool | None = None
    password: str | None = None
    nickname: str | None = None
    username: str | None = None
    role: str | None = None


@router.get("", response_model=list[UserOut])
def list_users(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    return [_user_out(u) for u in db.query(User).filter(User.is_deleted.is_(False)).order_by(User.id).all()]


@router.patch("/{user_id}", response_model=UserOut)
def patch_user(
    user_id: int,
    body: UserPatchIn,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user or user.is_deleted:
        raise HTTPException(404, "用户不存在")
    if user.id == admin.id and body.is_active is False:
        raise HTTPException(400, "不能禁用自己")
    # 登录账号（用户名）：管理员可改自己与其他用户的；需查重
    if body.username is not None:
        new_name = body.username.strip()
        if len(new_name) < 2 or len(new_name) > 64:
            raise HTTPException(400, "用户名长度需在 2-64 个字符")
        dup = (
            db.query(User)
            .filter(User.username == new_name, User.is_deleted.is_(False), User.id != user.id)
            .first()
        )
        if dup:
            raise HTTPException(400, f"用户名「{new_name}」已被占用")
        user.username = new_name
    # 角色：仅支持设置其他用户（避免把自己降级后无人管理平台）
    if body.role is not None:
        if body.role not in ("admin", "user"):
            raise HTTPException(400, "角色无效")
        if user.id == admin.id:
            raise HTTPException(400, "不能修改自己的角色")
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.nickname is not None:
        user.nickname = body.nickname.strip()
    if body.password:
        # 与注册同一套口令策略（含 bcrypt 72 字节上限），避免管理员绕过
        if len(body.password) < 6 or len(body.password.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise HTTPException(400, "密码长度需在 6 个字符以上、不超过 72 字节")
        user.password_hash = hash_password(body.password)
        # 版本 +1 使该用户所有旧 JWT 失效；媒体密钥轮换使旧媒体 URL 失效
        user.pwd_version = (user.pwd_version or 0) + 1
        user.media_key = secrets.token_urlsafe(24)
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    from datetime import datetime, timezone

    from app.models.device import Device
    from app.models.logo_rule import LogoRule
    from app.models.message import Message

    user = db.get(User, user_id)
    if not user or user.is_deleted:
        raise HTTPException(404, "用户不存在")
    if user.id == admin.id:
        raise HTTPException(400, "不能删除自己")
    if user.role == "admin":
        raise HTTPException(400, "不能删除管理员账号")
    now = datetime.now(timezone.utc)
    # 级联逻辑删除该用户全部数据（消息/来源/设备/头像规则 + 用户本身），30 天后物理清除
    db.query(Message).filter(Message.user_id == user_id).update(
        {"is_deleted": True, "deleted_at": now}, synchronize_session=False
    )
    db.query(Source).filter(Source.user_id == user_id).update(
        {"is_deleted": True, "is_active": False, "deleted_at": now}, synchronize_session=False
    )
    db.query(Device).filter(Device.user_id == user_id).update(
        {"is_deleted": True, "is_active": False, "deleted_at": now}, synchronize_session=False
    )
    db.query(LogoRule).filter(LogoRule.user_id == user_id).update(
        {"is_deleted": True, "deleted_at": now}, synchronize_session=False
    )
    # 解除 username 唯一约束：30 天内同名可注册新号（登录/管理列表均已按软删过滤）；
    # 后缀撞上既有用户名时补随机尾巴，避免 IntegrityError 500
    renamed = f"{user.username[:48]}__del{user.id}"
    if db.query(User.id).filter(User.username == renamed).first():
        renamed = f"{renamed}{secrets.token_hex(2)}"
    user.username = renamed
    user.is_active = False
    user.is_deleted = True
    user.deleted_at = now
    db.commit()
    return {"ok": True}


@router.post("/{user_id}/avatar", response_model=UserOut)
async def upload_user_avatar(
    user_id: int,
    file: UploadFile,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """管理员为指定用户设置头像（与本人上传共用同一套校验与落盘逻辑）。"""
    from app.api.v1.auth import apply_avatar_upload

    target = db.get(User, user_id)
    if not target or target.is_deleted:
        raise HTTPException(404, "用户不存在")
    await apply_avatar_upload(target, file)
    db.commit()
    db.refresh(target)
    return _user_out(target)


@router.get("/avatar/{user_id}")
def get_avatar(user_id: int, user: User = Depends(get_media_user), db: Session = Depends(get_db)):
    from pathlib import Path

    from fastapi.responses import FileResponse

    from app.core.config import settings
    from app.core.fsutil import data_file

    # 用户数据按账号隔离：仅本人与管理员可取他人头像（头像用于用户管理列表）
    if user.id != user_id and user.role != "admin":
        raise HTTPException(404, "无头像")
    target = db.get(User, user_id)
    if not target or not target.avatar_path:
        raise HTTPException(404, "无头像")
    path = data_file(settings.DATA_DIR, target.avatar_path)
    if not path or not path.is_file():
        raise HTTPException(404, "无头像")
    from app.api.v1.auth import media_file_headers

    return FileResponse(path, headers=media_file_headers(path))
