"""
FastAPI 应用入口。

启动方式（在 backend 目录下）：
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, documents, knowledge_base
from app.database import init_db
from app.request_context import setup_request_logging
from app.schemas import ApiResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库与数据目录。"""
    setup_request_logging()
    init_db()
    yield

app = FastAPI(
    title="知识库问答 API",
    description="基于 FastAPI + LangChain + Chroma + Qwen 的 RAG 多轮对话服务",
    version="1.0.0",
    lifespan=lifespan,
)

# 允许 Vue3 前端跨域访问（开发环境）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(knowledge_base.router)
app.include_router(documents.router)
app.include_router(chat.router)


@app.get("/health", tags=["系统"], summary="健康检查")
def health_check() -> ApiResponse:
    """服务存活探针，用于部署健康检查。"""
    return ApiResponse(message="ok", data={"status": "healthy"})
