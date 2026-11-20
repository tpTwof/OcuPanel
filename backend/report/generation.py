from __future__ import annotations
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, BinaryIO, Callable

from agents import DirectorAgent, SpecialistAgent
from vision.models import EyeAnalysis
from vision.analysis import DEFAULT_DISEASES
from llm.models import LLMConfiguration
from report.models import ReportResult
from agents.roles import DISEASE_ROLES
from utils import config
from llm.client import LLMClient
from knowledge.service import get_retriever, retrieve_evidence
from .context import build_context
from .drafting import generate_verified_draft
from .pdf import PDFRenderer
from .utils.messages import reject_message
from agents.tools.text_revision import content_len
from agents.verifier import CitationVerifier

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
        from agents.prompts.language import LANGUAGE_INSTRUCTION
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
    ) -> ReportResult:
        import imageio.v2 as imageio
        from vision import analyze_fundus

        job_dir = Path(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)
        if hasattr(image, "read"):
            image_path = job_dir / "input_image"
            image_path.write_bytes(image.read())
        else:
            image_path = image
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
            retrieved = retrieve_evidence(context)
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
        summary, verification = generate_verified_draft(
            agents, DirectorAgent(self.chat_with_gpt), contexts,
            build_context(analysis.diseases, note), evidence_by_role, evidence,
            self.verify_synthesis,
        )
        if missing_evidence:
            verification["missing_evidence_diseases"] = missing_evidence
        return ReportResult(summary, verification, ratio, overlay_path, evidence, visual_findings)

    def verify_synthesis(
        self,
        text: str,
        evidence: list[dict[str, Any]],
        regenerate: Callable[[list[dict[str, Any]]], str] | None = None,
    ) -> tuple[str | None, dict[str, Any]]:
        """调用校验 Agent，必要时通过回调重新生成。

        返回 (文本, 校验报告)。**文本为 None 表示不交报告**（拒答或校验故障），
        调用方必须据此走拒答路径，不能把原文返回给用户。
        """
        if not content_len(text) or text.lstrip().startswith("Error:"):
            return None, {"status": "rejected", "reason": "empty_text"}
        if not config.VERIFY_ENABLED:
            from agents.tools.evidence import unknown_citation_issues
            issues = unknown_citation_issues(text, evidence)
            if issues:
                return None, {
                    "status": "rejected", "reason": "unknown_citations",
                    "remaining_issues": issues,
                }
            return text, {"status": "disabled"}
        try:
            verifier = CitationVerifier(
                lambda prompt, system=None, temperature=None: self.chat_with_gpt(
                    prompt, reset=True, system=system, temperature=temperature
                ),
                min_chars=config.VERIFY_MIN_CHARS,
                # 语料混英文后，「资料未涵盖」这类偷懒改写的词面判据会失效，
                # 借用检索器的多语言向量做语义判据（bm25 模式下自动返回 0）
                sim_fn=get_retriever().similarity,
            )
            return verifier.execute(
                text, evidence, max_rounds=config.VERIFY_MAX_ROUNDS,
                regenerate=regenerate,
            )
        except Exception as exc:  # noqa: BLE001 - 校验崩了也不许把未校验的稿子放出去
            print(f"[VERIFY] 校验链路异常，本次不输出报告：{exc}", file=sys.stderr)
            return None, {"status": "error", "reason": str(exc)[:200]}
