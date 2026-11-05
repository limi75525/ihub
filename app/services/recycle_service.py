"""回收站开关的统一读取。

从 api/v1/recycle.py 下沉：books/logos/sources/settings 等删除入口都要判断
开关状态，路由层互相 import 违反依赖方向。
"""

from app.db.settings_repo import get_setting


def recycle_enabled() -> bool:
    """回收站开关（系统设置，管理员可改）。读库走独立短会话，供各删除入口调用。"""
    return get_setting("recycle_enabled", "true") == "true"
