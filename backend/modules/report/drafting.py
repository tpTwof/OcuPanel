"""按本次报告的证据和专科数量选择撰稿路径。"""
from collections.abc import Callable
from typing import Any

from modules.agent import DirectorAgent, ParallelOrchestrator, SpecialistAgent
from modules.agent.verifier import CitationVerifier
from core import config_impl as config

Issues = list[dict[str, Any]]
VerifiedDraft = tuple[str | None, dict[str, Any]]


def generate_verified_draft(
    specialists: list[SpecialistAgent],
    director: DirectorAgent,
    contexts: dict[str, str],
    case_context: str,
    evidence_by_role: dict[str, list[dict[str, Any]]],
    evidence: list[dict[str, Any]],
    verify: Callable[[str, list[dict[str, Any]], Callable[[Issues], str]], VerifiedDraft],
) -> VerifiedDraft:
    if config.VERIFY_ENABLED and not evidence:
        return None, CitationVerifier.no_evidence_result()

    numbers = {item["id"]: item["index"] for item in evidence}
    if len(specialists) == 1:
        agent = specialists[0]

        def draft(issues: Issues | None = None) -> str:
            return agent.execute(
                contexts[agent.name], evidence_by_role[agent.name], numbers,
                final_report=True, issues=issues,
            )
    else:
        if config.MULTI_AGENT_MODE != "parallel":
            raise NotImplementedError(
                f"MULTI_AGENT_MODE={config.MULTI_AGENT_MODE} 尚未实现，当前仅支持 parallel。"
            )
        reports = ParallelOrchestrator().run(specialists, contexts, evidence_by_role, numbers)

        def draft(issues: Issues | None = None) -> str:
            return director.execute(
                reports, evidence, issues, context=case_context, evidence_by_role=evidence_by_role,
            )

    return verify(draft(), evidence, draft)
