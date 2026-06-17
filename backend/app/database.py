"""SQLAlchemy 数据库初始化与会话管理。"""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings

settings = get_settings()

# SQLite 需要 check_same_thread=False 以支持 FastAPI 多线程
connect_args = {}
if settings.database_path.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_path,
    connect_args=connect_args,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """ORM 模型基类。"""


def get_db() -> Generator:
    """
    FastAPI 依赖注入：提供数据库会话，请求结束后自动关闭。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """创建所有数据表（应用启动时调用）。"""
    from app.models import knowledge_base, document, session, message  # noqa: F401
    from app.services.knowledge_base_service import ensure_default_knowledge_base

    # 先创建数据目录，避免 SQLite 无法创建数据库文件
    settings.chroma_path.mkdir(parents=True, exist_ok=True)
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    if settings.database_path.startswith("sqlite"):
        db_file = settings.database_path.replace("sqlite:///", "")
        Path(db_file).parent.mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(bind=engine)

    from app.migrations import run_migrations

    run_migrations(engine)

    # 初始化默认知识库
    db = SessionLocal()
    try:
        ensure_default_knowledge_base(db)
    finally:
        db.close()
