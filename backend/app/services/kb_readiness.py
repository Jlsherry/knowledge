"""Knowledge base readiness checks before chat."""

from sqlalchemy.orm import Session

from app.errors import DOCS_PROCESSING, KB_EMPTY, KB_NOT_READY, raise_api_error
from app.models import Document


def ensure_kb_ready_for_chat(db: Session, knowledge_base_id: str) -> None:
    """
    Validate that the knowledge base can serve RAG chat.

    Raises HTTPException with structured ``detail`` when not ready.
    """
    docs = (
        db.query(Document)
        .filter(Document.knowledge_base_id == knowledge_base_id)
        .all()
    )

    if not docs:
        raise_api_error(KB_EMPTY, status_code=409)

    ready_count = sum(1 for doc in docs if doc.status == "ready")
    processing_count = sum(1 for doc in docs if doc.status in ("pending", "processing"))

    if ready_count == 0 and processing_count > 0:
        raise_api_error(DOCS_PROCESSING, status_code=409)

    if ready_count == 0:
        raise_api_error(KB_NOT_READY, status_code=409)
