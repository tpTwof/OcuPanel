from typing import Any
from core.llm.models import LLMCall
from modules.knowledge.retrieval import format_evidence_block
from modules.agent.prompts.language import LANGUAGE_INSTRUCTION
from modules.agent.prompts.report import REPORT_REQUIREMENTS

class DirectorAgent:
    name = "director"
    role_description = "综合各专科结论并依据反馈修订报告"

    def __init__(self, llm_call: LLMCall) -> None:
        self.chat_with_gpt = llm_call

    def execute(
        self,
        expert_reports: dict[str, str],
        evidence: list[dict[str, Any]] | None = None,
        avoid: list[dict[str, Any]] | None = None,
        *,
        context: str = "",
        evidence_by_role: dict[str, list[dict[str, Any]]] | None = None,
    ) -> str:
        """Generate a director-level synthesis based on all expert reports

        avoid: 上一版被引用校验判为无依据的断言。重生成时把它们作为「禁止写入
        清单」交给 Director —— 不告诉它哪里错了，它会换个说法把同样的幻觉写回来。
        """
        combined_reports = "\n\n".join(
            [f"{role} Report:\n{report}" for role, report in expert_reports.items()]
        )
        director_prompt = (
            "The following is clinical information regarding a case of fundus disease, "
            "including findings from a fundus image, "
            f"computer-aided analysis, and a clinician's note:\n\n{context}\n\n{combined_reports}\n\n"
            "Based on the information above, write a final comprehensive diagnostic report. "
            "Summarize the key findings, provide "
            "diagnostic reasoning, and include appropriate recommendations. "
            "Organize findings by disease. Keep disagreements and missing information explicit, "
            "and consolidate duplicate recommendations. "
            "Omit unrelated or inapplicable reference clauses instead of discussing them just to cite them. "
            "The application displays raw model metrics separately, so refer to them without restating numeric results. "
            "Separate supplied case facts from cautious inference and specific recommendations. "
            "Do not cite guidelines as the source of case data. Explain how case findings relate to "
            "cited diagnostic criteria without implying that the references establish this patient's diagnosis. "
            "Keep the report concise. Do not invent an exhaustive test checklist or uncited physiology. "
            "Do not reclassify reported symptoms as absent to fit a screening guideline. "
            "Summarize rather than repeat the full case note or raw model values. "
            "If FLAIR was used, treat it as research-only prompt matching. Do not infer disease "
            "presence, absence, stage, lesion location, or image quality from its output. "
            "Do not mention any subreports. The report should be "
            f"written in a professional, neutral tone suitable for a clinical team or patient record."
            + LANGUAGE_INSTRUCTION
            + REPORT_REQUIREMENTS
            + format_evidence_block(evidence or [])
        )
        if evidence_by_role is not None:
            prompt_scope = "\n".join(
                f"- {role}: " + (", ".join(f"[{item['index']}]" for item in items) or "no evidence retrieved")
                for role, items in evidence_by_role.items()
            )
            director_prompt += (
                "\nUse the references assigned to each disease. When a disease has no references, "
                "state that evidence gap and limit its section to case observations and missing information.\n"
                + prompt_scope
            )
        if avoid:
            listed = "\n".join(
                f"- {str(it.get('quote', ''))[:80]}（问题：{it.get('verdict')}；{it.get('reason', '')}）"
                for it in list(avoid)[:12]
            )
            director_prompt += (
                "\n\n【上一版被判定缺乏依据的断言，本次禁止原样写入】\n"
                f"{listed}\n"
                "上述内容若要提及，只能写成资料支持得了的表述，或直接写「现有资料未涵盖」，"
                "不得换一种说法把同样的结论再写一遍。病例事实对照原始输入，不伪装成文献结论；"
                "依赖外部知识的解释与具体处置按分句标注资料编号 [n]。保留事实，缺依据的具体处置不编造。"
            )

        reply = self.chat_with_gpt(director_prompt, reset=True)
        if not isinstance(reply, str) or not reply.strip() or reply.startswith("Error:"):
            raise RuntimeError("Director failed to produce a report")
        # 引用编号错误由 Verifier 确定性识别并修订，草稿不在这里直接中断。
        return reply
