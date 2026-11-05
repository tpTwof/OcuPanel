from __future__ import annotations
from utils import config
from typing import Any
USE_CHINESE = config.REPORT_LANGUAGE.startswith("zh")
def reject_message(verification: dict[str, Any]) -> str:
    """拒答文案：告诉用户「为什么没有报告」，而不是交一份打了折的报告。"""
    remaining = verification.get("remaining_issues") or []
    is_error = verification.get("status") == "error"

    if USE_CHINESE:
        lines = ["## 无法生成有依据的诊断报告", ""]
        if is_error:
            lines.append("本次校验过程出错（%s），无法确认报告内容是否可靠。" % (verification.get("reason") or "unknown"))
        else:
            total = len(remaining) or verification.get("initial_issues", 0)
            lines.append(
                f"本轮报告有 {total} 处断言检索不到支持它们的资料，经过 {verification.get('rounds', 0)} 轮"
                "改写与重新生成后仍未消除。"
            )
        lines += ["", "为避免输出无依据的医学结论，本系统未生成诊断报告。"]
        if remaining:
            lines += ["", "未通过校验的表述（示例）："]
            for it in remaining[:5]:
                quote = (it.get("quote") or "")[:60]
                lines.append(f"- {quote}｜{it.get('reason') or it.get('verdict')}")
        lines += [
            "",
            "建议：补充视野、OCT、房角等检查资料，或完善本地知识库语料后重试。",
            "本系统不提供未经资料支持的推断性结论，这是刻意设计，而非故障。",
        ]
        return "\n".join(lines)

    lines = ["## No verifiable report could be generated", ""]
    if is_error:
        lines.append(f"Citation verification failed: {verification.get('reason') or 'unknown'}.")
    else:
        lines.append(
            f"{len(remaining) or verification.get('initial_issues', 0)} claims could not be grounded "
            f"in the knowledge base after {verification.get('rounds', 0)} rewrite rounds."
        )
    lines += ["", "The report was withheld to avoid unsupported clinical conclusions."]
    for it in remaining[:5]:
        lines.append(f"- {(it.get('quote') or '')[:60]} | {it.get('reason') or it.get('verdict')}")
    return "\n".join(lines)
