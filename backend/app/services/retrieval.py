"""Enhanced retrieval service: query rewrite, multi-query recall, and dedupe."""

import asyncio
from collections.abc import Sequence

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable

from app.config import get_settings
from app.services.bm25_retriever import bm25_search
from app.services.rerank import rerank_documents
from app.services.retrieval_context import mark_rerank_degraded
from app.services.vector_store import get_retriever


CONTEXTUALIZE_Q_SYSTEM_PROMPT = (
    "根据对话历史和最新的用户问题，将其改写为一个独立的、"
    "可用于文档检索的问题。不要回答问题，只需改写问题。"
    "如果问题已经独立完整，则原样返回。"
)

QUERY_EXPANSION_SYSTEM_PROMPT = (
    "你是知识库检索查询改写助手。请基于用户问题生成更适合文档检索的中文查询。"
    "要求：\n"
    "1. 不要回答问题。\n"
    "2. 保留关键实体、疾病名、文档术语、数值条件。\n"
    "3. 生成不同表达角度，避免重复。\n"
    "4. 每行一个查询，不要编号，不要解释。"
)


def _clean_query(text: str) -> str:
    """Normalize one generated query line."""
    return text.strip().strip("-* \t\r\n\"'`")


def _unique_queries(queries: Sequence[str], limit: int) -> list[str]:
    """Keep query order while removing duplicates and blanks."""
    seen: set[str] = set()
    result: list[str] = []
    for query in queries:
        normalized = _clean_query(query)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
        if len(result) >= limit:
            break
    return result


def _doc_key(doc: Document) -> tuple:
    """Build a stable dedupe key for retrieved chunks."""
    meta = doc.metadata or {}
    document_id = meta.get("document_id")
    chunk_index = meta.get("chunk_index")
    if document_id is not None and chunk_index is not None:
        return ("chunk", document_id, chunk_index)
    source = meta.get("filename") or meta.get("source") or ""
    return ("text", source, doc.page_content[:160])


def _dedupe_documents(documents: Sequence[Document], limit: int) -> list[Document]:
    """Keep first-seen chunks after multi-query retrieval."""
    seen: set[tuple] = set()
    result: list[Document] = []
    for doc in documents:
        key = _doc_key(doc)
        if key in seen:
            continue
        seen.add(key)
        result.append(doc)
        if len(result) >= limit:
            break
    return result


def _rrf_fuse(
    ranked_lists: Sequence[Sequence[Document]],
    limit: int,
    rrf_k: int,
) -> list[Document]:
    """Fuse multiple ranked result lists with Reciprocal Rank Fusion."""
    scores: dict[tuple, float] = {}
    docs_by_key: dict[tuple, Document] = {}
    first_seen: dict[tuple, int] = {}
    order = 0

    for ranked_docs in ranked_lists:
        for rank, doc in enumerate(ranked_docs, start=1):
            key = _doc_key(doc)
            if key not in docs_by_key:
                docs_by_key[key] = doc
                first_seen[key] = order
                order += 1
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)

    ranked_keys = sorted(
        scores,
        key=lambda key: (-scores[key], first_seen[key]),
    )

    fused: list[Document] = []
    for key in ranked_keys[:limit]:
        doc = docs_by_key[key]
        doc.metadata = dict(doc.metadata or {})
        doc.metadata["rrf_score"] = scores[key]
        fused.append(doc)
    return fused


def _contextualize_question(
    question: str,
    chat_history: list[BaseMessage],
    llm: Runnable,
) -> str:
    """Rewrite a follow-up question into a standalone retrieval query."""
    if not chat_history:
        return question

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", CONTEXTUALIZE_Q_SYSTEM_PROMPT),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
        ]
    )
    chain = prompt | llm | StrOutputParser()
    rewritten = chain.invoke({"input": question, "chat_history": chat_history})
    return _clean_query(rewritten) or question


async def _acontextualize_question(
    question: str,
    chat_history: list[BaseMessage],
    llm: Runnable,
) -> str:
    """Async variant of question contextualization."""
    if not chat_history:
        return question

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", CONTEXTUALIZE_Q_SYSTEM_PROMPT),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
        ]
    )
    chain = prompt | llm | StrOutputParser()
    rewritten = await chain.ainvoke({"input": question, "chat_history": chat_history})
    return _clean_query(rewritten) or question


