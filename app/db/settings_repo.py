"""系统设置的仓储函数（读写 system_settings 表）。

与 models/system_setting.py 的实体分离：模型文件只留表结构，
会话管理集中在这里（原先模型文件自开 SessionLocal，是实体与仓储混写的先例）。
"""

from app.db.session import SessionLocal
from app.models.system_setting import SystemSetting


def get_setting(key: str, default: str = "") -> str:
    db = SessionLocal()
    try:
        row = db.get(SystemSetting, key)
        return row.value if row else default
    finally:
        db.close()


def get_setting_db(db, key: str, default: str = "") -> str:
    row = db.get(SystemSetting, key)
    return row.value if row else default


def set_setting(key: str, value: str) -> None:
    db = SessionLocal()
    try:
        row = db.get(SystemSetting, key)
        if row:
            row.value = value
        else:
            db.add(SystemSetting(key=key, value=value))
        db.commit()
    finally:
        db.close()


def get_int_setting(key: str, default: int, lo: int, hi: int) -> int:
    """读取整型设置并夹在 [lo, hi] 内；值损坏/越界时回退 default。"""
    raw = get_setting(key, str(default))
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return default
    if v < lo or v > hi:
        return default
    return v
