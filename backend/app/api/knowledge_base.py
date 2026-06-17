"""知识库 API（单知识库模式）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ApiResponse, KnowledgeBaseResponse
from app.services.knowledge_base_service import get_default_knowledge_base

router = APIRouter(prefix="/api/kb", tags=["知识库"])


@router.get("", summary="获取知识库信息")
def get_knowledge_base(db: Session = Depends(get_db)) -> ApiResponse:
    """
    获取系统唯一的默认知识库信息。

    知识库在应用启动时自动创建，无需手动新建。
    """
    kb = get_default_knowledge_base(db)
    return ApiResponse(data=KnowledgeBaseResponse.model_validate(kb))
