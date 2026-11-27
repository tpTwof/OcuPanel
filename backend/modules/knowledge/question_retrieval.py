"""按检索计划执行检索：预算、去重、覆盖判断与一次补检。

调用方给出结构化计划，本模块负责把它真正落到索引上：

- 每个问题用「问题 + 少量关键病例特征」组合查询，不把病例全文拼进所有查询；
- 按病种、材料类型和适用条件筛选检索结果，被排除的条款保留原因；条款写明的前提
  与例外不构成排除理由，随证据进入提示词，由报告写明适用条件；
- 所有证据在请求内统一编号；补检新增证据追加编号，不重排已分配编号；
- 相同问题/查询/证据去重，查询数、耗时、证据条数都有上限，到上限就保留缺口；
- 检索工具故障与「没有相关证据」分开记录，不能伪装成成功检索。
"""

from __future__ import annotations

import hashlib
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from core import config
from modules.knowledge.metadata import (
    filter_evidence,
    resolve_topic,
    resolve_material_type,
    resolve_review_status,
)
from modules.knowledge.report_focus import topic_query
from modules.knowledge.service import get_retriever


@dataclass(frozen=True)
class RetrievalBudget:
    max_queries: int = 10
    max_seconds: float = 20.0
    max_evidence: int = 12
    supplemental_rounds: int = 1
    top_k: int = 12
    min_score: float = 0.35

    @classmethod
    def from_config(cls) -> "RetrievalBudget":
        return cls(
            max_queries=config.RETRIEVAL_MAX_QUERIES,
            max_seconds=config.RETRIEVAL_MAX_SECONDS,
            max_evidence=config.RETRIEVAL_MAX_EVIDENCE,
            supplemental_rounds=config.RETRIEVAL_SUPPLEMENTAL_ROUNDS,
            top_k=config.RAG_TOP_K,
            min_score=config.RAG_MIN_SCORE,
        )


@dataclass
class QuestionResult:
    question: str
    topic: str
    disease: str
    filters: dict[str, Any] = field(default_factory=dict)
    query: str = ""
    answered: bool = False
    gaps: list[str] = field(default_factory=list)
    failed: bool = False
    supplemented: bool = False
    excluded: list[dict[str, Any]] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "question": self.question, "topic": self.topic, "disease": self.disease,
            "query": self.query, "answered": self.answered, "gaps": list(self.gaps),
            "failed": self.failed, "supplemented": self.supplemented,
            "evidence_ids": list(self.evidence_ids),
            "excluded": self.excluded[:6],
        }


@dataclass
class RetrievalOutcome:
    status: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    questions: list[QuestionResult] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    queries: int = 0
    elapsed_ms: int = 0
    supplemental_rounds: int = 0
    budget_exhausted: bool = False

    @property
    def gaps(self) -> list[dict[str, Any]]:
        return [
            {"question": item.question, "topic": item.topic, "disease": item.disease,
             "answered": item.answered, "reasons": list(item.gaps)}
            for item in self.questions if not item.answered or item.gaps
        ]

    @property
    def unresolved(self) -> list[dict[str, Any]]:
        return [gap for gap in self.gaps if not gap["answered"]]

    def summary(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "queries": self.queries,
            "evidence_count": len(self.evidence),
            "failures": list(self.failures),
            "budget_exhausted": self.budget_exhausted,
            "supplemental_rounds": self.supplemental_rounds,
            "elapsed_ms": self.elapsed_ms,
            "questions": [item.summary() for item in self.questions],
            "gaps": self.gaps,
        }


def evidence_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    """可复核的证据快照：稳定 id、来源版本、内容哈希、正文摘要与适用条件。"""
    text = item.get("text", "")
    return {
        "id": item.get("id"), "source": item.get("source"), "title": item.get("title"),
        "section": item.get("section"), "version": item.get("version"),
        "url": item.get("url"), "content_hash": item.get("content_hash")
        or hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "material_type": resolve_material_type(item),
        "review_status": resolve_review_status(item),
        # 适用条件与「未核实」字段一起存档：报告当时的依据前提可以被复核。
        "applicability": dict(item.get("applicability") or {}),
        "applicability_unknown": list(item.get("applicability_unknown") or ()),
    }


