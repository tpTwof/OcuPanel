from typing import Any
from llm.models import LLMCall
from knowledge.retrieval import format_evidence_block
from llm.prompts import LANGUAGE_INSTRUCTION

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
            f"computer-aided analysis, and a clinician's note:\n\n{combined_reports}\n\n"
            "Based on the information above, write a final comprehensive diagnostic report. "
            "Summarize the key findings, provide "
            "diagnostic reasoning, and include appropriate recommendations. "
            "Do not mention any subreports. The report should be "
            f"written in a professional, neutral tone suitable for a clinical team or patient record."
            + LANGUAGE_INSTRUCTION
            + format_evidence_block(evidence or [])
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
                "不得换一种说法把同样的结论再写一遍。报告中每一条结论性表述都必须在句末标注资料编号 [n]。"
            )

        reply = self.chat_with_gpt(director_prompt, reset=True)
        if not isinstance(reply, str) or not reply.strip() or reply.startswith("Error:"):
            raise RuntimeError("Director failed to produce a report")
        from .tools.evidence import EvidenceTools
        numbers = {item["id"]: item.get("index", i) for i, item in enumerate(evidence or [], 1)}
        EvidenceTools(evidence or [], numbers).validate_citations(reply)
        return reply
