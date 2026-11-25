from __future__ import annotations
from typing import Any, TYPE_CHECKING
if TYPE_CHECKING:
    from .retrieval import Retriever
import threading
import sys
from utils import config
_RETRIEVERS: dict[bool, Retriever] = {}
_RETRIEVER_LOCK = threading.Lock()


def get_retriever(graph_enabled: bool | None = None) -> Retriever:
    from .retrieval import Retriever

    enabled = config.GRAPH_RAG_ENABLED if graph_enabled is None else graph_enabled
    with _RETRIEVER_LOCK:
        if enabled not in _RETRIEVERS:
            _RETRIEVERS[enabled] = Retriever.from_corpus(graph_enabled=enabled)
        return _RETRIEVERS[enabled]


def retrieve_evidence(query: str, boost: str = '', disease: str | None = None) -> list[dict[str, Any]]:
    """检索带出处的证据片段；任何异常都退化为「不注入」，不影响报告生成。

    给出 disease 时按该病种报告必须回答的方面分别检索再合并（见
    retrieve_report_evidence），未给出时按单条查询检索。
    """
    if disease:
        return retrieve_report_evidence(query, disease, boost=boost)
    evidence, _ = retrieve_with_status(query, boost)
    return evidence


def retrieve_report_evidence(
    query: str, disease: str, boost: str = '',
) -> list[dict[str, Any]]:
    """按报告必须回答的方面分别检索，合并为一个证据包。

    单条查询只会让诊断类条款占满结果，判读与随访类条款被长病例文本稀释。
    这里每个方面只用自己的主题词做检索——把病例全文拼进主题查询时，
    病例里反复出现的「眼压/视野/RNFL」会再次盖过主题词，四个方面都返回同一批
    诊断条款，实测「目标眼压」仍排第 6 而被截断。病例相关性与病种归属分别由
    RAG_MIN_SCORE 和 disease 过滤保证。

    合并按「轮次」取：先取各方面第 1 名，再取第 2 名，以此类推，
    这样每个方面至少贡献一条，不会因为前面方面的条款多就把后面的方面挤空。
    """
    from knowledge.report_focus import report_topics

    topics = report_topics(disease)
    if not topics:
        return retrieve_evidence(query, boost=boost, disease=disease)
    try:
        retriever = get_retriever()
        ranked: list[list[dict[str, Any]]] = [
            retriever.search(
                topic, k=config.RAG_TOP_K, min_score=config.RAG_MIN_SCORE,
                boost=f"{boost} {topic}".strip(), disease=disease,
            )
            for topic in topics
        ]
    except Exception as exc:  # noqa: BLE001 - 检索失败不该让整条链路 500
        print(f"[RAG] 报告检索失败，本次不注入证据：{exc}", file=sys.stderr)
        return []

    merged: dict[str, dict[str, Any]] = {}
    depth = max((len(items) for items in ranked), default=0)
    for position in range(depth):
        for items in ranked:
            if position < len(items):
                merged.setdefault(items[position]["id"], items[position])
        if len(merged) >= config.RAG_TOP_K:
            break
    return list(merged.values())[:config.RAG_TOP_K]


def retrieve_with_status(query: str, boost: str = '', *, graph_enabled: bool | None = None,
                         disease: str | None = None) -> tuple[list[dict[str, Any]], dict[str, str]]:
    if not config.RAG_ENABLED:
        return [], {"result": "disabled", "graph": "disabled"}
    enabled = config.GRAPH_RAG_ENABLED if graph_enabled is None else graph_enabled
    graph = "unavailable" if enabled else "disabled"
    try:
        retriever = get_retriever(enabled)
        if retriever.graph_available:
            graph = "ready"
        evidence = retriever.search(
            query, k=config.RAG_TOP_K, min_score=config.RAG_MIN_SCORE, boost=boost, disease=disease,
        )
    except Exception as exc:  # noqa: BLE001 - 检索失败不该让整条链路 500
        print(f"[RAG] 检索失败，本次不注入证据：{exc}", file=sys.stderr)
        return [], {"result": "error", "graph": graph}
    return evidence, {"result": "found" if evidence else "empty", "graph": graph}
