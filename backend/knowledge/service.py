from __future__ import annotations
from typing import Any, TYPE_CHECKING
if TYPE_CHECKING:
    from .retrieval import Retriever
import threading
import sys
from utils import config
_RETRIEVER = None
_RETRIEVER_LOCK = threading.Lock()
def get_retriever() -> Retriever:
    global _RETRIEVER
    if _RETRIEVER is None:
        with _RETRIEVER_LOCK:
            if _RETRIEVER is None:
                from knowledge.retrieval import Retriever

                _RETRIEVER = Retriever.from_corpus()
                print(f"[RAG] 语料已加载：{_RETRIEVER.size} 个片段", file=sys.stderr)
    return _RETRIEVER

def retrieve_evidence(query: str, boost: str = '') -> list[dict[str, Any]]:
    """检索带出处的证据片段；任何异常都退化为「不注入」，不影响报告生成。"""
    if not config.RAG_ENABLED:
        return []
    try:
        return get_retriever().search(
            query, k=config.RAG_TOP_K, min_score=config.RAG_MIN_SCORE, boost=boost
        )
    except Exception as exc:  # noqa: BLE001 - 检索失败不该让整条链路 500
        print(f"[RAG] 检索失败，本次不注入证据：{exc}", file=sys.stderr)
        return []
