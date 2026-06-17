"""Pydantic 请求/响应模型。"""

from datetime import datetime

from pydantic import BaseModel, Field


# ---------- 知识库 ----------


class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    description: str | None
    collection_name: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------- 文档 ----------


class DocumentResponse(BaseModel):
    id: str
    knowledge_base_id: str
    filename: str
    file_type: str
    file_size: int
    status: str
    chunk_count: int
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------- 会话 ----------


class SessionCreate(BaseModel):
    title: str | None = Field("新对话", description="会话标题")


class SessionResponse(BaseModel):
    id: str
    knowledge_base_id: str
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------- 消息 ----------


class SourceItem(BaseModel):
    """检索命中的文档片段来源。"""
    content: str
    filename: str | None = None
    page: int | None = None
    document_id: str | None = None
    chunk_index: int | None = None


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    sources: list[SourceItem] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    """对话请求体。"""
    message: str = Field(..., min_length=1, description="用户输入的问题")
    stream: bool = Field(True, description="是否以 SSE 流式返回")


class ChatResponse(BaseModel):
    """非流式对话响应。"""
    answer: str
    sources: list[SourceItem]


class ChatStopRequest(BaseModel):
    """停止流式生成并持久化当前已生成内容。"""
    request_id: str = Field(..., min_length=1, description="本次 chat 请求的 request_id")
    content: str = Field("", description="前端已收到的 assistant 文本")
    sources: list[SourceItem] | None = Field(None, description="前端已收到的引用来源")


class ApiResponse(BaseModel):
    """统一成功响应包装。"""
    code: int = 0
    message: str = "success"
    data: object | None = None
