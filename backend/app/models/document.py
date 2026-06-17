"""文档 ORM 模型。"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Document(Base):
    """已上传文档及其处理状态。"""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    knowledge_base_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)  # pdf / docx / txt
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    # pending -> processing -> ready / failed
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 每次入队/重建处理任务时递增，后台任务携带期望值以防旧任务覆盖新状态
    processing_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
