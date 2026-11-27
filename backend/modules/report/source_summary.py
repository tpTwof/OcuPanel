"""诊疗解释未完成核查时，保留输入资料的只读摘要，不交付失败草稿。

受限摘要与拒答、故障是三种不同结局：受限摘要只保留用户输入，页面与 PDF 都
标明「诊疗结论未交付」；它不能伪装成通过核查的报告，也不能导出诊断 PDF。
"""
import re
from modules.agent.tools.verification_audit import text_digest
from core import config

# 默认只把「仍有未核实断言」转成受限摘要；legacy 流程的 no_evidence 仍是拒答。
LIMITED_REASONS = ("unverified_claims_remain",)

_REASON_NOTES = {
    "unverified_claims_remain": (
        "本轮诊疗解释或具体建议仍有未解决的来源问题。",
        "Clinical interpretation or specific advice still has unresolved source issues.",
    ),
    "retrieval_failed": (
        "知识库检索出现故障，无法确认正文依据；故障与「没有相关证据」不同。",
        "Knowledge retrieval failed, so the basis of any report could not be verified.",
    ),
    "no_evidence": (
        "本次没有检索到可用于核查正文的参考资料。",
        "No references were retrieved to verify report statements.",
    ),
    "no_retrieval_requested": (
        "本次只需整理用户提供的资料，未引入外部依据。",
        "This request only organizes the supplied case input without external evidence.",
    ),
    "retrieval_disabled": (
        "知识检索未启用，正文无法引入可核查的外部依据。",
        "Knowledge retrieval is disabled, so no verifiable external evidence was used.",
    ),
}


def case_source_summary(
    note: str, verification: dict, *, reasons: tuple[str, ...] = LIMITED_REASONS,
) -> tuple[str | None, dict]:
    if (not note.strip() or verification.get('policy_version') != 2
            or verification.get('status') != 'rejected'
            or verification.get('reason') not in reasons):
        return None, verification
    reason = verification.get("reason")
    zh_note, en_note = _REASON_NOTES.get(reason, _REASON_NOTES["unverified_claims_remain"])
    fence = '`' * max(3, max((len(match[0]) + 1 for match in re.finditer(r'`+', note)), default=3))
    text = (
        '## 病例资料摘要（诊疗结论未交付）\n\n'
        f'{zh_note}以下仅保留输入记录，不包含未通过核查的诊断、治疗或随访方案。'
        '影像模型结果另行展示。\n\n'
        '### 原始病例记录（用户提供，未独立核验）\n\n'
        f'{fence}text\n{note}\n{fence}\n\n'
        '待核实表述及原因保留在校验记录中。本摘要不能作为已通过核查的诊断报告导出 PDF。'
    )
    if not config.REPORT_LANGUAGE.startswith('zh'):
        text = (
            '## Case input summary (clinical conclusions withheld)\n\n'
            f'{en_note} Only the supplied record is retained below; imaging results are shown '
            'separately.\n\n'
            '### Original case input (user supplied, not independently validated)\n\n'
            f'{fence}text\n{note}\n{fence}\n\n'
            'Unresolved statements remain in the verification record. '
            'This summary cannot be exported as a verified diagnostic PDF.'
        )
    return text, {
        **verification, 'status': 'limited', 'diagnostic_status': verification.get('status', 'rejected'),
        'delivery_scope': 'case_input_only', 'source_note_sha256': text_digest(note),
        'delivered_text_sha256': text_digest(text),
    }
