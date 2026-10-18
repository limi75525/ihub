"""数据库访问的通用小工具。"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def get_or_create(db: Session, model, **filters):
    """按唯一键「查到即返回，查不到即建」；并发首建撞唯一约束时回滚重查。

    音乐播放统计（star/scrobble）与影视播放心跳（10s 心跳与 stop 并发首发同一新条目）
    用同一模式：flush 撞 IntegrityError → 回滚取对方已建的行；极端竞态下第二次查询
    仍可能 miss（对方事务尚未提交），再查不到就重建而不是抛 500。
    """
    row = db.query(model).filter_by(**filters).first()
    if row is None:
        row = model(**filters)
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            row = db.query(model).filter_by(**filters).first()
            if row is None:
                row = model(**filters)
                db.add(row)
                db.flush()
    return row
