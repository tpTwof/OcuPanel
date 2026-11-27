"""单病种成稿：一次模型调用，不做工具循环。

以前的实现允许模型连续三次 search/read 证据，但证据全文本来就整块拼在提示词里，
循环只会多花 1-3 次调用而拿不到新信息。检索发生在撰稿之前
（`modules/knowledge/service.py`），这里不再提供二次检索入口。
"""

import json
from typing import Any

from core.llm.models import LLMCall
from modules.agent.models import SpecialistRole
from .tools.evidence import EvidenceTools
from .tools.json_response import parse_agent_decision
from modules.knowledge.retrieval import format_evidence_block
from modules.agent.prompts.language import LANGUAGE_INSTRUCTION
from modules.agent.prompts.report import REPORT_REQUIREMENTS

NO_EVIDENCE_CLAUSE = (
    "\nNo reference was retrieved for this disease. State the evidence gap and "
    "limit the analysis to supplied case observations and missing information."
)

FINAL_REPORT_CLAUSE = (
    "\nWrite the final report for the reader. Organize the interpretation, missing "
    "information and any supported recommendations. The application displays raw model "
    "metrics separately, so refer to them without restating numeric results."
    " Use separate sections for supplied case data, evidence-based interpretation and "
    "next steps with limitations. Cite only the clauses that use external knowledge. "
    "Omit unsupported specific schedules or treatments; leave their determination to the treating clinician."
    " Keep the report concise. Do not add an exhaustive generic checklist, uncited physiological "
    "explanations or a repeated list of all references. Missing information should be limited to "
    "what the supplied evidence or model warnings actually require. Do not reclassify symptoms "
    "as absent to fit a screening population. Prefer omitting an irrelevant reference to explaining "
    "at length why it is inapplicable."
    " Aim for roughly 600–1000 Chinese characters or 250–400 English words. "
    "Summarize case facts in 2–4 sentences; do not repeat the entire note. "
    "The interface already displays raw model values and sources, so do not repeat them "
    "or add unsupported explanations of their clinical thresholds."
    + REPORT_REQUIREMENTS
)

ISSUES_CLAUSE = "\nCorrect the following claims based on the supplied references, or omit them: {issues}"


def build_specialist_prompt(
    context: str,
    role_name: str,
    instructions: str,
    evidence: list[dict[str, Any]],
    numbers: dict[str, int],
    *,
    final_report: bool = False,
    issues: list[dict[str, Any]] | None = None,
) -> str:
    """拼接专科提示词。纯函数，便于单测确认每段约束都还在。"""
    prompt = (
        f"{context}\nAs a {role_name}, {instructions} "
        "Distinguish model predictions, measurements, missing data and recommendations. "
        "Do not infer untested diseases or severity from probability. Cite evidence for medical claims. "
        "Use only references relevant to this case; omit unrelated disease or screening clauses, "
        "including clauses explicitly described as inapplicable. "
        "Separate supplied case facts, cautious case interpretation, general next steps and "
        "specific reference-backed recommendations. Case facts come from the input, not from a guideline. "
        "An interpretation may combine case findings with cited diagnostic criteria without claiming "
        "that a reference describes this exact patient. Keep uncertainty explicit; do not upgrade "
        "an assessment to a definitive diagnosis, exclusion or stage. "
        + LANGUAGE_INSTRUCTION + format_evidence_block(evidence, numbers)
    )
    if not evidence:
        prompt += NO_EVIDENCE_CLAUSE
    if final_report:
        prompt += FINAL_REPORT_CLAUSE
    if issues:
        prompt += ISSUES_CLAUSE.format(issues=json.dumps(issues[:12], ensure_ascii=False))
    return prompt


class SpecialistAgent:
    def __init__(self, role: SpecialistRole, llm_call: LLMCall) -> None:
        if not role.name:
            raise ValueError('Invalid agent configuration')
        self.name = role.name
        self.instructions = role.instructions
        self.llm_call = llm_call

    def execute(
        self,
        context: str,
        evidence: list[dict[str, Any]],
        numbers: dict[str, int],
        *,
        final_report: bool = False,
        issues: list[dict[str, Any]] | None = None,
    ) -> str:
        prompt = build_specialist_prompt(
            context, self.name, self.instructions, evidence, numbers,
            final_report=final_report, issues=issues,
        )
        reply = self.llm_call(prompt, reset=True)
        if not isinstance(reply, str) or not reply.strip() or reply.startswith('Error:'):
            raise RuntimeError(f'Agent {self.name} failed: {reply}')
        decision = parse_agent_decision(reply)
        action = decision.get('action')
        if action != 'final':
            # 提示词已不再提供工具协议；模型仍返回结构化动作说明它没有按约定成稿，
            # 这属于协议失败，不能把 JSON 当报告交出去。
            raise ValueError(f'Agent returned an unsupported action: {action}')
        text = decision.get('text')
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Empty agent analysis')
        if not final_report:
            EvidenceTools(evidence, numbers).validate_citations(text)
        return text
