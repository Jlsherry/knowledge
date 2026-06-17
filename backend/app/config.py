"""应用配置模块：从 .env 文件加载环境变量。"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend 根目录（app 的上级）
BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """全局配置项，对应 .env 中的变量。"""

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    dashscope_api_key: str
    qwen_model: str = "qwen-plus"
    embedding_model: str = "text-embedding-v3"

    database_url: str = "sqlite:///./data/app.db"
    chroma_persist_dir: str = "./data/chroma"
    upload_dir: str = "./data/uploads"
    bm25_cache_dir: str = "./data/bm25"

    chunk_size: int = 800
    chunk_overlap: int = 120
    retrieval_top_k: int = 5
    # 检索方式：similarity（纯相似度）/ mmr（最大边际相关性，减少重复 chunk）
    retrieval_search_type: str = "mmr"
    retrieval_fetch_k: int = 20
    retrieval_lambda_mult: float = 0.5
    # 多路召回：原问题 + 历史改写问题 + 若干扩展查询，合并去重后进入生成
    retrieval_multi_query_enabled: bool = True
    retrieval_multi_query_count: int = 2
    retrieval_final_k: int = 6
    # 混合检索：向量召回 + BM25 关键词召回，并使用 RRF 融合排名
    hybrid_search_enabled: bool = True
    bm25_top_k: int = 20
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    rrf_k: int = 60
    # DashScope rerank：对多路召回候选进行相关性重排序
    rerank_enabled: bool = True
    rerank_model: str = "gte-rerank-v2"
    rerank_candidate_limit: int = 20
    rerank_top_n: int = 5
    # 引用来源 snippet 最大字符数（建议 300~500）
    source_snippet_max_len: int = 400
    max_history_turns: int = 5

    @property
    def chroma_path(self) -> Path:
        """Chroma 持久化目录的绝对路径。"""
        path = Path(self.chroma_persist_dir)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return path

    @property
    def upload_path(self) -> Path:
        """上传文件存储目录的绝对路径。"""
        path = Path(self.upload_dir)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return path

    @property
    def bm25_cache_path(self) -> Path:
        """BM25 索引缓存目录的绝对路径。"""
        path = Path(self.bm25_cache_dir)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return path

    @property
    def database_path(self) -> str:
        """将相对 SQLite 路径转为绝对路径。"""
        if self.database_url.startswith("sqlite:///./"):
            rel = self.database_url.replace("sqlite:///./", "")
            abs_path = BACKEND_ROOT / rel
            return f"sqlite:///{abs_path.as_posix()}"
        return self.database_url


def get_settings() -> Settings:
    """获取配置对象。不使用缓存，确保 .env 修改后重启即生效。"""
    return Settings()
