from datetime import datetime, timezone


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite 读出的 datetime 是 naive-UTC，统一补上 UTC 时区。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
