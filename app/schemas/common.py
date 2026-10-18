"""连接测试类请求体（音乐 / 影视等上游服务器的「测试连接」端点共用）。"""

from pydantic import BaseModel, Field


class ConnectionTestIn(BaseModel):
    """测试连接的表单值；留空 = 使用已保存配置（pass 是 Python 关键字，用别名接收）"""

    url: str | None = None
    user: str | None = None
    password: str | None = Field(default=None, alias="pass")


def pick(value: str | None, saved: str) -> str:
    """表单值优先（去空白），留空回退已保存配置。"""
    return (value or "").strip() or saved
