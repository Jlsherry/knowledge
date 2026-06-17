"""文档上传与管理 API（绑定默认知识库）。"""

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document
from app.schemas import ApiResponse, DocumentResponse
from app.services.document_loader import ALLOWED_EXTENSIONS, get_file_type
from app.services.document_service import (
    process_document_by_id,
    rebuild_document,
    rebuild_knowledge_base,
    rebuild_knowledge_base_by_id,
    remove_document,
    sanitize_upload_filename,
    save_upload_file,
    schedule_document_processing,
)
from app.services.knowledge_base_service import get_default_knowledge_base

router = APIRouter(prefix="/api/documents", tags=["文档"])

# 单文件大小上限 20MB
MAX_FILE_SIZE = 20 * 1024 * 1024


@router.post("", summary="上传文档")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="支持 pdf / docx / txt"),
    db: Session = Depends(get_db),
) -> ApiResponse:
    """
    上传文档到默认知识库，保存记录后在后台解析并向量化入库。

    处理流程：保存文件 → 创建记录 → 后台解析分块 → Embedding → 写入 Chroma。
    支持格式：`.pdf`、`.docx`、`.txt`。
    """
    kb = get_default_knowledge_base(db)

    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    safe_filename = sanitize_upload_filename(file.filename)
    ext = Path(safe_filename).suffix.lower() if "." in safe_filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式，仅支持: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过 20MB 限制")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="文件内容为空")

    try:
        file_type = get_file_type(safe_filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    file_path = save_upload_file(kb.id, safe_filename, content)

    doc = Document(
        knowledge_base_id=kb.id,
        filename=safe_filename,
        file_type=file_type,
        file_path=str(file_path),
        file_size=len(content),
        status="pending",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    job_version = schedule_document_processing(db, doc, kb)
    background_tasks.add_task(process_document_by_id, doc.id, kb.id, job_version)

    return ApiResponse(
        message="文档上传成功，正在后台处理",
        data=DocumentResponse.model_validate(doc),
    )


@router.get("", summary="文档列表")
def list_documents(db: Session = Depends(get_db)) -> ApiResponse:
    """获取默认知识库下的所有文档及处理状态。"""
    kb = get_default_knowledge_base(db)
    docs = (
        db.query(Document)
        .filter(Document.knowledge_base_id == kb.id)
        .order_by(Document.created_at.desc())
        .all()
    )
    return ApiResponse(data=[DocumentResponse.model_validate(d) for d in docs])


@router.post("/rebuild", summary="重建默认知识库向量库")
def rebuild_documents(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ApiResponse:
    """
    清空默认知识库的 Chroma collection，并在后台根据 SQLite 文档记录重建全部向量。

    接口立即返回；文档状态可在列表中轮询查看。
    """
    kb = get_default_knowledge_base(db)
    rebuild_version = rebuild_knowledge_base(db, kb)
    background_tasks.add_task(rebuild_knowledge_base_by_id, kb.id, rebuild_version)
    docs = (
        db.query(Document)
        .filter(Document.knowledge_base_id == kb.id)
        .order_by(Document.created_at.desc())
        .all()
    )
    return ApiResponse(
        message="已开始后台重建向量库，请在文档列表查看进度",
        data=[DocumentResponse.model_validate(doc) for doc in docs],
    )


@router.post("/{doc_id}/rebuild", summary="重建单个文档向量")
def rebuild_single_document(doc_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    """删除指定文档旧向量，并根据原始上传文件重新解析入库。"""
    kb = get_default_knowledge_base(db)
    doc = (
        db.query(Document)
        .filter(Document.id == doc_id, Document.knowledge_base_id == kb.id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    rebuilt = rebuild_document(db, doc, kb)
    return ApiResponse(
        message="文档向量重建成功" if rebuilt.status == "ready" else "文档向量重建失败",
        data=DocumentResponse.model_validate(rebuilt),
    )


@router.delete("/{doc_id}", summary="删除文档")
def delete_document(doc_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    """删除文档及其向量数据与本地文件。"""
    kb = get_default_knowledge_base(db)
    doc = (
        db.query(Document)
        .filter(Document.id == doc_id, Document.knowledge_base_id == kb.id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    remove_document(db, doc, kb)
    return ApiResponse(message="文档已删除")
