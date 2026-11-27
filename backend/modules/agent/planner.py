"""检索规划 Agent：把病例事实转成结构化的检索问题。

职责边界：
- Agent 决定是否需要外部依据、要回答哪些问题；
- 代码校验字段（主题枚举、问题数量、病种与来源类型、引用的事实 id），
  规划失败时退回保守的按病种计划并记录状态，不静默跳过该检索的内容；
- 本模块不执行检索、不撰稿、不下诊断。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from core import config
from modules.knowledge.metadata import CARE_STAGES, MATERIAL_TYPES, TOPICS
from modules.agent.prompts.planner import (
    MAX_QUESTION_CHARS,
    MAX_REASON_CHARS,
    PLANNER_SYSTEM,
    PLANNER_VERSION,
    build_planner_prompt,
)
from modules.agent.tools.json_response import parse_json

if TYPE_CHECKING:  # 只用于类型标注，避免 agent 反向依赖报告模块的实现
    from modules.report.case_facts import CaseFacts

MAX_MISSING_INFORMATION = 8
TOPIC_LABELS = {
    "diagnosis": "诊断评估", "interpretation": "检查判读", "examination": "检查方法",
    "differential": "鉴别诊断", "treatment": "处置建议", "followup": "随访监测",
    "education": "患者教育",
}
DISEASE_LABELS_ZH = {
    "glaucoma": "青光眼",
    "diabetic_retinopathy": "糖尿病视网膜病变",
    "age_related_macular_degeneration": "年龄相关性黄斑变性",
}
# 规划不可用时的保守覆盖顺序：先诊断与判读，再随访，最后处置。
FALLBACK_TOPICS = ("diagnosis", "interpretation", "followup", "treatment", "examination")
# 影像模型输出必须检索判读依据，不能只靠病例事实成稿。
MODEL_OUTPUT_REQUIRES_RETRIEVAL = True


@dataclass(frozen=True)
class RetrievalQuestion:
    question: str
    topic: str
    case_fact_ids: tuple[str, ...] = ()
    filters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalPlan:
    need_retrieval: bool
    reason: str
    questions: tuple[RetrievalQuestion, ...] = ()
    missing_information: tuple[str, ...] = ()
    status: str = "ok"
    version: int = PLANNER_VERSION

    def summary(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status,
            "need_retrieval": self.need_retrieval,
            "reason": self.reason,
            "questions": [
                {
                    "question": item.question, "topic": item.topic,
                    "case_fact_ids": list(item.case_fact_ids), "filters": dict(item.filters),
                }
                for item in self.questions
            ],
            "missing_information": list(self.missing_information),
        }


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected a non-empty string")
    return value.strip()[:limit]


def _text_list(value: Any, limit: int) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("Expected a list of strings")
    items = []
    for item in value:
        if isinstance(item, str) and item.strip():
            items.append(item.strip()[:limit])
    return tuple(items)


def _parse_filters(value: Any, diseases: tuple[str, ...]) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("filters must be an object")
    filters: dict[str, Any] = {}
    disease = value.get("disease")
    if disease:
        if not isinstance(disease, str) or disease.strip() not in diseases:
            raise ValueError("filters.disease must be one of the analyzed diseases")
        filters["disease"] = disease.strip()
    elif len(diseases) > 1:
        raise ValueError("filters.disease is required for multi-disease cases")
    for key in ("population", "region"):
        raw = value.get(key)
        if raw in (None, ""):
            continue
        if not isinstance(raw, str):
            raise ValueError(f"filters.{key} must be a string")
        filters[key] = raw.strip()[:120]
    stage = value.get("care_stage")
    if stage:
        if not isinstance(stage, str) or stage.strip().lower() not in CARE_STAGES:
            raise ValueError("filters.care_stage must be one of " + ", ".join(CARE_STAGES))
        filters["care_stage"] = stage.strip().lower()
    material_types = value.get("material_types")
    if material_types:
        if not isinstance(material_types, list) or any(
                not isinstance(item, str) or item not in MATERIAL_TYPES for item in material_types):
            raise ValueError("filters.material_types contains unsupported values")
        filters["material_types"] = list(dict.fromkeys(material_types))
    return filters


def parse_plan(
    payload: Any,
    *,
    fact_ids: tuple[str, ...],
    diseases: tuple[str, ...],
    max_questions: int,
) -> RetrievalPlan:
    """校验规划响应。字段不合约定时抛 ValueError，由调用方退回保守计划。"""
    if not isinstance(payload, dict):
        raise ValueError("plan must be a JSON object")
    need_retrieval = payload.get("need_retrieval")
    if not isinstance(need_retrieval, bool):
        raise ValueError("need_retrieval must be a boolean")
    reason = _text(payload.get("reason"), MAX_REASON_CHARS)

    raw_questions = payload.get("questions")
    if raw_questions is None:
        raw_questions = []
    if not isinstance(raw_questions, list):
        raise ValueError("questions must be a list")
    if len(raw_questions) > max_questions:
        raise ValueError(f"questions exceeds the limit of {max_questions}")
    if need_retrieval != bool(raw_questions):
        raise ValueError("need_retrieval and questions disagree")

    known_facts = set(fact_ids)
    questions: list[RetrievalQuestion] = []
    for raw in raw_questions:
        if not isinstance(raw, dict):
            raise ValueError("each question must be an object")
        topic = raw.get("topic")
        if topic not in TOPICS:
            raise ValueError("question.topic must be one of " + ", ".join(TOPICS))
        question = _text(raw.get("question"), MAX_QUESTION_CHARS)
        raw_ids = raw.get("case_fact_ids") or []
        if not isinstance(raw_ids, list):
            raise ValueError("case_fact_ids must be a list")
        # 自造的 id 不能执行，也不能静默当成有效触发依据：过滤掉由记录反映。
        case_fact_ids = tuple(item for item in raw_ids if isinstance(item, str) and item in known_facts)
        filters = _parse_filters(raw.get("filters"), diseases)
        if "disease" not in filters and len(diseases) == 1:
            filters["disease"] = diseases[0]
        questions.append(RetrievalQuestion(
            question=question, topic=topic, case_fact_ids=case_fact_ids, filters=filters,
        ))

    missing = _text_list(payload.get("missing_information"), 200)[:MAX_MISSING_INFORMATION]
    return RetrievalPlan(
        need_retrieval=need_retrieval, reason=reason,
        questions=tuple(questions), missing_information=missing,
    )


def fallback_plan(
    facts: "CaseFacts", diseases: tuple[str, ...], *, max_questions: int, reason: str,
) -> RetrievalPlan:
    """规划不可用时的保守计划：按病种覆盖诊断、判读、随访等主题。"""
    has_clinical_input = bool(facts.facts)
    if not diseases or not has_clinical_input:
        return RetrievalPlan(
            need_retrieval=False, reason=reason, status="fallback",
            missing_information=tuple(fact.text for fact in facts.missing)[:MAX_MISSING_INFORMATION],
        )
    candidates: list[tuple[str, str]] = []
    for topic in FALLBACK_TOPICS:
        for disease in diseases:
            candidates.append((disease, topic))
    questions = tuple(
        RetrievalQuestion(
            question=f"{DISEASE_LABELS_ZH.get(disease, disease)}：本病例的{TOPIC_LABELS[topic]}需要哪些依据？",
            topic=topic, filters={"disease": disease},
        )
        for disease, topic in candidates[:max_questions]
    )
    return RetrievalPlan(
        need_retrieval=True,
        reason=f"{reason}；已退回按病种保守检索，并记录为回退计划。",
        questions=questions, status="fallback",
        missing_information=tuple(fact.text for fact in facts.missing)[:MAX_MISSING_INFORMATION],
    )


class RetrievalPlanner:
    name = "retrieval_planner"
    role_description = "判断是否需要外部依据并制定结构化检索计划"

    def __init__(self, llm_call: Callable[..., str]) -> None:
        self.llm_call = llm_call

    def plan(self, facts: "CaseFacts", diseases: tuple[str, ...]) -> RetrievalPlan:
        diseases = tuple(diseases)
        max_questions = config.RETRIEVAL_PLAN_MAX_QUESTIONS
        if not facts.facts:
            return RetrievalPlan(need_retrieval=False, reason="没有可整理的病例事实，不检索。")
        prompt = build_planner_prompt(facts.prompt_block(), diseases, max_questions)
        raw = self.llm_call(prompt, system=PLANNER_SYSTEM, temperature=0.0)
        if not raw or raw.startswith("Error:"):
            print("[PLAN] 检索规划模型调用失败，退回保守计划", file=sys.stderr)
            return fallback_plan(
                facts, diseases, max_questions=max_questions,
                reason="规划模型调用失败",
            )
        try:
            plan = parse_plan(
                parse_json(raw), fact_ids=facts.fact_ids, diseases=diseases,
                max_questions=max_questions,
            )
            if MODEL_OUTPUT_REQUIRES_RETRIEVAL and not plan.need_retrieval and facts.has_model_output:
                raise ValueError("imaging model output requires external criteria")
            return plan
        except ValueError as exc:
            # 记录具体校验原因，便于区分「格式错误」与「故意不检索」。
            print(f"[PLAN] 规划响应不合约定（{exc}），退回保守计划", file=sys.stderr)
            return fallback_plan(
                facts, diseases, max_questions=max_questions,
                reason=f"规划响应不合约定：{str(exc)[:120]}",
            )