def _expand_queries(question: str, llm: Runnable, count: int) -> list[str]:
    """Generate alternative retrieval queries for semantic recall."""
    if count <= 0:
        return []

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", QUERY_EXPANSION_SYSTEM_PROMPT),
            ("human", "用户问题：{question}\n请生成 {count} 个检索查询。"),
        ]
    )
    chain = prompt | llm | StrOutputParser()
    raw = chain.invoke({"question": question, "count": count})
    return _unique_queries(raw.splitlines(), count)


async def _aexpand_queries(question: str, llm: Runnable, count: int) -> list[str]:
    """Async variant of query expansion."""
    if count <= 0:
        return []

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", QUERY_EXPANSION_SYSTEM_PROMPT),
            ("human", "用户问题：{question}\n请生成 {count} 个检索查询。"),
        ]
    )
    chain = prompt | llm | StrOutputParser()
    raw = await chain.ainvoke({"question": question, "count": count})
    return _unique_queries(raw.splitlines(), count)


def build_retrieval_queries(
    question: str,
    chat_history: list[BaseMessage],
    llm: Runnable,
) -> list[str]:
    """Build the ordered query set used by enhanced retrieval."""
    settings = get_settings()
    standalone_question = _contextualize_question(question, chat_history, llm)

    query_budget = max(1, settings.retrieval_multi_query_count + 2)
    queries = [question, standalone_question]
    if settings.retrieval_multi_query_enabled:
        queries.extend(
            _expand_queries(
                standalone_question,
                llm,
                settings.retrieval_multi_query_count,
            )
        )
    return _unique_queries(queries, query_budget)


async def abuild_retrieval_queries(
    question: str,
    chat_history: list[BaseMessage],
    llm: Runnable,
) -> list[str]:
    """Async variant of retrieval query construction."""
    settings = get_settings()
    standalone_question = await _acontextualize_question(question, chat_history, llm)

    query_budget = max(1, settings.retrieval_multi_query_count + 2)
    queries = [question, standalone_question]
    if settings.retrieval_multi_query_enabled:
        queries.extend(
            await _aexpand_queries(
                standalone_question,
                llm,
                settings.retrieval_multi_query_count,
            )
        )
    return _unique_queries(queries, query_budget)


def retrieve_documents(
    collection_name: str,
    question: str,
    chat_history: list[BaseMessage],
    llm: Runnable,
) -> list[Document]:
    """Retrieve documents with original, rewritten, and expanded queries."""
    settings = get_settings()
    retriever = get_retriever(collection_name)
    queries = build_retrieval_queries(question, chat_history, llm)

    candidate_limit = (
        settings.rerank_candidate_limit
        if settings.rerank_enabled
        else settings.retrieval_final_k
    )
    ranked_lists: list[list[Document]] = []

    for query in queries:
        ranked_lists.append(retriever.invoke(query))
        if settings.hybrid_search_enabled:
            ranked_lists.append(bm25_search(collection_name, query, settings.bm25_top_k))

    candidates = (
        _rrf_fuse(ranked_lists, candidate_limit, settings.rrf_k)
        if settings.hybrid_search_enabled
        else _dedupe_documents(
            [doc for ranked_docs in ranked_lists for doc in ranked_docs],
            candidate_limit,
        )
    )
    if settings.rerank_enabled:
        docs, degraded = rerank_documents(queries[0], candidates)
        if degraded:
            mark_rerank_degraded()
        return docs
    return candidates


async def aretrieve_documents(
    collection_name: str,
    question: str,
    chat_history: list[BaseMessage],
    llm: Runnable,
) -> list[Document]:
    """Async retrieve documents with original, rewritten, and expanded queries."""
    settings = get_settings()
    retriever = get_retriever(collection_name)
    queries = await abuild_retrieval_queries(question, chat_history, llm)

    candidate_limit = (
        settings.rerank_candidate_limit
        if settings.rerank_enabled
        else settings.retrieval_final_k
    )
    ranked_lists: list[list[Document]] = []

    for query in queries:
        ranked_lists.append(await retriever.ainvoke(query))
        if settings.hybrid_search_enabled:
            bm25_docs = await asyncio.to_thread(
                bm25_search,
                collection_name,
                query,
                settings.bm25_top_k,
            )
            ranked_lists.append(bm25_docs)

    candidates = (
        _rrf_fuse(ranked_lists, candidate_limit, settings.rrf_k)
        if settings.hybrid_search_enabled
        else _dedupe_documents(
            [doc for ranked_docs in ranked_lists for doc in ranked_docs],
            candidate_limit,
        )
    )
    if settings.rerank_enabled:
        docs, degraded = await asyncio.to_thread(rerank_documents, queries[0], candidates)
        if degraded:
            mark_rerank_degraded()
        return docs
    return candidates
