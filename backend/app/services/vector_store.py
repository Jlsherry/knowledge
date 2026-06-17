"""向量库服务：基于 Chroma 的文档存储与检索。"""

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import get_settings
from app.services.bm25_index import get_bm25_manager
from app.services.embedding import get_embeddings


def get_text_splitter() -> RecursiveCharacterTextSplitter:
    """创建文本分块器，按配置切分长文档。"""
    settings = get_settings()
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", "。", "！", "？", "；", " ", ""],
    )


def get_vector_store(collection_name: str) -> Chroma:
    """
    获取指定知识库对应的 Chroma 向量存储实例。

    每个知识库使用独立 collection，实现数据隔离。
    """
    settings = get_settings()
    return Chroma(
        collection_name=collection_name,
        embedding_function=get_embeddings(),
        persist_directory=str(settings.chroma_path),
    )


def add_documents_to_store(
    collection_name: str,
    documents: list[Document],
    document_id: str,
    filename: str,
    processing_version: int = 0,
) -> int:
    """
    将文档分块后写入向量库。

    为每个 chunk 附加 document_id、filename 元数据，便于溯源。
    返回写入的 chunk 数量。
    """
    splitter = get_text_splitter()
    chunks = splitter.split_documents(documents)

    for i, chunk in enumerate(chunks):
        chunk.metadata["document_id"] = document_id
        chunk.metadata["filename"] = filename
        chunk.metadata["chunk_index"] = i
        chunk.metadata["processing_version"] = int(processing_version)

    if not chunks:
        return 0

    vector_store = get_vector_store(collection_name)
    vector_store.add_documents(chunks)
    get_bm25_manager().add_chunks(collection_name, chunks)
    return len(chunks)


def get_retriever(collection_name: str):
    """
    创建检索器，返回 Top-K 相关文档块。

    检索策略由 RETRIEVAL_SEARCH_TYPE 控制：
    - similarity：纯向量相似度
    - mmr：最大边际相关性，在相关性与多样性之间平衡
    """
    settings = get_settings()
    vector_store = get_vector_store(collection_name)

    if settings.retrieval_search_type == "mmr":
        return vector_store.as_retriever(
            search_type="mmr",
            search_kwargs={
                "k": settings.retrieval_top_k,
                "fetch_k": settings.retrieval_fetch_k,
                "lambda_mult": settings.retrieval_lambda_mult,
            },
        )

    return vector_store.as_retriever(
        search_type="similarity",
        search_kwargs={"k": settings.retrieval_top_k},
    )


def delete_document_chunks(collection_name: str, document_id: str) -> None:
    """按 document_id 删除向量库中该文档的所有 chunk。"""
    vector_store = get_vector_store(collection_name)
    vector_store._collection.delete(where={"document_id": document_id})
    get_bm25_manager().remove_document(collection_name, document_id)


def clear_collection(collection_name: str) -> None:
    """清空指定 Chroma collection 中的全部 chunk。"""
    vector_store = get_vector_store(collection_name)
    existing = vector_store.get(include=[])
    ids = existing.get("ids") or []
    if ids:
        vector_store.delete(ids=ids)
    get_bm25_manager().clear(collection_name)
