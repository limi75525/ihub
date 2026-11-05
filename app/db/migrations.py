"""启动期数据库迁移（create_all 之后的增量迁移与一次性数据修复）。

从 main.py 收拢：组装根只留一行调用 run_startup_migrations()。
全部函数幂等——重复启动零副作用；新迁移按调用顺序追加到 run_startup_migrations。
"""

import logging

from sqlalchemy import text

from app.core.crypto import encrypt_text
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import Source  # noqa: F401 确保模型已注册

logger = logging.getLogger(__name__)

# create_all 不会给已存在的表补列，这里按需做轻量列迁移
_REQUIRED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "messages": [
        ("is_starred", "BOOLEAN DEFAULT 0"),
        ("is_pinned", "BOOLEAN DEFAULT 0"),
        ("is_deleted", "BOOLEAN DEFAULT 0"),
        ("deleted_at", "DATETIME"),
    ],
    "users": [
        ("last_login_ip", "VARCHAR(64) DEFAULT ''"),
        ("is_deleted", "BOOLEAN DEFAULT 0"),
        ("deleted_at", "DATETIME"),
        ("pwd_version", "INTEGER DEFAULT 0"),
        ("media_key", "VARCHAR(64)"),
        ("signature", "VARCHAR(128) DEFAULT ''"),
        ("email", "VARCHAR(128) DEFAULT ''"),
    ],
    "sources": [
        ("is_deleted", "BOOLEAN DEFAULT 0"),
        ("deleted_at", "DATETIME"),
        ("sort_order", "INTEGER DEFAULT 0"),
        ("imap_verify_tls", "BOOLEAN DEFAULT 1"),
        ("is_system", "BOOLEAN DEFAULT 0"),
    ],
    "devices": [("is_deleted", "BOOLEAN DEFAULT 0"), ("deleted_at", "DATETIME")],
    "logo_rules": [("is_deleted", "BOOLEAN DEFAULT 0"), ("deleted_at", "DATETIME")],
    "system_settings": [("is_deleted", "BOOLEAN DEFAULT 0"), ("deleted_at", "DATETIME")],
    "music_tracks": [
        ("album_artist", "VARCHAR(512) DEFAULT ''"),
        ("genre", "VARCHAR(128) DEFAULT ''"),
        ("year", "INTEGER DEFAULT 0"),
        ("track_no", "INTEGER DEFAULT 0"),
        ("disc_no", "INTEGER DEFAULT 0"),
        ("bitrate", "INTEGER DEFAULT 0"),
        ("sample_rate", "INTEGER DEFAULT 0"),
        ("cover_path", "VARCHAR(256)"),
    ],
    "music_playlists": [
        ("description", "VARCHAR(1024) DEFAULT ''"),
        ("cover_path", "VARCHAR(256)"),
    ],
    "transfer_items": [
        ("origin", "VARCHAR(16) DEFAULT 'share'"),
        ("dir_path", "VARCHAR(256) DEFAULT ''"),
    ],
    "video_items": [
        ("original_title", "VARCHAR(512) DEFAULT ''"),
        ("plot", "TEXT DEFAULT ''"),
        ("rating", "FLOAT DEFAULT 0"),
        ("genres", "VARCHAR(256) DEFAULT ''"),
        ("directors", "VARCHAR(512) DEFAULT ''"),
        ("actors", "TEXT DEFAULT ''"),
        ("runtime_min", "INTEGER DEFAULT 0"),
        ("poster_ref", "VARCHAR(512) DEFAULT ''"),
        ("fanart_ref", "VARCHAR(512) DEFAULT ''"),
        ("series_plot", "TEXT DEFAULT ''"),
        ("series_rating", "FLOAT DEFAULT 0"),
        ("series_genres", "VARCHAR(256) DEFAULT ''"),
        ("tmdb_id", "VARCHAR(32) DEFAULT ''"),
        ("series_tmdb_id", "VARCHAR(32) DEFAULT ''"),
        ("meta_sig", "VARCHAR(64) DEFAULT ''"),
    ],
}


def _ensure_sqlite_columns():
    from sqlalchemy import text

    with engine.connect() as conn:
        # 旧版头像规则表（按 4 种类型拆分）已被组合式 logo_rules 取代，直接弃用
        has_old = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='avatar_rules'")
        ).first()
        if has_old:
            conn.execute(text("DROP TABLE avatar_rules"))
        for table, columns in _REQUIRED_COLUMNS.items():
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if not existing:
                continue
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        conn.commit()


