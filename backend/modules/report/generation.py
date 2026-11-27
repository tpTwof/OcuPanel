from __future__ import annotations
import sys
from collections import Counter
from dataclasses import asdict
from functools import partial
from pathlib import Path
from typing import Any, BinaryIO, Callable

from modules.agent import DirectorAgent, SpecialistAgent
from modules.agent.planner import RetrievalPlanner
from modules.agent.prompts.report import REPORT_PROMPT_VERSION
from modules.vision.models import EyeAnalysis
from modules.vision.analysis import DEFAULT_DISEASES
from core.llm.models import LLMConfiguration
from modules.report.case_facts import CaseFacts, build_case_facts
from modules.report.models import ReportResult
from modules.agent.roles import DISEASE_ROLES
from core import config
from core.llm.client import LLMClient
from modules.knowledge.metadata import (
    clause_diseases,
    resolve_material_type,
    resolve_review_status,
)
from modules.knowledge.question_retrieval import RetrievalOutcome, retrieve_for_plan
from modules.knowledge.service import get_retriever, retrieve_evidence
from modules.knowledge.report_focus import disease_focus
from modules.report.context import build_context
from modules.report.drafting import generate_verified_draft
from modules.report.source_summary import case_source_summary
from modules.report.pdf import PDFRenderer
from modules.report.utils.messages import reject_message
from modules.agent.tools.text_revision import content_len
from modules.agent.verifier import CitationVerifier

# v2 流程中「只有病例输入、没有可用核查正文」的受限摘要原因。
# 与 legacy 的 no_evidence 拒答区分开：新流程把它作为受限摘要交付。
LIMITED_SUMMARY_REASONS = (
    "unverified_claims_remain", "retrieval_failed", "no_evidence",
    "no_retrieval_requested", "retrieval_disabled",
)
_RETRIEVAL_STOP_REASONS = {
    "error": "retrieval_failed",
    "empty": "no_evidence",
    "not_needed": "no_retrieval_requested",
    "disabled": "retrieval_disabled",
}

def build_generator_for_user(cfg: LLMConfiguration) -> "MedicalReportGenerator":
    """用**用户自己的** LLM 配置造一个生成器。

    这是"个人管理 API"的落点：模型、端点、密钥全部来自该用户在 SQLite 里的配置，
    代码里不再有任何硬编码的厂商/模型。cfg 由 storage.load_llm_config() 解密得到。
    """
    return MedicalReportGenerator(
        api_key=cfg.get("api_key"),
        model=cfg.get("model") or None,
        base_url=(cfg.get("base_url") or None),
    )


