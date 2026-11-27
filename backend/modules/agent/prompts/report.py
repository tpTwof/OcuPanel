"""统一报告提示词：初稿、多病种综合与修订共用同一套读者输出要求。

版本号会写入 `verification.report_prompt_version` 与报告存档，用来比较不同
提示词版本生成的报告。修改约束时递增版本，不要只改文字——否则历史报告无法
说明当时依据的是哪一版要求。
"""

from core import config

REPORT_PROMPT_VERSION = 3

USE_CHINESE = config.REPORT_LANGUAGE.startswith("zh")

SECTION_TITLES_ZH = (
    "初步评估", "关键依据", "诊断评估与待补信息", "下一步建议", "局限与核验状态",
)
SECTION_TITLES_EN = (
    "Preliminary assessment", "Key evidence",
    "Diagnostic assessment and missing information",
    "Next steps", "Limitations and verification status",
)

_SECTION_DETAIL = {
    "zh": (
        "按病种、眼别说明当前评估、支持发现与不确定性；医学解释就地引用资料编号。",
        "分开写病例记录（用户提供）、影像模型结果与外部证据，不混为一谈。",
        "说明判断依据、尚缺的前提，以及可考虑检查的目的；不要把未提供写成未检查。",
        "只给有依据的处置、随访与教育建议，逐项说明目的和适用前提。",
        "说明模型限制、证据缺口与来源审核状态，集中写一段，不逐节重复。",
    ),
    "en": (
        "State the current assessment, supporting findings and uncertainty per disease and eye; "
        "attach evidence numbers to medical interpretation here.",
        "Separate supplied case records, imaging model output and external evidence.",
        "Explain the basis, the missing premises and the purpose of any suggested test; "
        "never describe an unprovided test as not performed.",
        "Give only supported management, follow-up and education advice, each with its purpose "
        "and applicable preconditions.",
        "State model limits, evidence gaps and the review status of the sources in one paragraph.",
    ),
}


def report_section_titles() -> tuple[str, ...]:
    return SECTION_TITLES_ZH if USE_CHINESE else SECTION_TITLES_EN


def _structure_block() -> str:
    language = "zh" if USE_CHINESE else "en"
    lines = [
        "\n\nReport structure (use these section titles in the report language):"
        if not USE_CHINESE else "\n\n报告结构（按报告语言使用以下小节标题）："
    ]
    for index, (title, detail) in enumerate(zip(report_section_titles(), _SECTION_DETAIL[language]), 1):
        lines.append(f"{index}. {title} — {detail}")
    lines.append(
        "A section may state that no supported content is available; do not fill it with "
        "unsupported diagnoses, tests, doses, intervals or urgency."
        if not USE_CHINESE else
        "如果某一部分没有可支持的依据，可以直接写明「当前无法给出」，不要为了填满章节编造诊断、"
        "检查、剂量、间隔或紧急程度。"
    )
    return "\n".join(lines)


REPORT_REQUIREMENTS = (
    "\n\nFinal report requirements: answer what the analysis currently indicates and what to do next. "
    "Start with a clearly titled preliminary assessment, before the case recap or limitations. "
    "For each selected disease, state the current assessment supported by the supplied case data and evidence, "
    "the main supporting findings, and the remaining uncertainty. Use a cautious conclusion when warranted; "
    "Attach the applicable evidence numbers to medical interpretation in this opening assessment itself; "
    "do not defer all citations to a later section. Explain which findings need assessment under the "
    "cited criteria rather than making an uncited claim that model and clinical findings are concordant. "
    "Do not replace the whole assessment with a statement that diagnosis requires comprehensive evaluation."
    "\n\nFollow these constraints:"
    "\n1. Organize the report with the sections below, in order."
    "\n2. Distinguish a previously documented diagnosis, an imaging model hint and your preliminary "
    "assessment. Never convert a model score, a missing field or a single finding into a confirmed "
    "diagnosis, exclusion or stage."
    "\n3. Separate the left and right eye and identify the source of each conclusion (uploaded image, "
    "clinical record or external evidence). Do not infer an unphotographed eye from the other eye."
    "\n4. Every medical explanation and every specific recommendation must cite evidence that supports "
    "that statement and applies to this case. Cite only the clauses that use external knowledge."
    "\n5. Cite the input source of case facts. Never present a guideline clause as this patient's "
    "examination record or measurement."
    "\n6. For each recommendation, state its purpose and preconditions, and distinguish tests already "
    "completed, results not provided and information still to be assessed. Do not order a test already "
    "documented as completed unless the input or cited evidence gives a specific reason to repeat it; "
    "any need to repeat remains a clinician's decision. Do not call an unprovided test 'not performed'."
    "\n7. Do not invent a diagnosis, examination value, dose, treatment plan, urgency or follow-up "
    "interval to make the report appear complete."
    "\n8. When information is insufficient, state precisely what is missing and which judgment that "
    "gap limits. Use a cautious conclusion where warranted."
    "\n9. Similar cases may be cited as reference only; they never replace the diagnostic basis of the "
    "current case."
    "\n10. If sources conflict, applicability is unclear, or the source review is incomplete, keep that "
    "limitation explicit instead of writing a definite conclusion. Reference-backed test or treatment "
    "options must retain their population and setting limits; avoid 'mandatory' or 'standard protocol' "
    "wording when applicability has not been established."
    "\n11. When there is no supporting evidence, narrow or omit the statement. Do not substitute a "
    "generic checklist for case-specific analysis, and do not add uncited physiological explanations."
    "\n12. Keep these requirements when revising or regenerating: preserve a supported preliminary "
    "assessment and useful next steps while repairing unsupported clauses."
    "\n\nThe application displays raw model metrics and the full source list separately; refer to them "
    "without restating numeric results or repeating the whole list. Keep the report concise: summarize "
    "case facts in 2–4 sentences, do not repeat the entire note, and close with one concise limitations "
    "paragraph instead of repeating the same caveat in every section. Use section titles in the report "
    "language."
    + _structure_block()
)
