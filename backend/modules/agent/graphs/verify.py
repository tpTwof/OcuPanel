"""引用核查的控制流（LangGraph）。

迁移前这段逻辑是一个 220 行的 `for`/`if` 嵌套：首轮核查 → 来源仲裁 → 有限轮
重写 → 复核 → 疑似不成文就整篇重生成 → 局部清理 → 标注交付或拒答。分支多、
早退多，读一遍要来回跳。

这里把它拆成显式状态机：每个节点只做一件事，走到哪一步由路由函数按状态决定。
**判定规则、轮数上限、字段写入与迁移前逐条对应**——`tests/test_verifier.py`
原有的用例就是这次迁移的等价性证明，任何分支语义变化都会在那里红。

设计约束（不要在"优化"时改动）：
- 核查调用失败（`verify` 返回 None）一律进入 `error` 终态，绝不当成通过；
- 整篇重生成最多一次；
- 轮数用显式计数器，不依赖框架的 recursion_limit 兜底；
- 标注交付只适用于「资料未覆盖」，与资料冲突或编造数值仍然拒答。
"""

from __future__ import annotations

import re
import sys
from typing import Any, Callable

from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from core import config
from modules.agent.tools.annotation import annotate_unverified, unannotated
from modules.agent.tools.evidence import strip_unknown_citations
from modules.agent.tools.text_revision import (
    apply_replacements,
    content_len,
    omit_local_issues,
)
from modules.agent.tools.verification_audit import (
    case_fragments,
    reference_links,
    source_manifest,
    text_digest,
)

MAX_ISSUES_PER_ROUND = 12


class VerifyState(TypedDict, total=False):
    """图里流转的状态。字段与 `contracts.VerificationRecord` 的语义一一对应。"""

    text: str
    issues: list[dict[str, Any]] | None
    round: int
    regen_used: bool
    report: dict[str, Any]
    final_text: str | None
    outcome: str


def run_verification(
    verifier: Any,
    text: str,
    evidence: list[dict[str, Any]],
    *,
    max_rounds: int = 2,
    regenerate: Callable[[list[dict[str, Any]]], str] | None = None,
    max_issues_per_round: int = MAX_ISSUES_PER_ROUND,
) -> tuple[str | None, dict[str, Any]]:
    """执行核查图，返回 (交付正文或 None, 校验记录)。

    `verifier` 提供 verify / rewrite / case_context / sim_fn / min_chars /
    min_ratio，以及跨调用累积的 `_review_log` / `_grounding` / `_format_retries`。
    这里不复制它的实现，只编排调用顺序。
    """
    terminal, final_text, report, issues = _preflight(verifier, text, evidence, max_rounds)
    if terminal:
        return final_text, report

    graph = _build_graph(
        verifier, evidence, base_text=text, max_rounds=max_rounds,
        regenerate=regenerate, max_issues_per_round=max_issues_per_round,
    )
    result = graph.invoke(
        {"text": text, "issues": issues, "round": 0, "regen_used": False, "report": report},
        config={"recursion_limit": 2 * max(0, max_rounds) + 8},
    )
    return result.get("final_text"), result["report"]


def _preflight(
    verifier: Any, text: str, evidence: list[dict[str, Any]], max_rounds: int,
) -> tuple[bool, str | None, dict[str, Any], list[dict[str, Any]] | None]:
    """建报告、守卫、无效编号清理、首轮核查、来源仲裁。

    返回 `(是否终态, 终态正文, 报告, 问题列表)`。终态包括空正文、无证据、
    首轮通过、核查调用失败——这些分支在迁移前就是早退，不需要进图。
    """
    report: dict[str, Any] = {
        "status": "skipped",
        "rounds": 0,
        "initial_issues": 0,
        "remaining_issues": [],
        "fixed": [],
        "deleted": 0,
        "format_retries": 0,
        "policy_version": 2,
        "source_manifest": source_manifest(verifier.case_context, evidence),
        "draft_text_sha256": text_digest(text),
        "review_log": verifier._review_log,
        "case_fact_matches": verifier._case_fact_matches,
    }
    verifier._format_retries = 0
    if not content_len(text):
        report["status"] = "rejected"
        report["reason"] = "empty_text"
        return True, None, report, None
    if not evidence:
        # 没有证据包就无法校验，返回拒答，不能把未校验正文当作成功结果
        return True, None, verifier.no_evidence_result(), None

    # 编号笔误先做确定性清理：指向不存在编号的 [n] 直接去掉，不占用修订轮数。
    # 去掉后若该句另有依据会正常通过；确实无据的句子仍由语义核查发现。
    text, removed_markers = strip_unknown_citations(text, evidence)
    if removed_markers:
        report["stripped_citations"] = removed_markers
        print(f"[VERIFY] 去掉 {len(removed_markers)} 处无效引用编号："
              f"{[m['marker'] for m in removed_markers]}", file=sys.stderr)
        if not content_len(text):
            report.update(status="rejected", reason="empty_text")
            return True, None, report, None

    issues = verifier.verify(text, evidence, stage="initial")
    report["format_retries"] = verifier._format_retries
    report["rounds"] = 1
    if issues is None:
        report["status"] = "error"
        report["reason"] = "verify_call_failed"
        report["failure_kind"] = verifier._failure_kind
        report["failure_detail"] = verifier._failure_detail
        return True, None, report, None

    report["initial_issues"] = len(issues)
    if max_rounds > 0 and any(item.get("origin") == "source_audit" for item in issues):
        issues = verifier.verify(text, evidence, stage="source_adjudication")
        report["adjudicated"] = True
        report["format_retries"] = verifier._format_retries
        report["rounds"] = len(verifier._review_log)
        if issues is None:
            report.update(status="error", reason="recheck_call_failed",
                          failure_kind=verifier._failure_kind,
                          failure_detail=verifier._failure_detail)
            return True, None, report, None
    if not issues:
        report["status"] = "pass"
        report["final_text_sha256"] = text_digest(text)
        report["reference_links"] = reference_links(text)
        report["grounding"] = verifier._grounding
        return True, text, report, None
    return False, None, report, issues


