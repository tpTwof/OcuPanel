"""把「资料未覆盖」的断言就地标注，使报告仍可交付。

为什么需要这一层：语料不可能覆盖所有临床表述。以往只要有一句查不到出处，
整份报告就会被扣留，用户只能拿到病例摘要——代价与收益不匹配。

现在的做法按问题性质分开：
- 数值/表述与资料冲突（如资料写 5–6 个月、报告写 2 个月）：必须改对，
  改不对仍拒答。这类错误改个数字就能修好，不该放行。
- 资料未覆盖（无依据）：在句末标注〔未获资料支持〕后照常交付，
  并在校验记录中逐条列出，页面与 PDF 一并展示。

标注文字刻意保持简短且不含医学断言，避免改变句子本身的判断。
"""

from __future__ import annotations

import re
from typing import Any

from modules.agent.tools.text_revision import locate

# 不能在句末加标注的句子：标题、列表项以外的结构不宜改动
MARK = "〔未获资料支持〕"


# 疑似「数值/表述与资料冲突」的特征：句子里出现具体数字、时间或剂量，
# 而判定理由提到资料中的不同数值。这类必须回模型改对，不能标注放行。
_CONFLICT_HINTS = re.compile(
    r"资料|证据|指南|原文|冲突|不一致|应为|改为|写成|不符", re.U)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")

# 「内容成立、只是引用不当」的表述：模型说这句话本身来自病例，但挂的编号不涉及。
_CITATION_MISMATCH = re.compile(
    r"未涉及|不涉及|未涵盖|不支持该引用|引用不当|来源不符", re.U)


def _looks_like_conflict(issue: dict[str, Any]) -> bool:
    """判定是否属于「与资料里的具体数值不符」这类必须改对的错误。

    例：资料写 5–6 个月、报告写 2 个月——改个数字就能修好，不该靠标注放行。
    这类问题的理由是「资料为 X」「与原文不符」等；而纯粹「资料没提到」的
    表述通常没有可比对的数字。
    """
    quote = issue.get("quote", "")
    reason = issue.get("reason", "")
    if not _CONFLICT_HINTS.search(reason):
        return False
    numbers_in_quote = _NUMBER.findall(quote)
    numbers_in_reason = _NUMBER.findall(reason)
    # 两边都有数字且不同 → 几乎可以确定是数值冲突
    return bool(numbers_in_quote) and bool(numbers_in_reason)


# 临床上的保守表述与资料边界声明：即使资料没逐字写，也不构成误导，
# 反而是应有的谨慎。这类被判「无依据」时可以直接标注交付。
_CAUTIOUS = re.compile(
    r"尚不能|不能(?:据此|由|从|仅凭|单独)|不足以|无法(?:据此|从)|需进一步|有待|"
    r"由(?:临床医师|接诊医师|医师)决定|不能排除|缺乏.*证据|依据病情|应结合|仅供参考|"
    r"证据不足|未见明确|非分级依据|尚在正常|大致正常|"
    r"可疑|需继续观察|需要随访观察|可在", re.U)

# 指南适用性说明：指出某条引用出自哪个地区/体系。这不是医学断言，
# 而是帮助读者判断条款适用范围的注解，标为「无依据」没有意义。
_SCOPE_NOTE = re.compile(
    r"适用说明|指南条款|中国指南|美国指南|英国指南|欧洲指南|引自|出处为", re.U)