def _next_index(evidence: Sequence[dict[str, Any]]) -> int:
    return max((int(item.get("index", 0)) for item in evidence), default=0) + 1


def _build_query(question: Any, features: str) -> str:
    parts = [question.question]
    if features:
        parts.append(features)
    return " ".join(part for part in parts if part)[:400]


def _supplemental_query(question: Any, disease: str, features: str) -> str:
    """补检只用明确缺口收窄查询，不重复原查询。"""
    topic_terms = topic_query(disease, question.topic) if disease else ""
    parts = [question.question, topic_terms, features]
    return " ".join(part for part in parts if part)[:400]


def _adopt(
    item: dict[str, Any], index: int, question: QuestionResult, *, supplemental: bool,
) -> dict[str, Any]:
    adopted = dict(item)
    adopted["index"] = index
    adopted["questions"] = [{"question": question.question, "topic": question.topic}]
    adopted["content_hash"] = item.get("content_hash") or hashlib.sha256(
        item.get("text", "").encode("utf-8")).hexdigest()
    adopted["material_type"] = resolve_material_type(item)
    adopted["review_status"] = resolve_review_status(item)
    adopted["snapshot"] = evidence_snapshot(adopted)
    if supplemental:
        adopted["supplemental"] = True
    return adopted


def _attach_question(item: dict[str, Any], question: QuestionResult) -> None:
    entries = item.setdefault("questions", [])
    if not any(entry.get("question") == question.question for entry in entries):
        entries.append({"question": question.question, "topic": question.topic})


