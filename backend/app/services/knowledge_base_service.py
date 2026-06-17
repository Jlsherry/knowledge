"""默认知识库服务：系统仅使用一个知识库，启动时自动初始化。"""

import re

from sqlalchemy.orm import Session

from app.models import KnowledgeBase

# 固定名称，全局唯一
DEFAULT_KB_NAME = "默认知识库"
DEFAULT_KB_COLLECTION = "default_knowledge_base"

# Chroma collection 名只允许 ASCII 字母数字及 ._-
_CHROMA_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,510}[a-zA-Z0-9]$")


def _is_valid_chroma_collection(name: str) -> bool:
    """检查 collection 名是否符合 Chroma 命名规则。"""
    return bool(name and _CHROMA_NAME_PATTERN.match(name))


def ensure_default_knowledge_base(db: Session) -> KnowledgeBase:
    """
    确保默认知识库存在；不存在则自动创建。

    应用启动时调用，用户无需手动创建知识库。
    若已有知识库的 collection 名含中文等非法字符，自动修正为合法名称。
    """
    kb = db.query(KnowledgeBase).order_by(KnowledgeBase.created_at.asc()).first()
    if kb:
        if not _is_valid_chroma_collection(kb.collection_name):
            kb.collection_name = DEFAULT_KB_COLLECTION
            db.commit()
            db.refresh(kb)
        return kb

    kb = KnowledgeBase(
        name=DEFAULT_KB_NAME,
        description="系统默认知识库",
        collection_name=DEFAULT_KB_COLLECTION,
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return kb


def get_default_knowledge_base(db: Session) -> KnowledgeBase:
    """获取默认知识库，不存在时自动创建。"""
    return ensure_default_knowledge_base(db)