class MedicalReportGenerator(LLMClient, PDFRenderer):
    reject_message = staticmethod(reject_message)

    def __init__(
        self, api_key: str | None = None, model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        super().__init__(api_key=api_key, model=model, base_url=base_url)
        from modules.agent.prompts.language import LANGUAGE_INSTRUCTION
        self.system_prompt = {
            "role": "system",
            "content": "You are an ophthalmic analysis assistant. "
                       "Use only supplied case findings and evidence. " + LANGUAGE_INSTRUCTION,
        }
        self.messages = [self.system_prompt]


    def generate(
        self,
        image: str | Path | BinaryIO,
        note: str,
        job_dir: Path,
        diseases: tuple[str, ...] = DEFAULT_DISEASES,
        on_stage: Callable[[str], None] | None = None,
    ) -> ReportResult:
        """生成报告。on_stage 用于上报进度阶段，不改变生成逻辑。"""
        import imageio.v2 as imageio
        from modules.vision import analyze_fundus

        def stage(name: str) -> None:
            if on_stage is not None:
                on_stage(name)

        job_dir = Path(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)
        if hasattr(image, "read"):
            image_path = job_dir / "input_image"
            image_path.write_bytes(image.read())
        else:
            image_path = image
        stage("影像分析")
        analysis: EyeAnalysis = analyze_fundus(image_path, diseases=diseases)
        glaucoma = analysis.diseases.get("glaucoma")
        ratio = glaucoma.measurements.get("area_equivalent_cdr") if glaucoma else None
        overlay_path = ""
        overlay = analysis.overlays.get("optic_disc_cup")
        if overlay is not None:
            overlay_path = str(job_dir / "segmented_image.png")
            imageio.imwrite(overlay_path, overlay)

        contexts: dict[str, str] = {}
        evidence_by_role: dict[str, list[dict[str, Any]]] = {}
        evidence_by_id: dict[str, dict[str, Any]] = {}
        agents = []
        missing_evidence = []
        for disease, finding in analysis.diseases.items():
            role = DISEASE_ROLES[disease]
            agents.append(SpecialistAgent(role, self.chat_with_gpt))
            context = build_context({disease: finding}, note)
            contexts[role.name] = context
            role_items = evidence_by_role[role.name] = []
            retrieved = retrieve_evidence(context, boost=disease_focus(disease), disease=disease)
            if not retrieved:
                missing_evidence.append(disease)
            for item in retrieved:
                item_id = item["id"]
                if item_id not in evidence_by_id:
                    evidence_by_id[item_id] = {**item, "index": len(evidence_by_id) + 1}
                role_items.append(evidence_by_id[item_id])

        evidence = list(evidence_by_id.values())
        visual_findings = {
            disease: asdict(finding) for disease, finding in analysis.diseases.items()
        }
        case_context = build_context(analysis.diseases, note)
        stage("撰稿与核查")
        summary, verification = generate_verified_draft(
            agents, DirectorAgent(self.chat_with_gpt), contexts,
            case_context, evidence_by_role, evidence,
            partial(self.verify_synthesis, case_context=case_context),
        )
        if missing_evidence:
            verification["missing_evidence_diseases"] = missing_evidence
        if summary is None:
            summary, verification = case_source_summary(note, verification)
        return ReportResult(summary, verification, ratio, overlay_path, evidence, visual_findings)

    def generate_v2(
        self,
        image: str | Path | BinaryIO,
        note: str,
        job_dir: Path,
        diseases: tuple[str, ...] = DEFAULT_DISEASES,
        on_stage: Callable[[str], None] | None = None,
        *,
        laterality: str | None = None,
        captured_at: str | None = None,
        device: str = "",
        synthetic: bool = False,
        filename: str = "",
    ) -> ReportResult:
        """按需检索流程：病例事实 → 检索规划 → 按问题检索 → 统一提示词 → 核查。

        与 legacy 的区别只在证据从哪来、提示词用哪一版；影像分析、专科撰稿、
        Director 综合与 Verifier 核查全部复用。检索故障与「没有相关证据」分开
        记录：前者只交付病例输入摘要，后者按知识缺口收窄正文。
        """
        import imageio.v2 as imageio
        from modules.vision import analyze_fundus

        def stage(name: str) -> None:
            if on_stage is not None:
                on_stage(name)

        job_dir = Path(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)
        if hasattr(image, "read"):
            image_path = job_dir / "input_image"
            image_path.write_bytes(image.read())
        else:
            image_path = image
        stage("影像分析")
        analysis: EyeAnalysis = analyze_fundus(image_path, diseases=diseases)
        glaucoma = analysis.diseases.get("glaucoma")
        ratio = glaucoma.measurements.get("area_equivalent_cdr") if glaucoma else None
        overlay_path = ""
        overlay = analysis.overlays.get("optic_disc_cup")
        if overlay is not None:
            overlay_path = str(job_dir / "segmented_image.png")
            imageio.imwrite(overlay_path, overlay)
        visual_findings = {
            disease: asdict(finding) for disease, finding in analysis.diseases.items()
        }

        stage("病例事实整理")
        facts = build_case_facts(
            visual_findings, note, laterality=laterality, captured_at=captured_at,
            device=device, synthetic=synthetic, filename=filename,
        )
        stage("检索规划")
        plan = RetrievalPlanner(self.chat_with_gpt).plan(facts, tuple(analysis.diseases))
        stage("按问题检索")
        outcome = retrieve_for_plan(
            plan, diseases=tuple(analysis.diseases), case_features=facts.key_features(),
        )
        evidence = outcome.evidence
        record = self._pipeline_record(plan, outcome, facts, evidence)

        stop_reason = _RETRIEVAL_STOP_REASONS.get(outcome.status)
        if stop_reason or not evidence:
            reason = stop_reason or "no_evidence"
            # 没有可核查证据时不撰稿：只保留输入资料摘要，并说明是检索故障还是缺口。
            verification = self._limited_record(reason, record)
            summary, verification = case_source_summary(
                note, verification, reasons=LIMITED_SUMMARY_REASONS,
            )
            if summary is None:
                verification = {
                    **verification,
                    "status": "error" if reason == "retrieval_failed" else "rejected",
                    "failure_kind": "retrieval",
                }
            return ReportResult(
                summary, verification, ratio, overlay_path, evidence, visual_findings,
            )

        evidence_by_role = self._group_evidence(analysis, evidence)
        agents, contexts = self._agents_and_contexts(analysis, note, facts)
        numbers = {item["id"]: item["index"] for item in evidence}
        case_context = facts.verification_context()
        stage("撰稿与核查")
        summary, verification = generate_verified_draft(
            agents, DirectorAgent(self.chat_with_gpt), contexts, case_context,
            evidence_by_role, evidence,
            partial(
                self.verify_synthesis, case_context=case_context,
                case_facts=self._verifier_facts(facts), diseases=tuple(analysis.diseases),
            ),
        )
        verification = {**verification, **record}
        if summary is None:
            summary, verification = case_source_summary(
                note, verification, reasons=LIMITED_SUMMARY_REASONS,
            )
        missing = [disease for disease in analysis.diseases
                   if not evidence_by_role.get(DISEASE_ROLES[disease].name)]
        if missing:
            verification["missing_evidence_diseases"] = missing
        return ReportResult(
            summary, verification, ratio, overlay_path, evidence, visual_findings,
        )

    @staticmethod
    def _verifier_facts(facts: CaseFacts) -> list[dict[str, Any]]:
        return [
            {"id": fact.id, "kind": fact.kind, "eye": fact.eye, "text": fact.text,
             "numbers": list(fact.numbers)}
            for fact in facts.facts
        ]

    def _agents_and_contexts(
        self, analysis: EyeAnalysis, note: str, facts: CaseFacts,
    ) -> tuple[list[SpecialistAgent], dict[str, str]]:
        """每个病种一个专科上下文；缺失与冲突信息必须进入撰稿提示词。"""
        gaps = facts.gaps_note()
        agents: list[SpecialistAgent] = []
        contexts: dict[str, str] = {}
        for disease, finding in analysis.diseases.items():
            role = DISEASE_ROLES[disease]
            agents.append(SpecialistAgent(role, self.chat_with_gpt))
            context = build_context({disease: finding}, note)
            contexts[role.name] = f"{context}\n{gaps}" if gaps else context
        return agents, contexts

    @staticmethod
    def _group_evidence(
        analysis: EyeAnalysis, evidence: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """按问题所属病种把证据分给专科；未限病种的条款对所有病种可见。"""
        by_role: dict[str, list[dict[str, Any]]] = {
            DISEASE_ROLES[disease].name: [] for disease in analysis.diseases
        }
        for item in evidence:
            assigned = {
                entry.get("disease") for entry in item.get("questions") or []
                if entry.get("disease")
            }
            if not assigned:
                scope = clause_diseases(item)
                assigned = set(scope) if scope is not None else set(analysis.diseases)
            for disease in analysis.diseases:
                if disease in assigned:
                    by_role[DISEASE_ROLES[disease].name].append(item)
        return by_role

    @staticmethod
    def _pipeline_record(
        plan: Any, outcome: RetrievalOutcome, facts: CaseFacts,
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """检索、提示词版本、病例事实与知识缺口的可追溯记录。"""
        gaps = [{"kind": "corpus", **gap} for gap in outcome.unresolved]
        gaps += [
            {"kind": "case_fact", "id": fact.id, "text": fact.text}
            for fact in (*facts.missing, *facts.conflicts)
        ]
        gaps += [{"kind": "planner", "text": text} for text in plan.missing_information]
        unknown = Counter(
            field for item in evidence for field in item.get("applicability_unknown") or ()
        )
        return {
            "planner_version": plan.version,
            "report_prompt_version": REPORT_PROMPT_VERSION,
            "retrieval": {"plan": plan.summary(), **outcome.summary()},
            "case_facts": facts.summary(),
            "knowledge_gaps": gaps[:24],
            "applicability": {
                "material_types": dict(Counter(resolve_material_type(i) for i in evidence)),
                "review_status": dict(Counter(resolve_review_status(i) for i in evidence)),
                "unknown_applicability": dict(unknown),
                "unreviewed_evidence": [
                    item.get("id") for item in evidence
                    if resolve_review_status(item) != "verified"
                ][:12],
            },
        }

    @staticmethod
    def _limited_record(reason: str, record: dict[str, Any]) -> dict[str, Any]:
        """没有可核查正文时的记录骨架；由 case_source_summary 转成受限摘要。"""
        return {
            "status": "rejected", "reason": reason, "rounds": 0, "initial_issues": 0,
            "remaining_issues": [], "fixed": [], "deleted": 0, "format_retries": 0,
            "policy_version": 2, "draft_text_sha256": "", "review_log": [],
            "case_fact_matches": [], "source_manifest": {"evidence": []},
            **record,
        }

    def verify_synthesis(
        self,
        text: str,
        evidence: list[dict[str, Any]],
        regenerate: Callable[[list[dict[str, Any]]], str] | None = None,
        *, case_context: str = "",
        case_facts: list[dict[str, Any]] | None = None,
        diseases: tuple[str, ...] = (),
    ) -> tuple[str | None, dict[str, Any]]:
        """调用校验 Agent，必要时通过回调重新生成。

        返回 (文本, 校验报告)。**文本为 None 表示不交报告**（拒答或校验故障），
        调用方必须据此走拒答路径，不能把原文返回给用户。
        """
        from modules.agent.tools.applicability import applicability_issues

        if not content_len(text) or text.lstrip().startswith("Error:"):
            return None, {"status": "rejected", "reason": "empty_text"}
        if not config.VERIFY_ENABLED:
            from modules.agent.tools.evidence import unknown_citation_issues
            citation_issues = unknown_citation_issues(text, evidence)
            issues = [
                *citation_issues,
                *applicability_issues(
                    text, evidence, case_context=case_context,
                    case_facts=case_facts or (), diseases=diseases,
                ),
            ]
            if issues:
                return None, {
                    "status": "rejected",
                    "reason": "unknown_citations" if citation_issues else "unsupported_claims",
                    "remaining_issues": issues,
                }
            return text, {"status": "disabled"}
        try:
            verifier = CitationVerifier(
                lambda prompt, system=None, temperature=None: self.chat_with_gpt(
                    prompt, reset=True, system=system, temperature=temperature
                ),
                min_chars=config.VERIFY_MIN_CHARS,
                case_context=case_context,
                require_grounding=True,
                # 语料混英文后，「资料未涵盖」这类偷懒改写的词面判据会失效，
                # 借用检索器的多语言向量做语义判据（bm25 模式下自动返回 0）
                sim_fn=get_retriever().similarity,
                case_facts=case_facts or [],
                diseases=diseases,
            )
            return verifier.execute(
                text, evidence, max_rounds=config.VERIFY_MAX_ROUNDS,
                regenerate=regenerate,
            )
        except Exception as exc:  # noqa: BLE001 - 校验崩了也不许把未校验的稿子放出去
            print(f"[VERIFY] 校验链路异常，本次不输出报告：{exc}", file=sys.stderr)
            return None, {
                "status": "error", "reason": str(exc)[:200],
                # 记录异常类型，便于区分超时、解析失败与参数错误；
                # 不写入模型原始响应或服务商错误详情。
                "failure_kind": "exception",
                "failure_detail": type(exc).__name__,
            }
