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

# 这些 verdict 表示「资料里没有」，可以标注后交付；
# partial 表示「一部分成立、一部分与资料冲突」，属于需要改对的错误。
UNSUPPORTED_VERDICTS = {"uncited"}


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
    r"尚不能|不能据此|不能由|不足以|无法据此|需进一步|有待|由临床医师|"
    r"不能排除|缺乏.*证据|依据病情|应结合|仅供参考|"
    r"证据不足|未见明确|非分级依据", re.U)

# 指南适用性说明：指出某条引用出自哪个地区/体系。这不是医学断言，
# 而是帮助读者判断条款适用范围的注解，标为「无依据」没有意义。
_SCOPE_NOTE = re.compile(
    r"适用说明|指南条款|中国指南|美国指南|英国指南|欧洲指南|引自|出处为", re.U)


def is_annotation_only(issue: dict[str, Any], case_context: str = "") -> bool:
    """该问题是否属于「资料未覆盖、可标注交付」的类别。

    需要同时满足：
    1. 属于「资料没覆盖到」而非「与资料冲突」——与资料里的数值或结论
       对不上（如资料 5–6 个月、正文 2 个月）必须回模型改对；
    2. 引用编号问题（citation_control / grounding_gap）一律阻断，
       那是引用错误而不是缺出处；
    3. 满足以下任一条件：
       - 影响被判为 local；
       - 句子是保守表述或资料边界声明（_CAUTIOUS）；
       - 句子是指南适用性说明（_SCOPE_NOTE）；
       - 句中标为病例复述（basis=case_fact），且内容确实取自病例输入。

    第 3 条为什么不能只看 impact：该字段由模型主观填写，实测它把大量
    「恰好资料没写到」的句子也标成 core，导致降级交付形同虚设。这些句子
    要么在收窄结论，要么在说明适用范围，要么在复述病例，标注后交付不会误导。

    case_fact 必须核对病例输入：否则模型可以把任意断言标成「病例事实」
    绕过核查，那等于关掉了校验。
    """
    verdict = issue.get("verdict")
    origin = issue.get("origin")
    if origin in {"citation_control", "grounding_gap"}:
        return False
    if _looks_like_conflict(issue):
        return False
    if verdict not in {"uncited", "unsupported", "partial"}:
        return False
    quote = issue.get("quote", "")
    # 带具体处置的句子一律不降级：剂量、时限、复查频率、手术用药都要核对依据
    if _ACTIONABLE.search(quote):
        return False
    if issue.get("impact") == "local":
        if verdict == "partial":
            return bool(_CITATION_MISMATCH.search(issue.get("reason", "")))
        return True
    # 标为病例复述的，内容必须真的来自病例输入；否则模型可以用这个标签绕过核查
    if issue.get("basis") == "case_fact":
        return _matches_case(quote, case_context)
    if _CAUTIOUS.search(quote) or _SCOPE_NOTE.search(quote):
        return True
    return False


# 含有具体处置的句子：剂量、时限、复查频率、手术或用药。这类必须核对依据，
# 不能因为句子前半段是病例复述就整句放行。
_ACTIONABLE = re.compile(
    r"应每周|应每\d|每日|每次\d|剂量|mg|ml|手术|用药|滴眼|激光|注射|"
    r"\d+\s*[-–~]\s*\d+\s*(?:天|周|个月|月|年)|每\s*\d+\s*(?:天|周|个月|月)", re.U)


def _matches_case(quote: str, case_context: str) -> bool:
    """句子的实词是否确实出现在病例输入里。

    用去标点的字面包含判断：病例复述通常就是改写自输入，
    要求逐字相同会把「主诉视物模糊」与「患者诉视物模糊」这类误判。
    """
    if not case_context:
        return False
    stripped = re.sub(r"[\s，。；：、,.;:（）()\[\]【】]", "", quote)
    if not stripped:
        return False
    case = re.sub(r"[\s，。；：、,.;:（）()\[\]【】]", "", case_context)
    # 取句子最长的若干片段做包含判断，容忍少量改写
    for size in (12, 9, 6):
        for start in range(0, max(1, len(stripped) - size + 1)):
            fragment = stripped[start:start + size]
            if len(fragment) == size and fragment in case:
                return True
    return False


def annotate_unverified(
    text: str, issues: list[dict[str, Any]], case_context: str = "",
    unknown: set[int] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """给可标注的问题句加上标记，返回新正文与已标注的记录。

    引用不当的情况（句子内容成立、只是挂的编号不涉及）会同时去掉该编号，
    避免标注后仍留着一条对不上的引用。无法唯一定位的句子跳过，不猜测位置。
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
        if issue.get("verdict") == "partial":
            # 只去掉被指出的编号，保留句子其余部分
            for number in issue.get("citations") or []:
                segment = re.sub(rf"\[\s*{number}\s*\]", "", segment)
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
        })
    return text, annotated


def unannotated(issues: list[dict[str, Any]], case_context: str = "") -> list[dict[str, Any]]:
    """仍需阻断交付的问题（与资料冲突、无法定位等）。"""
    return [item for item in issues if not is_annotation_only(item, case_context)]