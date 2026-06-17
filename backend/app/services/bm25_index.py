"""BM25 inverted index with in-memory cache, disk persistence, and incremental updates."""

from __future__ import annotations

import hashlib
import logging
import math
import pickle
import re
import threading
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.documents import Document

from app.config import get_settings

logger = logging.getLogger(__name__)

TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]{1,4}|[a-zA-Z0-9_]+")
INDEX_VERSION = 2

ChunkKey = tuple[str, int]


def chunk_fingerprint(
    document_id: str,
    chunk_index: int,
    text: str,
    processing_version: int = 0,
) -> str:
    """Stable fingerprint for one indexed chunk (id + index + version + content)."""
    payload = (
        f"{document_id}\x00{int(chunk_index)}\x00{int(processing_version)}\x00"
        f"{(text or '').strip()}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def aggregate_collection_fingerprint(fingerprints: Iterable[str]) -> str:
    """Hash of sorted chunk fingerprints representing the whole collection."""
    joined = "\n".join(sorted(fingerprints))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def tokenize_for_bm25(text: str) -> list[str]:
    """Tokenize mixed Chinese/English text for keyword retrieval."""
    tokens: list[str] = []
    for match in TOKEN_PATTERN.finditer((text or "").lower()):
        token = match.group(0)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            tokens.append(token)
            if len(token) > 1:
                tokens.extend(token[i : i + 2] for i in range(len(token) - 1))
            if len(token) > 2:
                tokens.extend(token[i : i + 3] for i in range(len(token) - 2))
        else:
            tokens.append(token)
    return tokens


def _chunk_key(document_id: str, chunk_index: int) -> ChunkKey:
    return document_id, int(chunk_index)


@dataclass
class BM25Chunk:
    document_id: str
    chunk_index: int
    filename: str | None
    page: int | None
    text: str
    tokens: list[str]
    fingerprint: str = ""
    tf: Counter[str] = field(default_factory=Counter)
    doc_len: int = 0

    @classmethod
    def from_document(cls, doc: Document) -> BM25Chunk | None:
        meta = doc.metadata or {}
        document_id = meta.get("document_id")
        chunk_index = meta.get("chunk_index")
        if document_id is None or chunk_index is None:
            return None

        text = (doc.page_content or "").strip()
        if not text:
            return None

        tokens = tokenize_for_bm25(text)
        if not tokens:
            return None

        page = meta.get("page")
        processing_version = int(meta.get("processing_version") or 0)
        return cls(
            document_id=str(document_id),
            chunk_index=int(chunk_index),
            filename=meta.get("filename") or meta.get("source"),
            page=int(page) if page is not None else None,
            text=text,
            tokens=tokens,
            fingerprint=chunk_fingerprint(
                str(document_id),
                int(chunk_index),
                text,
                processing_version,
            ),
            tf=Counter(tokens),
            doc_len=len(tokens),
        )

    def to_document(self, score: float | None = None) -> Document:
        metadata = {
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "filename": self.filename,
        }
        if self.page is not None:
            metadata["page"] = self.page
        if score is not None:
            metadata["bm25_score"] = score
        return Document(page_content=self.text, metadata=metadata)


@dataclass
class BM25Index:
    collection_name: str
    version: int = INDEX_VERSION
    chunks: dict[ChunkKey, BM25Chunk] = field(default_factory=dict)
    postings: dict[str, set[ChunkKey]] = field(default_factory=dict)
    total_len: int = 0
    collection_fingerprint: str = ""

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    def refresh_collection_fingerprint(self) -> str:
        self.collection_fingerprint = aggregate_collection_fingerprint(
            chunk.fingerprint for chunk in self.chunks.values()
        )
        return self.collection_fingerprint

    def _add_chunk(self, chunk: BM25Chunk) -> None:
        key = _chunk_key(chunk.document_id, chunk.chunk_index)
        if key in self.chunks:
            self._remove_key(key)

        self.chunks[key] = chunk
        self.total_len += chunk.doc_len
        for token in set(chunk.tokens):
            self.postings.setdefault(token, set()).add(key)

    def _remove_key(self, key: ChunkKey) -> None:
        chunk = self.chunks.pop(key, None)
        if not chunk:
            return

        self.total_len -= chunk.doc_len
        for token in set(chunk.tokens):
            posting = self.postings.get(token)
            if not posting:
                continue
            posting.discard(key)
            if not posting:
                self.postings.pop(token, None)

    def add_chunks(self, documents: Iterable[Document]) -> int:
        added = 0
        for doc in documents:
            chunk = BM25Chunk.from_document(doc)
            if not chunk:
                continue
            self._add_chunk(chunk)
            added += 1
        if added:
            self.refresh_collection_fingerprint()
        return added

    def remove_document(self, document_id: str) -> int:
        keys = [key for key in self.chunks if key[0] == str(document_id)]
        for key in keys:
            self._remove_key(key)
        if keys:
            self.refresh_collection_fingerprint()
        return len(keys)

    def clear(self) -> None:
        self.chunks.clear()
        self.postings.clear()
        self.total_len = 0
        self.refresh_collection_fingerprint()

    def search(
        self,
        query: str,
        top_k: int,
        *,
        k1: float,
        b: float,
    ) -> list[Document]:
        query_tokens = tokenize_for_bm25(query)
        if not query_tokens or not self.chunks:
            return []

        candidate_keys: set[ChunkKey] = set()
        for token in query_tokens:
            candidate_keys.update(self.postings.get(token, ()))

        if not candidate_keys:
            return []

        doc_count = self.chunk_count
        avgdl = self.total_len / doc_count if doc_count else 0.0

        scored: list[tuple[float, ChunkKey, BM25Chunk]] = []
        for key in candidate_keys:
            chunk = self.chunks[key]
            score = _score_chunk(query_tokens, chunk, self.postings, doc_count, avgdl, k1, b)
            if score > 0:
                scored.append((score, key, chunk))

        scored.sort(key=lambda item: (-item[0], item[1][0], item[1][1]))

        return [chunk.to_document(score=score) for score, _, chunk in scored[:top_k]]

    def build_from_chroma(self) -> int:
        """Rebuild the full index from the Chroma collection."""
        from app.services.vector_store import get_vector_store

        vector_store = get_vector_store(self.collection_name)
        raw = vector_store.get(include=["documents", "metadatas"])
        texts = raw.get("documents") or []
        metadatas = raw.get("metadatas") or []

        self.clear()
        documents = [
            Document(page_content=text, metadata=dict(metadata or {}))
            for text, metadata in zip(texts, metadatas, strict=False)
            if text
        ]
        added = self.add_chunks(documents)
        if added == 0:
            self.refresh_collection_fingerprint()
        return added


def _score_chunk(
    query_tokens: Sequence[str],
    chunk: BM25Chunk,
    postings: dict[str, set[ChunkKey]],
    doc_count: int,
    avgdl: float,
    k1: float,
    b: float,
) -> float:
    score = 0.0
    for token in query_tokens:
        tf = chunk.tf.get(token, 0)
        if tf <= 0:
            continue
        df = len(postings.get(token, ()))
        if df <= 0:
            continue
        idf = math.log(1 + (doc_count - df + 0.5) / (df + 0.5))
        denom = tf + k1 * (1 - b + b * chunk.doc_len / (avgdl or 1))
        score += idf * (tf * (k1 + 1)) / denom
    return score


class BM25IndexManager:
    """Per-collection BM25 index with lazy load, validation, and persistence."""

    def __init__(self) -> None:
        self._indexes: dict[str, BM25Index] = {}
        self._lock = threading.RLock()

    def _cache_path(self, collection_name: str) -> Path:
        settings = get_settings()
        cache_dir = settings.bm25_cache_path
        cache_dir.mkdir(parents=True, exist_ok=True)
        safe_name = collection_name.replace("/", "_")
        return cache_dir / f"{safe_name}.pkl"

    def _chroma_collection_fingerprint(self, collection_name: str) -> tuple[int, str]:
        from app.services.vector_store import get_vector_store

        vector_store = get_vector_store(collection_name)
        raw = vector_store.get(include=["documents", "metadatas"])
        texts = raw.get("documents") or []
        metadatas = raw.get("metadatas") or []

        fingerprints: list[str] = []
        for text, metadata in zip(texts, metadatas, strict=False):
            if not text:
                continue
            meta = metadata or {}
            document_id = meta.get("document_id")
            chunk_index = meta.get("chunk_index")
            if document_id is None or chunk_index is None:
                continue
            fingerprints.append(
                chunk_fingerprint(
                    str(document_id),
                    int(chunk_index),
                    text,
                    int(meta.get("processing_version") or 0),
                )
            )
        return len(fingerprints), aggregate_collection_fingerprint(fingerprints)

    def _validate_or_rebuild(self, index: BM25Index) -> BM25Index:
        try:
            chroma_count, chroma_fingerprint = self._chroma_collection_fingerprint(
                index.collection_name
            )
        except Exception:
            logger.exception(
                "failed to fingerprint chroma collection=%s",
                index.collection_name,
            )
            return index

        cache_fingerprint = index.collection_fingerprint
        if not cache_fingerprint:
            cache_fingerprint = index.refresh_collection_fingerprint()

        if index.chunk_count == chroma_count and cache_fingerprint == chroma_fingerprint:
            return index

        logger.warning(
            "bm25 cache out of sync collection=%s cache_chunks=%s chroma_chunks=%s "
            "cache_fp=%s chroma_fp=%s rebuilding",
            index.collection_name,
            index.chunk_count,
            chroma_count,
            cache_fingerprint[:12],
            chroma_fingerprint[:12],
        )
        index.build_from_chroma()
        self._save_to_disk(index)
        return index

    def _chroma_chunk_count(self, collection_name: str) -> int:
        count, _ = self._chroma_collection_fingerprint(collection_name)
        return count

    def _load_from_disk(self, collection_name: str) -> BM25Index | None:
        path = self._cache_path(collection_name)
        if not path.exists():
            return None
        try:
            with path.open("rb") as file:
                index = pickle.load(file)
            if not isinstance(index, BM25Index):
                return None
            if index.collection_name != collection_name or index.version != INDEX_VERSION:
                return None
            return index
        except Exception:
            logger.exception("failed to load bm25 cache collection=%s", collection_name)
            return None

    def _save_to_disk(self, index: BM25Index) -> None:
        path = self._cache_path(index.collection_name)
        tmp_path = path.with_suffix(".tmp")
        try:
            with tmp_path.open("wb") as file:
                pickle.dump(index, file, protocol=pickle.HIGHEST_PROTOCOL)
            tmp_path.replace(path)
        except Exception:
            logger.exception("failed to save bm25 cache collection=%s", index.collection_name)
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def get_index(self, collection_name: str) -> BM25Index:
        with self._lock:
            if collection_name in self._indexes:
                return self._indexes[collection_name]

            index = self._load_from_disk(collection_name)
            if index is None:
                index = BM25Index(collection_name=collection_name)
                try:
                    if self._chroma_chunk_count(collection_name) > 0:
                        index.build_from_chroma()
                        self._save_to_disk(index)
                except Exception:
                    logger.exception("failed to build bm25 index collection=%s", collection_name)
            else:
                index = self._validate_or_rebuild(index)

            self._indexes[collection_name] = index
            return index

    def add_chunks(self, collection_name: str, documents: Iterable[Document]) -> int:
        with self._lock:
            index = self.get_index(collection_name)
            added = index.add_chunks(documents)
            if added:
                self._save_to_disk(index)
            return added

    def remove_document(self, collection_name: str, document_id: str) -> int:
        with self._lock:
            index = self.get_index(collection_name)
            removed = index.remove_document(document_id)
            if removed:
                self._save_to_disk(index)
            return removed

    def clear(self, collection_name: str) -> None:
        with self._lock:
            index = self.get_index(collection_name)
            index.clear()
            self._save_to_disk(index)

    def rebuild(self, collection_name: str) -> int:
        with self._lock:
            index = BM25Index(collection_name=collection_name)
            count = index.build_from_chroma()
            self._indexes[collection_name] = index
            self._save_to_disk(index)
            return count

    def search(self, collection_name: str, query: str, top_k: int, *, k1: float, b: float) -> list[Document]:
        with self._lock:
            index = self.get_index(collection_name)
        return index.search(query, top_k, k1=k1, b=b)


_manager = BM25IndexManager()


def get_bm25_manager() -> BM25IndexManager:
    return _manager
