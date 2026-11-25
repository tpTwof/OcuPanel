"""诊疗解释未完成核查时，保留输入资料的只读摘要，不交付失败草稿。"""
import re
from agents.tools.verification_audit import text_digest
from utils import config


def case_source_summary(note: str, verification: dict) -> tuple[str | None, dict]:
    if (not note.strip() or verification.get('policy_version') != 2
            or verification.get('status') != 'rejected'
            or verification.get('reason') != 'unverified_claims_remain'):
        return None, verification
    fence = '`' * max(3, max((len(match[0]) + 1 for match in re.finditer(r'`+', note)), default=3))
    text = (
        '## 病例资料摘要（诊疗结论未交付）\n\n'
        '本轮诊疗解释或具体建议仍有未解决的来源问题。以下仅保留输入记录，'
        '不包含未通过核查的诊断、治疗或随访方案。影像模型结果另行展示。\n\n'
        '### 原始病例记录（用户提供，未独立核验）\n\n'
        f'{fence}text\n{note}\n{fence}\n\n'
        '待核实表述及原因保留在校验记录中。本摘要不能作为已通过核查的诊断报告导出 PDF。'
    )
    if not config.REPORT_LANGUAGE.startswith('zh'):
        text = (
            '## Case input summary (clinical conclusions withheld)\n\n'
            'Clinical interpretation or specific advice still has unresolved source issues. '
            'Only the supplied record is retained below; imaging results are shown separately.\n\n'
            '### Original case input (user supplied, not independently validated)\n\n'
            f'{fence}text\n{note}\n{fence}\n\n'
            'Unresolved statements remain in the verification record. '
            'This summary cannot be exported as a verified diagnostic PDF.'
        )
    return text, {
        **verification, 'status': 'limited', 'diagnostic_status': 'rejected',
        'delivery_scope': 'case_input_only', 'source_note_sha256': text_digest(note),
        'delivered_text_sha256': text_digest(text),
    }