def _migrate_logo_groups():
    """旧版组合式 logo_rules（phone/signature/email/nickname 四字段）→ 企业分组模型。

    新结构：logo_groups（企业名称 + 默认头像）+ logo_rules(group_id, signature, account)。
    迁移按「单位」聚合：旧规则以 签名/昵称/号码/邮箱 第一个非空字段作为企业名，
    同名旧规则合并进同一分组，旧规则的头像成为分组默认头像，匹配字段拆为成员规则。
    幂等：新库（logo_rules 已含 account 列）直接跳过。"""
    from sqlalchemy import text

    from app.models.logo_group import LogoGroup
    from app.models.logo_rule import LogoRule as NewRule

    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(logo_rules)"))}
        if not cols or "account" in cols:
            return  # 全新库（create_all 已按新模型建表）或已完成迁移
        conn.execute(text("ALTER TABLE logo_rules RENAME TO logo_rules_old"))
        conn.commit()

    # 旧表已挪走，按新模型补建 logo_rules（此时 create_all 不会再跳过它）
    Base.metadata.create_all(bind=engine, tables=[NewRule.__table__])

    db = SessionLocal()
    moved_rules = 0
    try:
        from datetime import datetime as _dt

        def _parse_dt(v):
            """旧表 raw SQL 读出的时间通常是字符串，ORM DateTime 列只收 datetime。"""
            if isinstance(v, _dt):
                return v
            try:
                return _dt.fromisoformat(v) if v else None
            except (TypeError, ValueError):
                return None

        with engine.connect() as conn:
            old_rows = conn.execute(
                text(
                    "SELECT id, user_id, phone, signature, email, nickname, "
                    "logo_path, logo_url, created_at, is_deleted FROM logo_rules_old"
                )
            ).mappings().all()
        # 按 (user_id, 企业名) 聚合；软删旧规则不迁移（其 Logo 文件按归属清理后随之弃置）
        groups: dict[tuple[int, str], LogoGroup] = {}
        for row in old_rows:
            if row["is_deleted"]:
                continue
            key = (row["signature"] or row["nickname"] or row["phone"] or row["email"] or "未命名").strip()[:128]
            gk = (row["user_id"], key)
            if gk not in groups:
                g = LogoGroup(user_id=row["user_id"], name=key)
                db.add(g)
                db.flush()
                groups[gk] = g
            g = groups[gk]
            # 第一个带 Logo 的旧规则头像 → 企业默认头像（成员规则不再重复挂同一张图）
            if not g.logo_path and not g.logo_url and (row["logo_path"] or row["logo_url"]):
                g.logo_path = row["logo_path"]
                g.logo_url = row["logo_url"]
            members: list[tuple[str, str]] = []
            if row["phone"]:
                members.append((row["signature"] or "", row["phone"]))
            if row["email"]:
                members.append((row["signature"] or row["nickname"] or "", row["email"]))
            if not members:
                members.append((row["signature"] or row["nickname"] or "", ""))
            for sig, acct in members:
                dup = (
                    db.query(NewRule.id)
                    .filter(
                        NewRule.user_id == row["user_id"],
                        NewRule.group_id == g.id,
                        NewRule.signature == (sig or "")[:64],
                        NewRule.account == (acct or "")[:256],
                    )
                    .first()
                )
                if dup:
                    continue
                db.add(
                    NewRule(
                        user_id=row["user_id"],
                        group_id=g.id,
                        signature=(sig or "")[:64],
                        account=(acct or "")[:256],
                        created_at=_parse_dt(row["created_at"]),
                    )
                )
                moved_rules += 1
        db.commit()
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE logo_rules_old"))
            conn.commit()
        logger.info(
            "头像库已迁移为企业分组模型：%s 个企业分组、%s 条匹配规则",
            len(groups), moved_rules,
        )
    except Exception:
        db.rollback()
        logger.exception("头像库分组迁移失败（保留旧表 logo_rules_old 供排查）")
        raise
    finally:
        db.close()


def _migrate_email_passwords():
    """历史明文授权码统一加密为 Fernet 密文（幂等：密文跳过）。"""
    db = SessionLocal()
    try:
        sources = (
            db.query(Source)
            .filter(Source.type == "email", Source.email_password.isnot(None))
            .all()
        )
        migrated = 0
        for s in sources:
            if not s.email_password or s.email_password.startswith("gAAAA"):
                continue  # 已是密文
            s.email_password = encrypt_text(s.email_password)
            migrated += 1
        if migrated:
            db.commit()
            logger.info("已加密 %s 个来源的历史明文授权码", migrated)
    finally:
        db.close()



def _cleanup_seed_system_sources() -> None:
    """删除历史「种子」系统来源及其事件消息（系统通知已接管，接入服务不再展示）。

    注意：这里必须是普通函数——曾误加 @asynccontextmanager，调用出来只是个
    context manager 对象、函数体从不执行，导致旧库里的「种子」系统来源一直
    留在 接入服务 里且界面不给删除按钮。
    """
    from app.models.message import Message

    db = SessionLocal()
    try:
        ids = [
            sid
            for (sid,) in db.query(Source.id)
            .filter(Source.is_system.is_(True), Source.name == "种子")
            .all()
        ]
        if not ids:
            return
        deleted = (
            db.query(Message)
            .filter(Message.source_id.in_(ids))
            .delete(synchronize_session=False)
        )
        db.query(Source).filter(Source.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
        logger.info("已清理种子系统来源 %s 个及其事件消息 %s 条", len(ids), deleted)
    except Exception:
        db.rollback()
        logger.exception("清理种子系统来源失败")


def run_startup_migrations() -> None:
    """create_all 之后按顺序执行全部迁移；任何一步失败整体抛出（启动即失败，不半迁移）。"""
    _ensure_sqlite_columns()
    _migrate_logo_groups()
    _migrate_email_passwords()
    # 系统通知上线（2026-10-25）：种子事件不再进消息中心，历史「种子」系统来源及其消息一并清除
    _cleanup_seed_system_sources()
