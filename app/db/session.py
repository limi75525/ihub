from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

engine = create_engine(
    f"sqlite:///{settings.DATA_DIR / 'ihub.db'}",
    # timeout：写锁被占（扫描线程批量写 / ingest 提交 nonce）时最多等 30s 再报
    # database is locked，而不是 pysqlite 默认 5s——单 worker 下读写并发的主要兜底
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _sqlite_pragma(dbapi_conn, _record):
    """WAL：读写不互斥（API 读不会被 ingest/扫描/调度线程的写阻塞）。

    journal_mode 持久化在库文件上，重复执行幂等；busy_timeout 按连接生效。
    """
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