def retrieve_for_plan(
    plan: Any,
    *,
    diseases: tuple[str, ...],
    retriever: Any | None = None,
    budget: RetrievalBudget | None = None,
    existing: Sequence[dict[str, Any]] = (),
    case_features: str = "",
) -> RetrievalOutcome:
    """执行检索计划并返回证据包、覆盖状态与失败记录。"""
    budget = budget or RetrievalBudget.from_config()
    evidence: list[dict[str, Any]] = [dict(item) for item in existing]
    seen_ids = {item["id"] for item in evidence}
    seen_queries: set[str] = set()
    questions: list[QuestionResult] = []
    failures: list[dict[str, Any]] = []
    queries = 0
    budget_exhausted = False
    started = time.monotonic()

    def elapsed() -> float:
        return time.monotonic() - started

    def can_query() -> bool:
        return queries < budget.max_queries and elapsed() < budget.max_seconds

    def has_room() -> bool:
        return len(evidence) < budget.max_evidence

    if not plan.need_retrieval:
        return RetrievalOutcome(status="not_needed")
    if not config.RAG_ENABLED:
        return RetrievalOutcome(status="disabled")

    if retriever is None:
        retriever = get_retriever()

    def run_search(result: QuestionResult, query: str) -> list[dict[str, Any]]:
        disease = result.disease or None
        return retriever.search(
            query, k=min(budget.top_k, max(budget.max_evidence, 1)),
            min_score=budget.min_score,
            boost=topic_query(result.disease, result.topic) if result.disease else "",
            disease=disease,
        )

    def absorb(result: QuestionResult, hits: list[dict[str, Any]], *, supplemental: bool) -> bool:
        """筛选、去重、采用；返回是否新增了证据。"""
        nonlocal budget_exhausted
        accepted, rejected = filter_evidence(
            hits, topic=result.topic, filters=result.filters, disease=result.disease or None,
        )
        result.excluded.extend(rejected)
        progressed = False
        for item in accepted:
            if resolve_topic(item) != result.topic:
                result.excluded.append({"id": item["id"], "reason": "topic_mismatch"})
                continue
            # 带 preconditions/exclusions 或未在筛选中核实的适用条件不是排除理由：
            # 条款保留，`applicability_unknown` 随证据进撰稿提示词，要求报告写明前提。
            if item["id"] in seen_ids:
                for stored in evidence:
                    if stored["id"] == item["id"]:
                        _attach_question(stored, result)
                        result.evidence_ids.append(item["id"])
                        break
                continue
            if not has_room():
                budget_exhausted = True
                break
            adopted = _adopt(item, _next_index(evidence), result, supplemental=supplemental)
            evidence.append(adopted)
            seen_ids.add(item["id"])
            result.evidence_ids.append(item["id"])
            progressed = True
        result.answered = bool(result.evidence_ids)
        if result.answered:
            result.gaps = [gap for gap in result.gaps if gap != "no_result"]
        return progressed

    for question in plan.questions:
        result = QuestionResult(
            question=question.question, topic=question.topic,
            disease=question.filters.get("disease") or "",
            filters=dict(question.filters),
        )
        questions.append(result)
        if not can_query() or not has_room():
            budget_exhausted = True
            result.gaps.append("budget_exhausted")
            continue
        result.query = _build_query(question, case_features)
        if result.query in seen_queries:
            result.gaps.append("duplicate_query")
            continue
        seen_queries.add(result.query)
        queries += 1
        try:
            hits = run_search(result, result.query)
        except Exception as exc:  # noqa: BLE001 - 故障要记录，不能当成「没有证据」
            print(f"[RAG] 规划检索失败：{type(exc).__name__}", file=sys.stderr)
            result.failed = True
            result.gaps.append("tool_error")
            failures.append({"question": result.question, "kind": "tool_error",
                             "detail": type(exc).__name__})
            continue
        absorb(result, hits, supplemental=False)
        if not result.answered:
            reason = result.excluded[0]["reason"] if result.excluded else "no_result"
            result.gaps.append(reason)

    # 缺口补检：只针对明确缺口，最多一轮，且不重复已执行查询。
    supplemental_rounds = 0
    for _ in range(max(0, budget.supplemental_rounds)):
        pending = [item for item in questions
                   if not item.answered and not item.failed
                   and "budget_exhausted" not in item.gaps
                   and "duplicate_query" not in item.gaps]
        if not pending:
            break
        progressed = False
        for result in pending:
            if not can_query() or not has_room():
                budget_exhausted = True
                break
            query = _supplemental_query(result, result.disease, case_features)
            if query in seen_queries:
                if "duplicate_query" not in result.gaps:
                    result.gaps.append("duplicate_query")
                continue
            seen_queries.add(query)
            queries += 1
            result.supplemented = True
            try:
                hits = run_search(result, query)
            except Exception as exc:  # noqa: BLE001
                print(f"[RAG] 补检失败：{type(exc).__name__}", file=sys.stderr)
                result.failed = True
                result.gaps.append("tool_error")
                failures.append({"question": result.question, "kind": "tool_error",
                                 "detail": type(exc).__name__})
                continue
            if absorb(result, hits, supplemental=True):
                progressed = True
            elif result.excluded:
                reason = result.excluded[0]["reason"]
                if reason not in result.gaps:
                    result.gaps.append(reason)
        supplemental_rounds += 1
        if not progressed:
            break

    attempted = queries
    if failures and attempted and all(item.failed for item in questions if item.query):
        status = "error"
    elif not evidence:
        status = "empty"
    elif any(not item.answered for item in questions):
        status = "partial"
    else:
        status = "ok"
    return RetrievalOutcome(
        status=status, evidence=evidence, questions=questions, failures=failures,
        queries=queries, elapsed_ms=int(elapsed() * 1000),
        supplemental_rounds=supplemental_rounds, budget_exhausted=budget_exhausted,
    )
