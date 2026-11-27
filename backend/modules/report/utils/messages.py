from __future__ import annotations
from core import config
from typing import Any
USE_CHINESE = config.REPORT_LANGUAGE.startswith("zh")
def reject_message(verification: dict[str, Any]) -> str:
    """拒答文案：告诉用户「为什么没有报告」，而不是交一份打了折的报告。"""
    remaining = verification.get("remaining_issues") or []
    is_error = verification.get("status") == "error"

    reason = verification.get("reason")
    if reason == "retrieval_failed":
        return (
            "## 知识检索故障，本次未生成报告\n\n"
            "检索工具调用失败，无法确认正文的资料来源。这与「没有相关证据」不同："
            "故障不能被当作成功检索，也不能据此判断资料缺失。\n\n"
            "请查看后端 RAG 日志后重试；已有影像结果仍可查看。"
            if USE_CHINESE else
            "## Knowledge retrieval failed\n\n"
            "The retrieval tool failed, so the sources behind any report could not be established. "
            "This differs from having no relevant evidence.\n\n"
            "Check the backend RAG logs and retry; imaging results remain available."
        )
    if reason == "unsupported_claims":
        return (
            "## 报告包含无法核实的内容\n\n"
            "程序检查发现正文存在无法由病例输入或检索资料支持的数值或适用性冲突，"
            "本次未输出报告。请补充资料或核对写法后重试。"
            if USE_CHINESE else
            "## The report contains unverifiable content\n\n"
            "Deterministic checks found values or applicability conflicts not supported by the "
            "case input or retrieved sources. The report was withheld."
        )
    if is_error:
        kind = verification.get("failure_kind")
        details = {
            "empty_response": ("校验模型返回了空内容。", "The verification model returned an empty response."),
            "llm_error": ("校验模型请求失败。", "The verification model request failed."),
            "invalid_json": ("校验模型未返回有效 JSON。", "The verification model returned invalid JSON."),
            "invalid_claims": ("校验模型返回的 claims 结构不符合约定。", "The verification model returned an invalid claims structure."),
        }
        detail = details.get(kind, (
            "校验模型调用或返回格式出错。", "The verification model request or response format failed.",
        ))[0 if USE_CHINESE else 1]
        if kind in {"invalid_json", "invalid_claims"} and verification.get("failure_detail"):
            label = "格式检查" if USE_CHINESE else "Format check"
            detail += f"\n\n{label}：{verification['failure_detail']}\n\n"
        if USE_CHINESE:
            return ("## 报告引用校验出错\n\n" + detail +
                    "这不表示病例资料缺少引用，也不等于已确认正文没有依据。\n\n"
                    "请检查「个人设置 → LLM API 配置」的连通性，并查看后端的 LLM / VERIFY 日志后重试。"
                    "在校验成功前，本次报告正文暂不交付。")
        return ("## Report citation verification failed\n\n" + detail +
                " This does not establish that case data or references are missing.\n\n"
                "Check the LLM API settings and backend LLM / VERIFY logs, then retry. "
                "The report text is withheld until verification succeeds.")
    if reason == "no_evidence":
        return ("本次分析未取得可用于校验的参考资料，无法生成有依据的报告。" if USE_CHINESE
                else "No references were available to verify this report.")
    if reason == "empty_text":
        return ("缺少可交付的报告正文。" if USE_CHINESE else "No report text remains for delivery.")

    if USE_CHINESE:
        lines = ["## 无法生成有依据的诊断报告", ""]
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
            "请先核对上述具体表述及适用证据。非核心说明会尝试局部删减后重新校验；"
            "涉及诊断或处置、定位不明确或复核仍未通过的问题会阻止正文交付。",
            "已计算的结构化影像结果仍可查看；不因报告中的个别表述失败而清除。",
        ]
        return "\n".join(lines)

    lines = ["## No verifiable report could be generated", ""]
    lines.append(
        f"{len(remaining) or verification.get('initial_issues', 0)} claims could not be grounded "
        f"in the knowledge base after {verification.get('rounds', 0)} rewrite rounds."
    )
    lines += ["", "The report was withheld to avoid unsupported clinical conclusions."]
    for it in remaining[:5]:
        lines.append(f"- {(it.get('quote') or '')[:60]} | {it.get('reason') or it.get('verdict')}")
    return "\n".join(lines)
