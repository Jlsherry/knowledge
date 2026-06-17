"""文档处理服务：上传、解析、向量化入库。"""

import logging
import re
import time
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import Document, KnowledgeBase
from app.services.document_loader import ALLOWED_EXTENSIONS, load_document
from app.services.vector_store import (
    add_documents_to_store,
    clear_collection,
    delete_document_chunks,
)

logger = logging.getLogger(__name__)

# 文件名白名单：字母、数字、中文、常见标点与空格
_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w\u4e00-\u9fff.\-()（） ]", re.UNICODE)
_MAX_FILENAME_STEM_LEN = 200


def sanitize_upload_filename(filename: str) -> str:
    """
    清洗上传文件名，用于磁盘存储与数据库记录。

    - 仅保留 basename，去除路径分隔符与 ``..``
    - 白名单字符过滤，移除控制字符与特殊符号
    - 保留合法扩展名（pdf / docx / txt）
    """
    base = Path(filename or "").name.strip().replace("\x00", "")
    if not base or base in {".", ".."}:
        base = "upload"

    lower_base = base.lower()
    if lower_base in ALLOWED_EXTENSIONS:
        return f"upload{lower_base}"

    suffix = Path(base).suffix.lower()
    stem = Path(base).stem

    stem = _UNSAFE_FILENAME_CHARS.sub("", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" .-_")
    if not stem:
        stem = "upload"

    if len(stem) > _MAX_FILENAME_STEM_LEN:
        stem = stem[:_MAX_FILENAME_STEM_LEN]

    if suffix in ALLOWED_EXTENSIONS:
        return f"{stem}{suffix}"
    return stem


def save_upload_file(kb_id: str, filename: str, file_bytes: bytes) -> Path:
    """
    将上传文件保存到本地目录。

    路径格式：uploads/{kb_id}/{uuid}_{sanitized_filename}
    """
    settings = get_settings()
    kb_dir = settings.upload_path / kb_id
    kb_dir.mkdir(parents=True, exist_ok=True)

    safe_filename = sanitize_upload_filename(filename)
    safe_name = f"{uuid.uuid4().hex[:8]}_{safe_filename}"
    file_path = kb_dir / safe_name
    file_path.write_bytes(file_bytes)
    return file_path


def bump_processing_version(db: Session, doc: Document) -> int:
    """递增处理版本号并返回新值，用于绑定后台任务。"""
    doc.processing_version = int(doc.processing_version or 0) + 1
    db.commit()
    db.refresh(doc)
    return doc.processing_version


def bump_kb_rebuild_version(db: Session, kb: KnowledgeBase) -> int:
    """递增整库重建版本号并返回新值，用于绑定后台任务。"""
    kb.rebuild_version = int(kb.rebuild_version or 0) + 1
    db.commit()
    db.refresh(kb)
    return kb.rebuild_version


def _is_kb_rebuild_current(db: Session, kb_id: str, expected_version: int) -> bool:
    """知识库仍存在且重建版本未变时返回 True。"""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        logger.info(
            "kb rebuild job aborted: missing kb_id=%s expected_version=%s",
            kb_id,
            expected_version,
        )
        return False
    if int(kb.rebuild_version or 0) != expected_version:
        logger.info(
            "kb rebuild job aborted: stale version kb_id=%s expected=%s actual=%s",
            kb_id,
            expected_version,
            kb.rebuild_version,
        )
        return False
    return True


def _load_kb(db: Session, kb_id: str) -> KnowledgeBase | None:
    return db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()


