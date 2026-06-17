"""知识库 ORM 模型。"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class KnowledgeBase(Base):
    """知识库：文档与向量检索的逻辑隔离单元。"""

    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Chroma collection 名称，与知识库一一对应
    collection_name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    # 整库重建任务版本号；每次调度重建递增，后台任务携带期望值以防旧任务继续跑
    rebuild_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    documents = relationship("Document", back_populates="knowledge_base", cascade="all, delete-orphan")
    chat_sessions = relationship("ChatSession", back_populates="knowledge_base", cascade="all, delete-orphan")