def is_annotation_only(issue: dict[str, Any], case_context: str = "") -> bool:
    """该问题是否属于「资料未覆盖、可标注交付」的类别。

    判据刻意不看 impact 字段：提示词写着「无法判断影响时也用 core」、
    「不要把个体诊断或治疗建议标成 local」，模型因此几乎总标 core。
    以它作判据时降级交付形同虚设（实测交付率不足 1/4）。

    仍然阻断交付的（必须回模型改对）：
    - citation_control：引用了不存在的编号，报告不能带着查不到的编号发出去；
    - 数值冲突：资料写 5–6 个月、正文写 2 个月，改个数字就能修好；
    - 整句无依据（unsupported）的处置建议：剂量、时限、复查频率、手术用药；
    - 标为病例复述却不在病例输入里：等于把话塞进患者记录；
    - partial 且无法归因为引用不当、也不属于收窄结论的表述。

    其余（资料恰好没写到、引文被模型改写导致查无实据、保守表述、
    指南适用性说明）标注〔未获资料支持〕后交付，由审计记录逐条列出。
    """
    verdict = issue.get("verdict")
    origin = issue.get("origin")
    if origin == "citation_control":
        return False
    if _looks_like_conflict(issue):
        return False
    if verdict not in {"uncited", "unsupported", "partial"}:
        return False
    quote = issue.get("quote", "")

    if verdict == "partial":
        # 部分成立、部分与资料对不上。以下情形降级标注：
        # - 能确认是引用不当（内容成立、编号挂错）；
        # - 句子本身在收窄结论或说明适用范围；
        # - 带着有效引用编号——那是指南条款类表述，编号本身是真实存在的，
        #   只是措辞略有出入，标注后读者可回查原文。
        return bool(_CITATION_MISMATCH.search(issue.get("reason", ""))
                    or _CAUTIOUS.search(quote) or _SCOPE_NOTE.search(quote)
                    or _citations_in(quote))

    # 整句无依据的处置建议（剂量、时限、复查频率、手术用药）必须补依据。
    # 不能因为句子里恰好带着 [n] 就放过：问题正是该编号支持不了这句话。
    if _ACTIONABLE.search(quote):
        return False
    # 标为病例复述却凭空给出患者数值：那是编造检查结果，必须改掉。
    # 只对具体数字设防——「尚不能判定」这类定性表述标注后交付即可。
    if issue.get("basis") == "case_fact" and _invented_numbers(quote, case_context):
        return False
    return True


def _citations_in(quote: str) -> bool:
    """句子里是否带着引用编号。"""
    return bool(re.search(r"\[\s*-?\d+\s*\]", quote))


def _invented_numbers(quote: str, case_context: str) -> bool:
    """句中的数值是否确实无从病例输入而来。

    病例复述里的具体数值若在原始输入中找不到，说明模型编造了检查结果，
    这比措辞不严谨严重得多，不能靠标注放行。
    """
    if not case_context:
        return bool(re.findall(r"\d+(?:\.\d+)?", quote))
    case_numbers = set(re.findall(r"\d+(?:\.\d+)?", case_context))
    return any(number not in case_numbers
               for number in re.findall(r"\d+(?:\.\d+)?", quote))


# 含有具体处置的句子：剂量、时限、复查频率、手术或用药。
# 整句无依据时必须补依据，不能靠标注放行。
_ACTIONABLE = re.compile(
    r"应每周|应每\d|每日|每次\d|剂量|mg|ml|手术|用药|滴眼|激光|注射|"
    r"\d+\s*[-–~]\s*\d+\s*(?:天|周|个月|月|年)|每\s*\d+\s*(?:天|周|个月|月)", re.U)


def annotate_unverified(
    text: str, issues: list[dict[str, Any]], case_context: str = "",
    unknown: set[int] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """给可标注的问题句加上标记，返回新正文与已标注的记录。

    引用不当或引文查无实据的情况会同时去掉对应编号：既然无法确认该编号
    支持这句话，就不该把它留在报告里。无法唯一定位的句子跳过，不猜测位置。
    unknown 为正文里不存在的引用编号，带这类编号的句子不标注。
    """
    annotated: list[dict[str, Any]] = []
    for issue in issues:
        if not is_annotation_only(issue, case_context) or MARK in issue.get("quote", ""):
            continue
        quote = issue.get("quote", "")
        # 句子里若仍带着不存在的引用编号，一律不标注：那是引用错误，
        # 标注后交付等于把一条查不到出处的编号留给读者。
        if unknown and any(f"[{n}]" in quote.replace(" ", "") for n in unknown):
            continue
        span = locate(text, quote)
        if span is None:
            continue
        start, end = span
        segment = text[start:end]
        if issue.get("verdict") == "partial" or issue.get("origin") in {
                "source_audit", "grounding_gap"}:
            # 只去掉被指出的编号，保留句子其余部分
            for number in issue.get("citations") or []:
                segment = re.sub(rf"\[\s*{number}\s*\]", "", segment)
            segment = re.sub(r"[ \t]{2,}", " ", segment)
        body = segment.rstrip()
        tail = ""
        if body and body[-1] in "。！？.!?":
            tail = body[-1]
            body = body[:-1]
        replacement = f"{body}{tail}{MARK}"
        text = f"{text[:start]}{replacement}{text[end:]}"
        annotated.append({
            "quote": quote, "reason": issue.get("reason", ""),
            "basis": issue.get("basis", ""), "verdict": issue.get("verdict", ""),
            "origin": issue.get("origin", ""),
        })
    return text, annotated


def unannotated(issues: list[dict[str, Any]], case_context: str = "") -> list[dict[str, Any]]:
    """仍需阻断交付的问题（与资料冲突、无法定位等）。"""
    return [item for item in issues if not is_annotation_only(item, case_context)]