"""RAG 对话链服务：历史感知检索 + Qwen 生成。"""

import json
import logging
import re
import time
from collections.abc import AsyncIterator

from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from app.config import get_settings
from app.schemas import SourceItem
from app.services.retrieval import aretrieve_documents, retrieve_documents
from app.services.retrieval_context import begin_retrieval, consume_retrieval_warnings

logger = logging.getLogger(__name__)

# RAG 回答：基于检索上下文生成答案
QA_SYSTEM_PROMPT = (
    "你是一个知识库问答助手。请严格根据以下检索到的上下文回答问题。\n"
    "规则：\n"
    "1. 只使用上下文中的信息作答，不要编造。\n"
    "2. 如果上下文中没有相关信息，请明确说「根据现有知识库内容，我无法找到相关信息」。\n"
    "3. 回答简洁准确，可使用 Markdown 格式。\n"
    "\n上下文：\n{context}"
)


def get_llm(streaming: bool = False) -> ChatTongyi:
    """创建通义千问 LLM 实例。"""
    settings = get_settings()
    return ChatTongyi(
        model=settings.qwen_model,
        dashscope_api_key=settings.dashscope_api_key,
        streaming=streaming,
    )


def _build_qa_chain(streaming: bool = False):
    """构建基于已检索 context 的回答链。"""
    llm = get_llm(streaming=streaming)
    qa_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", QA_SYSTEM_PROMPT),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
        ]
    )
    return create_stuff_documents_chain(llm, qa_prompt)


def db_messages_to_langchain(messages: list[tuple[str, str]]) -> list[BaseMessage]:
    """
    将数据库中的 (role, content) 列表转为 LangChain 消息格式。

    用于多轮对话时传入 chat_history。
    """
    result: list[BaseMessage] = []
    for role, content in messages:
        if role == "user":
            result.append(HumanMessage(content=content))
        elif role == "assistant":
            result.append(AIMessage(content=content))
    return result


def _truncate_snippet(text: str, max_len: int) -> str:
    """将引用文本截断到指定长度，超出部分以省略号结尾。"""
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "…"


def _normalize_chunk_index(chunk_index) -> int | None:
    """将 chunk_index 统一为 int，避免 str/int 导致去重失效。"""
    if chunk_index is None:
        return None
    try:
        return int(chunk_index)
    except (TypeError, ValueError):
        return None


def _normalize_document_id(document_id) -> str | None:
    """将 document_id 统一为 str。"""
    if document_id is None:
        return None
    text = str(document_id).strip()
    return text or None


def _content_fingerprint(content: str) -> str:
    """内容指纹：去除空白后取前缀，用于识别重叠分块的重复片段。"""
    normalized = re.sub(r"\s+", "", (content or "").strip())
    return normalized[:240]


def _source_dedup_key(meta: dict, content: str) -> tuple:
    """
    生成来源去重键：优先 document_id + chunk_index，否则回退到 filename + 内容前缀。
    """
    document_id = _normalize_document_id(meta.get("document_id"))
    chunk_index = _normalize_chunk_index(meta.get("chunk_index"))
    if document_id is not None and chunk_index is not None:
        return ("chunk", document_id, chunk_index)
    filename = meta.get("filename") or meta.get("source") or ""
    return ("text", filename, _content_fingerprint(content))


def normalize_source_items(sources: list[SourceItem]) -> list[SourceItem]:
    """
    对来源列表去重并截断内容（用于返回给前端或持久化前处理）。
    """
    settings = get_settings()
    max_len = settings.source_snippet_max_len
    seen_keys: set[tuple] = set()
    seen_fingerprints: set[str] = set()
    result: list[SourceItem] = []

    for item in sources:
        document_id = _normalize_document_id(item.document_id)
        chunk_index = _normalize_chunk_index(item.chunk_index)
        meta = {
            "document_id": document_id,
            "chunk_index": chunk_index,
            "filename": item.filename,
        }
        key = _source_dedup_key(meta, item.content)
        fingerprint = _content_fingerprint(item.content)
        if key in seen_keys or (fingerprint and fingerprint in seen_fingerprints):
            continue
        seen_keys.add(key)
        if fingerprint:
            seen_fingerprints.add(fingerprint)

        result.append(
            SourceItem(
                content=_truncate_snippet(item.content, max_len),
                filename=item.filename,
                page=item.page,
                document_id=document_id,
                chunk_index=chunk_index,
            )
        )
    return result


