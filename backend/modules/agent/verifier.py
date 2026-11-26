"""引用校验 Agent：协调核查、修订、复核和最终状态。

提示词位于 prompts/verification.py；JSON 解析与文本修订位于 tools/。
病例数据无需外部文献引用，其真实性需要与原始病例核对，不由本模块保证。
"""
from __future__ import annotations
import re
import sys
from typing import Any, Callable
from core.llm.models import LLMCall
from core import config
from .prompts.verification import (
    VERIFIER_SYSTEM,
    REWRITER_SYSTEM,
    build_verify_prompt,
    build_rewrite_prompt,
)
from .tools.json_response import parse_json
from .tools.verification_response import parse_claims
from .tools.grounding import audit_grounding, uncovered_citations
from .tools.verification_audit import (
    case_fragments, contains_case_fragment, match_case_facts, reference_links, source_manifest, text_digest,
)
from .tools.evidence import strip_unknown_citations, unknown_citation_issues
from .tools.annotation import annotate_unverified, unannotated
from .tools.text_revision import (
    apply_replacements, content_len, locate, omit_local_issues, snap_to_sentence,
)

MAX_ISSUES_PER_ROUND = 12

class CitationVerifier:
    """核查引用，有限轮修订并复核，必要时请求一次整篇重生成。

    llm_call 接收 prompt、system、temperature；regenerate 回调接收问题列表。
    execute 返回 (正文或 None, 校验记录)。此 Agent 不验证影像测量本身。
    """
    name = "verifier"
    role_description = "核查引用、修订不支持的陈述并复核"

    def execute(
        self,
        text: str,
        evidence: list[dict[str, Any]],
        max_rounds: int = 2,
        regenerate: Callable[[list[dict[str, Any]]], str] | None = None,
    ) -> tuple[str | None, dict[str, Any]]:
        return self.verify_and_rewrite(text, evidence, max_rounds=max_rounds, regenerate=regenerate)

    def __init__(
        self,
        llm_call: LLMCall,
        min_chars: int = 300,
        min_ratio: float = 0.4,
        sim_fn: Callable[[str, str], float] | None = None,
        case_context: str = "",
        require_grounding: bool = False,
    ) -> None:
        self._llm = llm_call
        # 修订后仍有问题且正文低于阈值时，优先请求整篇重生成。
        self.min_chars = min_chars
        self.min_ratio = min_ratio
        # 语义相似度回调，用于跨语言判断「假覆盖」；不传则只用词面判据
        self.sim_fn = sim_fn
        self._failure_kind: str | None = None
        self._failure_detail: str | None = None
        self._format_retries = 0
        self.case_context = case_context
        self._review_log: list[dict] = []
        self._case_fact_matches: list[dict] = []
        self.require_grounding = require_grounding
        self._grounding: list[dict] = []

    def _record_review(self, text: str, issues: list[dict] | None, stage: str) -> list[dict] | None:
        self._review_log.append({
            "stage": stage, "text_sha256": text_digest(text),
            "issue_count": len(issues) if issues is not None else None,
            "issues": issues, "failure_kind": self._failure_kind,
        })
        return issues

    def _ground_issues(self, text: str, evidence: list[dict], issues: list[dict]) -> tuple[list[dict], list[dict]]:
        issues, matches = match_case_facts(issues, self.case_context)
        fragments = case_fragments(self.case_context)
        for item in issues:
            if contains_case_fragment(item["quote"], fragments):
                item["impact"] = "core"
        known = {(item["quote"], tuple(item["citations"])): item for item in issues}
        for item in unknown_citation_issues(text, evidence):
            key = (item["quote"], tuple(item["citations"]))
            if key in known:
                known[key]["impact"] = "core"
            else:
                issues.append(item)
        return issues, matches

    # -- 单步 ---------------------------------------------------------------
    def _previous_summary(self) -> dict | None:
        """上一轮核查的精简摘要，用于保持判断一致。

        不要整份 review_log：它带着每个问题的完整 reason，轮数越多提示词越长，
        实测会导致单次调用从 40 秒涨到 160 秒。这里只保留阶段、计数与问题句。
        """
        if not self._review_log:
            return None
        last = self._review_log[-1]
        quotes = [item.get("quote", "")[:40] for item in (last.get("issues") or [])][:8]
        return {"stage": last.get("stage"), "issue_count": last.get("issue_count"),
                "quotes": quotes}

    def verify(self, text: str, evidence: list[dict], *, stage: str = "review") -> list[dict[str, Any]] | None:
        """返回问题句列表；调用或解析失败返回 None，主流程据此返回 error。"""
        self._failure_kind = None
        self._failure_detail = None
        previous = self._previous_summary()
        prompt = build_verify_prompt(text, evidence, case_context=self.case_context, previous=previous)
        for attempt in range(2):
            raw = self._llm(prompt, system=VERIFIER_SYSTEM, temperature=0.0)
            if not raw or raw.startswith("Error:"):
                self._failure_kind = "empty_response" if not raw else "llm_error"
                self._failure_detail = None
                print(f"[VERIFY] 校验失败：{self._failure_kind}", file=sys.stderr)
                return self._record_review(text, None, stage)
            data = parse_json(raw)
            try:
                issues = parse_claims(data)
                for index, item in enumerate(issues):
                    if locate(text, item["quote"]) is not None:
                        continue
                    # 模型改写了措辞而不是逐字复制：先对齐到最接近的正文原句，
                    # 对齐后仍能定点修订或标注；对不上才按格式错误重试。
                    snapped = snap_to_sentence(text, item["quote"])
                    if snapped is None:
                        raise ValueError(
                            f"claims[{index}].quote must uniquely match the current report")
                    item["quote"] = snapped
                grounding, source_issues = audit_grounding(data, text, evidence, self.case_context,
                                                          required=self.require_grounding)
                known_quotes = {item["quote"] for item in issues}
                issues.extend(item for item in source_issues if item["quote"] not in known_quotes)
                issues, matches = self._ground_issues(text, evidence, issues)
                if self.require_grounding and not issues:
                    # grounding 漏列某个引用时，不再让整次核查失败（invalid_claims），
                    # 而是把这些分句当作「需要补充出处」的问题交给后续处理。
                    missing = uncovered_citations(text, grounding)
                    if missing:
                        issues.extend({
                            "quote": clause, "verdict": "uncited",
                            # 带上该句的编号，降级交付时要把这些编号去掉
                            "citations": [int(n) for n in re.findall(r"\[(-?\d+)\]", clause)],
                            "impact": "core", "basis": "medical_knowledge",
                            "reason": "grounding 未列出该引用对应的资料原文",
                            "origin": "grounding_gap",
                        } for clause in missing)
                break
            except ValueError as exc:
                self._failure_kind = "invalid_json" if data is None else "invalid_claims"
                self._failure_detail = str(exc)
                print(f"[VERIFY] {self._failure_kind}: {self._failure_detail}", file=sys.stderr)
                if attempt == 1:
                    return self._record_review(text, None, stage)
                self._format_retries += 1
                # 重新核查原文和原证据，不将无效响应改造成「无问题」。
                prompt = build_verify_prompt(text, evidence, case_context=self.case_context, previous=previous) + (
                    "\n\n【格式重试】上次响应不符合约定：" + self._failure_detail +
                    "。请重新核查上面的完整报告与参考资料，只返回约定的 JSON 问题列表。"
                    "不得为了满足格式而省略实际存在的问题。"
                )
        self._case_fact_matches.extend(item for item in matches if item not in self._case_fact_matches)
        # 成功路径不留下上一轮的故障标记；失败路径（上方 return）保留 _failure_kind
        # 供调用方写入 verification.failure_kind，不能在这里提前清空。
        self._failure_kind = None
        self._failure_detail = None
        self._grounding = grounding
        return self._record_review(text, issues, stage)

    def rewrite(
        self,
        text: str,
        issues: list[dict],
        evidence: list[dict],
    ) -> list[dict]:
        raw = self._llm(
            build_rewrite_prompt(text, issues, evidence, case_context=self.case_context),
            system=REWRITER_SYSTEM,
            temperature=0.2,
        )
        if not raw or raw.startswith("Error:"):
            print(f"[VERIFY] 重写调用失败：{(raw or '空响应')[:200]}", file=sys.stderr)
            return []
        data = parse_json(raw)
        if not isinstance(data, dict):
            print(f"[VERIFY] 重写结果不是 JSON，跳过：{raw[:200]}", file=sys.stderr)
            return []
        return [r for r in (data.get("replacements") or []) if isinstance(r, dict)]

    # -- 主流程 -------------------------------------------------------------
    @staticmethod
    def no_evidence_result() -> dict[str, Any]:
        return {"status": "rejected", "reason": "no_evidence", "rounds": 0,
                "initial_issues": 0, "remaining_issues": [], "fixed": [], "deleted": 0}

    def verify_and_rewrite(
        self,
        text: str,
        evidence: list[dict],
        max_rounds: int = 2,
        regenerate: Callable[[list[dict[str, Any]]], str] | None = None,
    ) -> tuple[str | None, dict[str, Any]]:
        """执行核查、有限轮修订与复核。

        返回状态：pass（首次通过）、rewritten（修订后通过）、
        rejected（无证据、空正文或问题未消除）、error（校验调用失败）。
        仅剩非核心说明时可尝试一次局部删除，随后重新核查全文。
        regenerate 最多调用一次；仅在复核仍有问题，且正文过短或轮数用尽时触发。
        """
        self._review_log = []
        self._case_fact_matches = []
        self._grounding = []
        report = {
            "status": "skipped",
            "rounds": 0,
            "initial_issues": 0,
            "remaining_issues": [],
            "fixed": [],
            "deleted": 0,
            "format_retries": 0,
            "policy_version": 2,
            "source_manifest": source_manifest(self.case_context, evidence),
            "draft_text_sha256": text_digest(text),
            "review_log": self._review_log,
            "case_fact_matches": self._case_fact_matches,
        }
        self._format_retries = 0
        if not content_len(text):
            report["status"] = "rejected"
            report["reason"] = "empty_text"
            return None, report
        if not evidence:
            # 没有证据包就无法校验，返回拒答，不能把未校验正文当作成功结果
            return None, self.no_evidence_result()

        ev_text = "\n".join(item.get("text", "") for item in evidence)
        ev_map = {
            int(item.get("index", pos)): str(item.get("text", ""))
            for pos, item in enumerate(evidence, 1)
        }
        min_len = max(self.min_chars, int(content_len(text) * self.min_ratio))

        # 编号笔误先做确定性清理：指向不存在编号的 [n] 直接去掉，不占用修订轮数。
        # 去掉后若该句另有依据会正常通过；确实无据的句子仍由下面的语义核查发现。
        text, removed_markers = strip_unknown_citations(text, evidence)
        if removed_markers:
            report["stripped_citations"] = removed_markers
            print(f"[VERIFY] 去掉 {len(removed_markers)} 处无效引用编号："
                  f"{[m['marker'] for m in removed_markers]}", file=sys.stderr)
            if not content_len(text):
                report.update(status="rejected", reason="empty_text")
                return None, report

        issues = self.verify(text, evidence, stage="initial")
        report["format_retries"] = self._format_retries
        report["rounds"] = 1
        if issues is None:
            report["status"] = "error"
            report["reason"] = "verify_call_failed"
            report["failure_kind"] = self._failure_kind
            report["failure_detail"] = self._failure_detail
            return None, report

        report["initial_issues"] = len(issues)
        if max_rounds > 0 and any(item.get("origin") == "source_audit" for item in issues):
            issues = self.verify(text, evidence, stage="source_adjudication")
            report["adjudicated"] = True
            report["format_retries"] = self._format_retries
            report["rounds"] = len(self._review_log)
            if issues is None:
                report.update(status="error", reason="recheck_call_failed",
                              failure_kind=self._failure_kind, failure_detail=self._failure_detail)
                return None, report
        if not issues:
            report["status"] = "pass"
            report["final_text_sha256"] = text_digest(text)
            report["reference_links"] = reference_links(text)
            report["grounding"] = self._grounding
            return text, report

        current = text
        regen_used = False

        for round_no in range(1, max(0, max_rounds) + 1):
            replacements = self.rewrite(current, issues[:MAX_ISSUES_PER_ROUND], evidence)
            if replacements:
                current, applied, deleted = apply_replacements(
                    current, replacements, ev_text, sim_fn=self.sim_fn, evidence_map=ev_map,
                    allowed_quotes=[item["quote"] for item in issues[:MAX_ISSUES_PER_ROUND]],
                    protected_facts=case_fragments(self.case_context),
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
                return None, report
            issues = self.verify(current, evidence, stage="recheck")
            report["format_retries"] = self._format_retries
            report["rounds"] = len(self._review_log)
            if issues is None:
                report["status"] = "error"
                report["reason"] = "recheck_call_failed"
                report["failure_kind"] = self._failure_kind
                report["failure_detail"] = self._failure_detail
                return None, report
            if not issues:
                break

            if all(item.get("impact", "core") == "local" for item in issues):
                break

            too_thin = content_len(current) < min_len
            if regenerate and not regen_used and (too_thin or round_no == max_rounds):
                regen_used = True
                print(
                    "[VERIFY] 改写无法收敛（{}），重新生成整篇报告".format(
                        "正文已删至不成文" if too_thin else "轮数用尽仍有余留"
                    ),
                    file=sys.stderr,
                )
                try:
                    regenerated = regenerate(issues)
                except Exception as exc:
                    regenerated = None
                    report["regeneration_failure"] = type(exc).__name__
                if regenerated and content_len(regenerated) and not regenerated.lstrip().startswith("Error:"):
                    current = regenerated
                    report["regenerated"] = True
                    issues = self.verify(current, evidence, stage="regenerated")
                    report["format_retries"] = self._format_retries
                    report["rounds"] = len(self._review_log)
                    if issues is None:
                        report["status"] = "error"
                        report["reason"] = "recheck_call_failed"
                        report["failure_kind"] = self._failure_kind
                        report["failure_detail"] = self._failure_detail
                        return None, report
                    if not issues:
                        break
                else:
                    print("[VERIFY] 重新生成失败", file=sys.stderr)

        if issues:
            cleaned, omitted = omit_local_issues(current, issues)
            if omitted:
                report["fixed"].extend(omitted)
                report["deleted"] += len(omitted)
                report["local_cleanup"] = True
                if not content_len(cleaned):
                    report.update(status="rejected", reason="empty_text", remaining_issues=issues)
                    return None, report
                current = cleaned
                issues = self.verify(current, evidence, stage="local_cleanup")
                report["format_retries"] = self._format_retries
                report["rounds"] = len(self._review_log)
                if issues is None:
                    report.update(
                        status="error", reason="recheck_call_failed",
                        failure_kind=self._failure_kind, failure_detail=self._failure_detail,
                    )
                    return None, report

        if not issues:
            report["status"] = "rewritten" if (report["fixed"] or report.get("regenerated")) else "pass"
            report["final_text_sha256"] = text_digest(current)
            report["reference_links"] = reference_links(current)
            report["grounding"] = self._grounding
            print(
                f"[VERIFY] 通过：首轮 {report['initial_issues']} 处问题，"
                f"改写 {len(report['fixed'])} 句（删 {report['deleted']}），"
                f"重生成={'是' if report.get('regenerated') else '否'}",
                file=sys.stderr,
            )
            return current, report

        report["remaining_issues"] = issues
        # 到这里仍未消解：区分「资料未覆盖」与「与资料冲突」。
        # 前者标注后照常交付，后者一律拒答——改个数值就能修好的错误不该放行。
        if config.VERIFY_SOFT_DELIVERY:
            blocking = unannotated(issues, self.case_context)
            if not blocking:
                unknown_numbers = {int(m.group(1)) for m in re.finditer(r"\[(-?\d+)\]", current)} - {
                    item.get("index", i) for i, item in enumerate(evidence, 1)}
                annotated_text, marked = annotate_unverified(
                    current, issues, self.case_context, unknown=unknown_numbers)
                if marked:
                    report.update(
                        status="rewritten", reason="delivered_with_annotations",
                        final_text_sha256=text_digest(annotated_text),
                        reference_links=reference_links(annotated_text),
                        grounding=self._grounding,
                        annotations=marked,
                        annotated_count=len(marked),
                    )
                    report["remaining_issues"] = []
                    print(
                        f"[VERIFY] 交付：仍有 {len(marked)} 处资料未覆盖，已就地标注",
                        file=sys.stderr,
                    )
                    return annotated_text, report
        report["status"] = "rejected"
        report["reason"] = "unverified_claims_remain"
        print(
            f"[VERIFY] 拒答：仍有 {len(issues)} 处断言无法被资料支持，不输出报告",
            file=sys.stderr,
        )
        return None, report
