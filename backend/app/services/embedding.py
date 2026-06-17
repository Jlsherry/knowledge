"""Embedding 服务：封装 DashScope text-embedding-v3。"""

from langchain_community.embeddings import DashScopeEmbeddings

from app.config import get_settings


def get_embeddings() -> DashScopeEmbeddings:
    """
    获取 DashScope Embedding 单例。

    使用 text-embedding-v3 将文本块转为向量，供 Chroma 检索使用。
    """
    settings = get_settings()
    return DashScopeEmbeddings(
        model=settings.embedding_model,
        dashscope_api_key=settings.dashscope_api_key,
    )
