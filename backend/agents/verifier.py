"""引用校验 Agent：协调核查、修订、复核和最终状态。

提示词位于 prompts/verification.py；JSON 解析与文本修订位于 tools/。
病例数据无需外部文献引用，其真实性需要与原始病例核对，不由本模块保证。
"""
from __future__ import annotations
from typing import Any, Callable
import sys
from typing import Any, Callable
from llm.models import LLMCall
from .prompts.verification import (
    VERIFIER_SYSTEM,
    REWRITER_SYSTEM,
    build_verify_prompt,
    build_rewrite_prompt,
)
from .tools.json_response import parse_json
from .tools.evidence import unknown_citation_issues
from .tools.text_revision import apply_replacements, content_len

MAX_ISSUES_PER_ROUND = 12
_VERDICTS = {"partial", "unsupported", "uncited"}

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
    ) -> None:
        self._llm = llm_call
        # 修订后仍有问题且正文低于阈值时，优先请求整篇重生成。
        self.min_chars = min_chars
        self.min_ratio = min_ratio
        # 语义相似度回调，用于跨语言判断「假覆盖」；不传则只用词面判据
        self.sim_fn = sim_fn

    # -- 单步 ---------------------------------------------------------------
    def verify(self, text: str, evidence: list[dict]) -> list[dict[str, Any]] | None:
        """返回问题句列表；调用或解析失败返回 None，主流程据此返回 error。"""
        raw = self._llm(
            build_verify_prompt(text, evidence),
            system=VERIFIER_SYSTEM,
            temperature=0.0,
        )
        if not raw or raw.startswith("Error:"):
            print(f"[VERIFY] 校验调用失败：{(raw or '空响应')[:200]}", file=sys.stderr)
            return None

        data = parse_json(raw)
        if not isinstance(data, dict) or not isinstance(data.get("claims"), list):
            print(f"[VERIFY] 校验结果缺少有效 claims 列表，本轮终止：{raw[:200]}", file=sys.stderr)
            return None

        issues: list[dict] = []
        for item in data.get("claims") or []:
            if not isinstance(item, dict):
                continue
            quote = str(item.get("quote") or "").strip()
            verdict = str(item.get("verdict") or "").strip().lower()
            if not quote or verdict not in _VERDICTS:
                continue
            issues.append({
                "quote": quote[:200],
                "verdict": verdict,
                "citations": item.get("citations") or [],
                "reason": str(item.get("reason") or "")[:120],
            })
        deterministic = unknown_citation_issues(text, evidence)
        known = {(item["quote"], tuple(item["citations"])) for item in issues}
        issues.extend(
            item for item in deterministic
            if (item["quote"], tuple(item["citations"])) not in known
        )
        return issues

    def rewrite(
        self,
        text: str,
        issues: list[dict],
        evidence: list[dict],
    ) -> list[dict]:
        raw = self._llm(
            build_rewrite_prompt(text, issues, evidence),
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
        regenerate 最多调用一次；仅在复核仍有问题，且正文过短或轮数用尽时触发。
        """
        report = {
            "status": "skipped",
            "rounds": 0,
            "initial_issues": 0,
            "remaining_issues": [],
            "fixed": [],
            "deleted": 0,
        }
        if not text or not text.strip():
            report["status"] = "rejected"
            report["reason"] = "empty_text"
            return None, report
        if not evidence:
            # 没有证据包就无法校验，返回拒答，不能把未校验正文当作成功结果
            report["reason"] = "no_evidence"
            report["status"] = "rejected"
            return None, report

        ev_text = "\n".join(item.get("text", "") for item in evidence)
        ev_map = {
            int(item.get("index", pos)): str(item.get("text", ""))
            for pos, item in enumerate(evidence, 1)
        }
        min_len = max(self.min_chars, int(content_len(text) * self.min_ratio))

        issues = self.verify(text, evidence)
        report["rounds"] = 1
        if issues is None:
            report["status"] = "error"
            report["reason"] = "verify_call_failed"
            return None, report

        report["initial_issues"] = len(issues)
        if not issues:
            report["status"] = "pass"
            return text, report

        current = text
        regen_used = False

        for round_no in range(1, max(0, max_rounds) + 1):
            replacements = self.rewrite(current, issues[:MAX_ISSUES_PER_ROUND], evidence)
            if replacements:
                current, applied, deleted = apply_replacements(
                    current, replacements, ev_text, sim_fn=self.sim_fn, evidence_map=ev_map
                )
                report["fixed"].extend(applied)
                report["deleted"] += deleted
                print(
                    f"[VERIFY] 第 {round_no} 轮：{len(issues)} 处问题 → "
                    f"改写 {len(applied)} 句（其中删除 {deleted} 句）",
                    file=sys.stderr,
                )

            issues = self.verify(current, evidence)
            report["rounds"] = round_no + 1
            if issues is None:
                report["status"] = "error"
                report["reason"] = "recheck_call_failed"
                return None, report
            if not issues:
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
                regenerated = regenerate(issues)
                if regenerated and not str(regenerated).startswith("Error:"):
                    current = regenerated
                    report["regenerated"] = True
                    issues = self.verify(current, evidence)
                    report["rounds"] += 1
                    if issues is None:
                        report["status"] = "error"
                        report["reason"] = "recheck_call_failed"
                        return None, report
                    if not issues:
                        break
                else:
                    print("[VERIFY] 重新生成失败", file=sys.stderr)

        if not issues:
            report["status"] = "rewritten" if (report["fixed"] or report.get("regenerated")) else "pass"
            print(
                f"[VERIFY] 通过：首轮 {report['initial_issues']} 处问题，"
                f"改写 {len(report['fixed'])} 句（删 {report['deleted']}），"
                f"重生成={'是' if report.get('regenerated') else '否'}",
                file=sys.stderr,
            )
            return current, report

        report["remaining_issues"] = issues
        report["status"] = "rejected"
        report["reason"] = "unverified_claims_remain"
        print(
            f"[VERIFY] 拒答：仍有 {len(issues)} 处断言无法被资料支持，不输出报告",
            file=sys.stderr,
        )
        return None, report
