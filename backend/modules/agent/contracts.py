"""引用核查的返回契约。

核查记录会跨进程边界被消费：写进 reports.verification、拼进 PDF 的校验记录、
再由前端结果条读取（`frontend/src/components/VerificationResult.jsx`）。
核查迁到 LangGraph 后，图节点之间也只通过这里的字段传递状态。

新增字段必须先进 `VerificationRecord`：`tests/test_agent_contract.py` 会断言
实际返回的键集合是它的子集，避免图里悄悄长出前端不认识的键。
"""

from __future__ import annotations

from typing import Any

from typing_extensions import NotRequired, TypedDict


class VerificationRecord(TypedDict):
    """一次核查的完整记录。凡是分支特有的字段都标成 NotRequired。"""

    status: str
    rounds: int
    initial_issues: int
    remaining_issues: list[dict[str, Any]]
    fixed: list[dict[str, Any]]
    deleted: int
    format_retries: int
    policy_version: int
    source_manifest: dict[str, Any]
    draft_text_sha256: str
    review_log: list[dict[str, Any]]
    case_fact_matches: list[dict[str, Any]]
    # v2 流程（检索规划 + 统一提示词）追加的可追溯字段。旧流程不写，故标 NotRequired。
    planner_version: NotRequired[int]
    report_prompt_version: NotRequired[int]
    retrieval: NotRequired[dict[str, Any]]
    case_facts: NotRequired[dict[str, Any]]
    knowledge_gaps: NotRequired[list[dict[str, Any]]]
    applicability: NotRequired[dict[str, Any]]
    # 报告流程与归档追加的派生字段（由 generation/service 写入）。
    missing_evidence_diseases: NotRequired[list[str]]
    diagnostic_status: NotRequired[str]
    delivery_scope: NotRequired[str]
    source_note_sha256: NotRequired[str]
    delivered_text_sha256: NotRequired[str]
    # 通过 / 交付后才写入
    final_text_sha256: NotRequired[str]
    reference_links: NotRequired[list[dict[str, Any]]]
    grounding: NotRequired[list[dict[str, Any]]]
    annotations: NotRequired[list[dict[str, Any]]]
    annotated_count: NotRequired[int]
    # 失败与拒答分支
    reason: NotRequired[str]
    failure_kind: NotRequired[str | None]
    failure_detail: NotRequired[str | None]
    regeneration_failure: NotRequired[str]
    # 过程标记
    stripped_citations: NotRequired[list[dict[str, Any]]]
    adjudicated: NotRequired[bool]
    regenerated: NotRequired[bool]
    local_cleanup: NotRequired[bool]


FIELDS = frozenset(VerificationRecord.__annotations__)

# 主路径每次都写的基础字段（`no_evidence_result` 是更短的早退形态，不在此列）。
BASE_FIELDS = frozenset({
    "status", "rounds", "initial_issues", "remaining_issues", "fixed", "deleted",
    "format_retries", "policy_version", "source_manifest", "draft_text_sha256",
    "review_log", "case_fact_matches",
})

# 交付正文（pass / rewritten）时必须齐全：前端结果条与 PDF 都读这些键。
DELIVERED_FIELDS = frozenset({
    "status", "rounds", "initial_issues", "fixed", "deleted", "review_log",
    "final_text_sha256", "reference_links",
})

# 拒答时必须给出原因，否则前端只能显示"校验未通过"。
REJECTED_FIELDS = frozenset({"status", "reason"})

# 校验故障必须带分类，拒答文案据此给用户不同的排查提示。
ERROR_FIELDS = frozenset({"status", "reason", "failure_kind"})