def _build_graph(
    verifier: Any,
    evidence: list[dict[str, Any]],
    *,
    base_text: str,
    max_rounds: int,
    regenerate: Callable[[list[dict[str, Any]]], str] | None,
    max_issues_per_round: int,
):
    """把修订循环与收尾判定连成图。节点只做一件事，路由只读状态。"""
    ev_text = "\n".join(item.get("text", "") for item in evidence)
    ev_map = {
        int(item.get("index", pos)): str(item.get("text", ""))
        for pos, item in enumerate(evidence, 1)
    }
    # 「删到不成文」的判据在本次核查开始时确定：固定下限与原稿比例取大者。
    # 不能每轮重算，否则正文越改越短，门槛也跟着降，等于放宽了不成文判定。
    min_len = max(verifier.min_chars, int(content_len(base_text) * verifier.min_ratio))

    def _round_labels(state: VerifyState) -> None:
        report = state["report"]
        report["format_retries"] = verifier._format_retries
        report["rounds"] = len(verifier._review_log)

    def _fail(state: VerifyState, reason: str) -> dict[str, Any]:
        state["report"].update(
            status="error", reason=reason,
            failure_kind=verifier._failure_kind, failure_detail=verifier._failure_detail,
        )
        return {**state, "final_text": None, "outcome": "error"}

    def rewrite(state: VerifyState) -> dict[str, Any]:
        report, current, issues = state["report"], state["text"], state["issues"]
        round_no = state.get("round", 0) + 1
        replacements = verifier.rewrite(current, issues[:max_issues_per_round], evidence)
        if replacements:
            current, applied, deleted = apply_replacements(
                current, replacements, ev_text, sim_fn=verifier.sim_fn, evidence_map=ev_map,
                allowed_quotes=[item["quote"] for item in issues[:max_issues_per_round]],
                protected_facts=case_fragments(verifier.case_context),
            )
            issue_by_quote = {item["quote"]: item for item in issues}
            for item in applied:
                issue = issue_by_quote.get(item["quote"], {})
                item.update({key: issue[key] for key in ("basis", "impact", "reason") if key in issue})
            report["fixed"].extend(applied)
            report["deleted"] += deleted
            print(
                f"[VERIFY] 第 {round_no} 轮：{len(issues)} 处问题 → "
                f"改写 {len(applied)} 句（其中删除 {deleted} 句）",
                file=sys.stderr,
            )
        if not content_len(current):
            report.update(status="rejected", reason="empty_text")
            return {**state, "text": current, "round": round_no,
                    "final_text": None, "outcome": "rejected"}
        issues = verifier.verify(current, evidence, stage="recheck")
        state = {**state, "text": current, "issues": issues, "round": round_no}
        _round_labels(state)
        if issues is None:
            return _fail(state, "recheck_call_failed")
        return state

    def after_rewrite(state: VerifyState) -> str:
        if state.get("outcome"):
            return END
        issues = state["issues"]
        if not issues:
            return "deliver"
        if all(item.get("impact", "core") == "local" for item in issues):
            return "cleanup"
        too_thin = content_len(state["text"]) < min_len
        if regenerate and not state.get("regen_used") and (
                too_thin or state["round"] == max_rounds):
            return "regenerate"
        if state["round"] < max_rounds:
            return "rewrite"
        return "cleanup"

    def regenerate_node(state: VerifyState) -> dict[str, Any]:
        report, issues = state["report"], state["issues"]
        too_thin = content_len(state["text"]) < min_len
        print(
            "[VERIFY] 改写无法收敛（{}），重新生成整篇报告".format(
                "正文已删至不成文" if too_thin else "轮数用尽仍有余留"
            ),
            file=sys.stderr,
        )
        try:
            regenerated = regenerate(issues) if regenerate else None
        except Exception as exc:  # noqa: BLE001 - 重生成失败仍按剩余问题收尾
            regenerated = None
            report["regeneration_failure"] = type(exc).__name__
        if regenerated and content_len(regenerated) and not regenerated.lstrip().startswith("Error:"):
            current = regenerated
            report["regenerated"] = True
            issues = verifier.verify(current, evidence, stage="regenerated")
            state = {**state, "text": current, "issues": issues, "regen_used": True}
            _round_labels(state)
            if issues is None:
                return _fail(state, "recheck_call_failed")
            return state
        print("[VERIFY] 重新生成失败", file=sys.stderr)
        return {**state, "regen_used": True}

    def after_regenerate(state: VerifyState) -> str:
        if state.get("outcome"):
            return END
        if not state["issues"]:
            return "deliver"
        if state["round"] < max_rounds:
            return "rewrite"
        return "cleanup"

    def cleanup(state: VerifyState) -> dict[str, Any]:
        report, current, issues = state["report"], state["text"], state["issues"]
        if not issues:
            return state
        cleaned, omitted = omit_local_issues(current, issues)
        if not omitted:
            return state
        report["fixed"].extend(omitted)
        report["deleted"] += len(omitted)
        report["local_cleanup"] = True
        if not content_len(cleaned):
            report.update(status="rejected", reason="empty_text", remaining_issues=issues)
            return {**state, "final_text": None, "outcome": "rejected"}
        issues = verifier.verify(cleaned, evidence, stage="local_cleanup")
        state = {**state, "text": cleaned, "issues": issues}
        _round_labels(state)
        if issues is None:
            return _fail(state, "recheck_call_failed")
        return state

    def after_cleanup(state: VerifyState) -> str:
        if state.get("outcome"):
            return END
        return "deliver" if not state["issues"] else "annotate"

    def deliver(state: VerifyState) -> dict[str, Any]:
        report, current = state["report"], state["text"]
        report["status"] = "rewritten" if (report["fixed"] or report.get("regenerated")) else "pass"
        report["final_text_sha256"] = text_digest(current)
        report["reference_links"] = reference_links(current)
        report["grounding"] = verifier._grounding
        print(
            f"[VERIFY] 通过：首轮 {report['initial_issues']} 处问题，"
            f"改写 {len(report['fixed'])} 句（删 {report['deleted']}），"
            f"重生成={'是' if report.get('regenerated') else '否'}",
            file=sys.stderr,
        )
        return {**state, "final_text": current, "outcome": "delivered"}

    def annotate(state: VerifyState) -> dict[str, Any]:
        report, current, issues = state["report"], state["text"], state["issues"]
        report["remaining_issues"] = issues
        # 到这里仍未消解：区分「资料未覆盖」与「与资料冲突」。
        # 前者标注后照常交付，后者一律拒答——改个数值就能修好的错误不该放行。
        if config.VERIFY_SOFT_DELIVERY:
            blocking = unannotated(issues, verifier.case_context)
            if not blocking:
                unknown_numbers = {int(m.group(1)) for m in re.finditer(r"\[(-?\d+)\]", current)} - {
                    item.get("index", i) for i, item in enumerate(evidence, 1)}
                annotated_text, marked = annotate_unverified(
                    current, issues, verifier.case_context, unknown=unknown_numbers)
                if marked:
                    report.update(
                        status="rewritten", reason="delivered_with_annotations",
                        final_text_sha256=text_digest(annotated_text),
                        reference_links=reference_links(annotated_text),
                        grounding=verifier._grounding,
                        annotations=marked, annotated_count=len(marked),
                    )
                    report["remaining_issues"] = []
                    print(
                        f"[VERIFY] 交付：仍有 {len(marked)} 处资料未覆盖，已就地标注",
                        file=sys.stderr,
                    )
                    return {**state, "final_text": annotated_text, "outcome": "delivered"}
        report["status"] = "rejected"
        report["reason"] = "unverified_claims_remain"
        print(
            f"[VERIFY] 拒答：仍有 {len(issues)} 处断言无法被资料支持，不输出报告",
            file=sys.stderr,
        )
        return {**state, "final_text": None, "outcome": "rejected"}

    def start(state: VerifyState) -> dict[str, Any]:
        return state

    def after_start(state: VerifyState) -> str:
        if max_rounds <= 0:
            return "cleanup"
        return "rewrite"

    graph = StateGraph(VerifyState)
    graph.add_node("start", start)
    graph.add_node("rewrite", rewrite)
    graph.add_node("regenerate", regenerate_node)
    graph.add_node("cleanup", cleanup)
    graph.add_node("deliver", deliver)
    graph.add_node("annotate", annotate)
    graph.set_entry_point("start")
    graph.add_conditional_edges("start", after_start)
    graph.add_conditional_edges("rewrite", after_rewrite)
    graph.add_conditional_edges("regenerate", after_regenerate)
    graph.add_conditional_edges("cleanup", after_cleanup)
    graph.add_edge("deliver", END)
    graph.add_edge("annotate", END)
    return graph.compile()