def _is_job_current(db: Session, doc_id: str, expected_version: int) -> bool:
    """文档仍存在且处理版本未变时返回 True。"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        logger.info(
            "document job aborted: deleted doc_id=%s expected_version=%s",
            doc_id,
            expected_version,
        )
        return False
    if int(doc.processing_version or 0) != expected_version:
        logger.info(
            "document job aborted: stale version doc_id=%s expected=%s actual=%s",
            doc_id,
            expected_version,
            doc.processing_version,
        )
        return False
    return True


def _abort_stale_job(
    db: Session,
    doc_id: str,
    kb: KnowledgeBase,
    expected_version: int,
    *,
    reason: str,
) -> None:
    """旧任务退出前清理可能误写入的向量 chunk。"""
    logger.info(
        "document job stopping doc_id=%s expected_version=%s reason=%s",
        doc_id,
        expected_version,
        reason,
    )
    try:
        delete_document_chunks(kb.collection_name, doc_id)
    except Exception:
        logger.exception("failed to cleanup stale chunks doc_id=%s", doc_id)
    db.expire_all()


def process_document(
    db: Session,
    doc: Document,
    kb: KnowledgeBase,
    *,
    expected_version: int,
) -> bool:
    """
    同步处理单个文档：解析 → 分块 → 向量化 → 更新状态。

    返回 True 表示处理完成并提交；False 表示任务已过期或被取消。
    """
    doc_id = doc.id
    if not _is_job_current(db, doc_id, expected_version):
        return False

    doc.status = "processing"
    doc.error_message = None
    doc.chunk_count = 0
    db.commit()

    start = time.perf_counter()
    logger.info(
        "document processing started doc_id=%s version=%s kb_id=%s filename=%s",
        doc_id,
        expected_version,
        kb.id,
        doc.filename,
    )

    if not _is_job_current(db, doc_id, expected_version):
        _abort_stale_job(db, doc_id, kb, expected_version, reason="before_parse")
        return False

    try:
        file_path = Path(doc.file_path)
        if not file_path.exists():
            if not _is_job_current(db, doc_id, expected_version):
                return False
            doc = db.query(Document).filter(Document.id == doc_id).one()
            doc.status = "failed"
            doc.error_message = "原始文件不存在，可能已被删除"
            doc.chunk_count = 0
            db.commit()
            return True

        documents = load_document(file_path, doc.file_type)

        if not _is_job_current(db, doc_id, expected_version):
            _abort_stale_job(db, doc_id, kb, expected_version, reason="after_parse")
            return False

        chunk_count = add_documents_to_store(
            collection_name=kb.collection_name,
            documents=documents,
            document_id=doc_id,
            filename=doc.filename,
            processing_version=expected_version,
        )

        if not _is_job_current(db, doc_id, expected_version):
            _abort_stale_job(db, doc_id, kb, expected_version, reason="after_index")
            return False

        doc = db.query(Document).filter(Document.id == doc_id).one()
        doc.status = "ready"
        doc.chunk_count = chunk_count
        doc.error_message = None
        db.commit()
        logger.info(
            "document processing finished doc_id=%s version=%s status=ready chunks=%s elapsed=%.3fs",
            doc_id,
            expected_version,
            chunk_count,
            time.perf_counter() - start,
        )
        return True
    except Exception as exc:
        if not _is_job_current(db, doc_id, expected_version):
            _abort_stale_job(db, doc_id, kb, expected_version, reason="after_error")
            return False

        doc = db.query(Document).filter(Document.id == doc_id).one()
        doc.status = "failed"
        doc.error_message = str(exc)
        doc.chunk_count = 0
        db.commit()
        logger.exception(
            "document processing failed doc_id=%s version=%s elapsed=%.3fs",
            doc_id,
            expected_version,
            time.perf_counter() - start,
        )
        return True


def schedule_document_processing(db: Session, doc: Document, kb: KnowledgeBase) -> int:
    """递增版本并返回 job 版本号，供后台任务绑定。"""
    version = bump_processing_version(db, doc)
    logger.info(
        "document processing scheduled doc_id=%s version=%s kb_id=%s",
        doc.id,
        version,
        kb.id,
    )
    return version


def process_document_by_id(doc_id: str, kb_id: str, expected_version: int) -> None:
    """
    后台任务入口：使用独立数据库会话重新加载文档和知识库后处理。

    ``expected_version`` 由调度方在入队前递增得到；版本不匹配或文档已删除时静默退出。
    """
    db = SessionLocal()
    try:
        if not _is_job_current(db, doc_id, expected_version):
            return

        doc = db.query(Document).filter(Document.id == doc_id).first()
        kb = _load_kb(db, kb_id)
        if not doc or not kb:
            logger.info(
                "document job skipped doc_id=%s version=%s missing_doc_or_kb",
                doc_id,
                expected_version,
            )
            return

        process_document(db, doc, kb, expected_version=expected_version)
    finally:
        db.close()


def rebuild_document(db: Session, doc: Document, kb: KnowledgeBase) -> Document:
    """
    重建单个文档的向量数据。

    会先删除该文档旧 chunk，再基于 SQLite 中记录的 file_path 重新解析入库。
    """
    expected_version = bump_processing_version(db, doc)
    doc.status = "pending"
    doc.chunk_count = 0
    doc.error_message = None
    db.commit()

    try:
        delete_document_chunks(kb.collection_name, doc.id)
    except Exception:
        pass

    process_document(db, doc, kb, expected_version=expected_version)
    db.refresh(doc)
    return doc


def rebuild_knowledge_base(db: Session, kb: KnowledgeBase) -> int:
    """
    调度整库向量重建：清空 collection、重置文档状态并返回 job 版本号。

    实际逐文档处理由 ``rebuild_knowledge_base_by_id`` 在后台执行。
    """
    rebuild_version = bump_kb_rebuild_version(db, kb)
    docs = (
        db.query(Document)
        .filter(Document.knowledge_base_id == kb.id)
        .order_by(Document.created_at.asc())
        .all()
    )

    clear_collection(kb.collection_name)

    for doc in docs:
        doc.processing_version = int(doc.processing_version or 0) + 1
        doc.status = "pending"
        doc.chunk_count = 0
        doc.error_message = None
    db.commit()

    logger.info(
        "kb rebuild scheduled kb_id=%s version=%s doc_count=%s",
        kb.id,
        rebuild_version,
        len(docs),
    )
    return rebuild_version


def rebuild_knowledge_base_by_id(kb_id: str, expected_rebuild_version: int) -> None:
    """
    后台任务入口：按文档顺序重建向量，版本不匹配时静默退出。

    ``expected_rebuild_version`` 由调度方在入队前递增得到。
    """
    db = SessionLocal()
    start = time.perf_counter()
    try:
        if not _is_kb_rebuild_current(db, kb_id, expected_rebuild_version):
            return

        kb = _load_kb(db, kb_id)
        if not kb:
            logger.info(
                "kb rebuild job skipped kb_id=%s version=%s missing_kb",
                kb_id,
                expected_rebuild_version,
            )
            return

        docs = (
            db.query(Document)
            .filter(Document.knowledge_base_id == kb.id)
            .order_by(Document.created_at.asc())
            .all()
        )
        logger.info(
            "kb rebuild started kb_id=%s version=%s doc_count=%s",
            kb.id,
            expected_rebuild_version,
            len(docs),
        )

        processed = 0
        for doc in docs:
            if not _is_kb_rebuild_current(db, kb_id, expected_rebuild_version):
                logger.info(
                    "kb rebuild stopped kb_id=%s version=%s processed=%s reason=stale",
                    kb_id,
                    expected_rebuild_version,
                    processed,
                )
                return

            current = db.query(Document).filter(Document.id == doc.id).first()
            if not current:
                continue

            version = int(current.processing_version or 0)
            process_document(db, current, kb, expected_version=version)
            processed += 1

        logger.info(
            "kb rebuild finished kb_id=%s version=%s processed=%s elapsed=%.3fs",
            kb_id,
            expected_rebuild_version,
            processed,
            time.perf_counter() - start,
        )
    finally:
        db.close()


def remove_document(db: Session, doc: Document, kb: KnowledgeBase) -> None:
    """删除文档：使进行中的任务失效、清理向量 chunk、本地文件与数据库记录。"""
    doc_id = doc.id
    bump_processing_version(db, doc)

    try:
        delete_document_chunks(kb.collection_name, doc_id)
    except Exception:
        pass

    file_path = Path(doc.file_path)
    if file_path.exists():
        file_path.unlink()

    db.delete(doc)
    db.commit()
    logger.info("document removed doc_id=%s", doc_id)
