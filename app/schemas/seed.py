"""种子模块请求/响应模型。"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

SEED_KINDS = ("qbittorrent", "moviepilot")
SEED_VISIBILITY = ("all", "standard", "download_subscribe", "admin_only")
SEED_EVENTS = ("download_complete", "subscribe_complete", "signin_failed")

class SeedConnectionIn(BaseModel):
    kind: Literal["qbittorrent", "moviepilot"]
    name: str = Field(default="", max_length=64)
    base_url: str = Field(min_length=1, max_length=1024)
    username: str = Field(default="", max_length=256)
    # qB 密码或 MoviePilot API_TOKEN；只写不读
    secret: str = Field(default="", max_length=1024)
    auth_mode: str = Field(default="password", max_length=16)
    verify_tls: bool = True
    enabled: bool = True

    @field_validator("base_url")
    @classmethod
    def _strip_base_url(cls, v: str) -> str:
        return v.strip().rstrip("/")


class SeedConnectionPatch(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    base_url: str | None = Field(default=None, max_length=1024)
    username: str | None = Field(default=None, max_length=256)
    secret: str | None = Field(default=None, max_length=1024)
    clear_secret: bool = False
    auth_mode: str | None = Field(default=None, max_length=16)
    verify_tls: bool | None = None
    enabled: bool | None = None

    @field_validator("base_url")
    @classmethod
    def _strip_base_url(cls, v: str | None) -> str | None:
        return v.strip().rstrip("/") if v else v


class SeedActionIn(BaseModel):
    action: Literal["pause", "resume", "recheck", "reannounce"]


class SeedDeleteIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    delete_files: bool = False
    confirm: bool = False


class SeedBulkActionIn(BaseModel):
    hashes: list[str] = Field(min_length=1, max_length=200)
    action: Literal["pause", "resume"]


class SeedBulkDeleteIn(BaseModel):
    hashes: list[str] = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=256)
    delete_files: bool = False
    confirm: bool = False


class SeedTransferIn(BaseModel):
    target: Literal["tv", "movie"]


class SubscribeSeasonIn(BaseModel):
    """详情页季订阅/取消订阅（走 MP 的订阅接口）。"""
    action: Literal["subscribe", "unsubscribe"]
    name: str = Field(min_length=1, max_length=256)
    year: str = Field(default="", max_length=16)
    tmdb_id: str = Field(min_length=1, max_length=32)
    season: int = Field(..., ge=0, le=200)


class SeedResourceActionIn(BaseModel):
    op_id: str = Field(min_length=10, max_length=128)


class SeedAddIn(BaseModel):
    url: str = Field(min_length=1, max_length=8192)
    save_path: str = Field(default="", max_length=1024)
    category: str = Field(default="", max_length=128)
    tags: str = Field(default="", max_length=256)
    paused: bool = False