def extract_sources(documents: list[Document]) -> list[SourceItem]:
    """从检索到的 Document 列表提取引用来源（去重 + 截断）。"""
    raw: list[SourceItem] = []
    for doc in documents:
        meta = doc.metadata or {}
        raw.append(
            SourceItem(
                content=doc.page_content,
                filename=meta.get("filename") or meta.get("source"),
                page=meta.get("page"),
                document_id=_normalize_document_id(meta.get("document_id")),
                chunk_index=_normalize_chunk_index(meta.get("chunk_index")),
            )
        )
    return normalize_source_items(raw)


def chat(
    collection_name: str,
    question: str,
    chat_history: list[tuple[str, str]],
) -> tuple[str, list[SourceItem]]:
    """
    非流式对话：执行 RAG 链并返回完整答案与引用来源。

    Args:
        collection_name: 知识库对应的 Chroma collection
        question: 用户当前问题
        chat_history: 历史消息 [(role, content), ...]
    """
    retrieval_llm = get_llm(streaming=False)
    chain = _build_qa_chain(streaming=False)
    lc_history = db_messages_to_langchain(chat_history)

    start = time.perf_counter()
    context_docs = retrieve_documents(collection_name, question, lc_history, retrieval_llm)
    retrieval_elapsed = time.perf_counter() - start
    logger.info(
        "rag retrieval finished stream=false collection=%s docs=%s elapsed=%.3fs",
        collection_name,
        len(context_docs),
        retrieval_elapsed,
    )
    generation_start = time.perf_counter()
    answer = chain.invoke(
        {"input": question, "chat_history": lc_history, "context": context_docs}
    )
    logger.info(
        "rag generation finished stream=false collection=%s answer_len=%s elapsed=%.3fs",
        collection_name,
        len(answer),
        time.perf_counter() - generation_start,
    )
    sources = extract_sources(context_docs)
    return answer, sources


async def chat_stream(
    collection_name: str,
    question: str,
    chat_history: list[tuple[str, str]],
) -> AsyncIterator[str]:
    """
    流式对话：通过 astream_events 逐 token 输出 SSE 数据。

    事件格式（JSON 字符串）：
    - {"type": "token", "content": "..."}  — 增量文本
    - {"type": "sources", "data": [...]}     — 引用来源（结束时发送）
    - {"type": "done"}                       — 流结束标记
    """
    retrieval_llm = get_llm(streaming=False)
    chain = _build_qa_chain(streaming=True)
    lc_history = db_messages_to_langchain(chat_history)
    begin_retrieval()
    start = time.perf_counter()
    context_docs = await aretrieve_documents(
        collection_name, question, lc_history, retrieval_llm
    )
    for warning in consume_retrieval_warnings():
        yield json.dumps(
            {"type": "warning", **warning},
            ensure_ascii=False,
        )
    logger.info(
        "rag retrieval finished stream=true collection=%s docs=%s elapsed=%.3fs",
        collection_name,
        len(context_docs),
        time.perf_counter() - start,
    )

    input_data = {
        "input": question,
        "chat_history": lc_history,
        "context": context_docs,
    }

    token_count = 0
    generation_start = time.perf_counter()
    async for event in chain.astream_events(input_data, version="v2"):
        kind = event.get("event")

        # LLM 流式 token
        if kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if chunk and hasattr(chunk, "content") and chunk.content:
                token_count += 1
                yield json.dumps(
                    {"type": "token", "content": chunk.content},
                    ensure_ascii=False,
                )

    logger.info(
        "rag generation finished stream=true collection=%s token_events=%s elapsed=%.3fs",
        collection_name,
        token_count,
        time.perf_counter() - generation_start,
    )

    collected_sources = extract_sources(context_docs)
    if collected_sources:
        yield json.dumps(
            {
                "type": "sources",
                "data": [s.model_dump() for s in collected_sources],
            },
            ensure_ascii=False,
        )

    yield json.dumps({"type": "done"}, ensure_ascii=False)
