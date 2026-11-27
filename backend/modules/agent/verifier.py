"""引用校验 Agent：核查单次调用、定点重写，控制流见 `graphs/verify.py`。

提示词位于 prompts/verification.py；JSON 解析与文本修订位于 tools/。
病例数据无需外部文献引用，其真实性需要与原始病例核对，不由本模块保证。

这个类现在只负责"一次核查"和"一次重写"两件事，以及跨调用累积的现场
（review_log / grounding / 失败分类）。首轮 → 仲裁 → 修订 → 重生成 → 标注
这些状态流转都交给 LangGraph 图，`execute` 保持原签名作为对外契约。
"""
from __future__ import annotations
import re
import sys
from typing import Any, Callable
from core.llm.models import LLMCall
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
    case_fragments, contains_case_fragment, match_case_facts, text_digest,
)
from .tools.evidence import unknown_citation_issues
from .tools.applicability import applicability_issues
from .tools.text_revision import content_len, locate, snap_to_sentence

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
        case_facts: list[dict[str, Any]] | None = None,
        diseases: tuple[str, ...] = (),
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
        # 结构化的病例事实与病种，用于确定性的眼别/适用性检查（可留空）
        self.case_facts = case_facts or []
        self.diseases = tuple(diseases)
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
        # 编号错误、编造数值、左右眼错位与病种不适用都由代码确定性识别，
        # 不依赖模型是否“看见”；同一句已有问题时只提升影响级别，不重复记录。
        deterministic = [
            *unknown_citation_issues(text, evidence),
            *applicability_issues(
                text, evidence, case_context=self.case_context,
                case_facts=self.case_facts, diseases=self.diseases,
            ),
        ]
        for item in deterministic:
            key = (item["quote"], tuple(item["citations"]))
            if key in known:
                known[key].update(item)
            else:
                issues.append(item)
                known[key] = item
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
        evidence: list[dict[str, Any]],
        max_rounds: int = 2,
        regenerate: Callable[[list[dict[str, Any]]], str] | None = None,
    ) -> tuple[str | None, dict[str, Any]]:
        """执行核查、有限轮修订与复核。

        返回状态：pass（首次通过）、rewritten（修订后通过）、
        rejected（无证据、空正文或问题未消除）、error（校验调用失败）。
        分支细节见 `graphs/verify.py`：这里只重置本次核查的现场，然后把状态机
        跑起来——迁移前这段逻辑是本方法里的 220 行嵌套。
        """
        from .graphs.verify import run_verification

        self._review_log = []
        self._case_fact_matches = []
        self._grounding = []
        self._format_retries = 0
        return run_verification(
            self, text, evidence, max_rounds=max_rounds, regenerate=regenerate,
        )
