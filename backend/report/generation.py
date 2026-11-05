from __future__ import annotations
from typing import Any, Callable
from pathlib import Path
from typing import Any, BinaryIO
from vision.models import EyeAnalysis
from llm.models import LLMConfiguration
from report.models import ReportResult, SpecialistReports
from agents.roles import get_role
import sys
from utils import config
from llm.client import LLMClient
from knowledge.service import get_retriever, retrieve_evidence
from .context import build_context
from .utils.messages import reject_message
from .pdf import PDFRenderer
from .utils.jobs import new_job_dir

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
        roles: list[str] | tuple[str, ...],
        job_dir: Path,
    ) -> ReportResult:
        reports, ratio, path, evidence = self.generate_reports(image, note, roles, job_dir)
        summary = self.generate_synthesis(reports, evidence)
        summary, verification = self.verify_synthesis(
            summary, evidence,
            lambda issues: self.generate_synthesis(reports, evidence, avoid=issues),
        )
        return ReportResult(summary, verification, ratio, path, evidence)

    def generate_reports(
        self,
        data_pth: str | Path | BinaryIO,
        note: str,
        roles: list[str] | tuple[str, ...] | None = None,
        job_dir: str | Path | None = None,
    ) -> SpecialistReports:
        """Generate diagnostic reports from multiple medical experts

        job_dir: 本次请求独占的临时目录。不传则自动新建（由调用方负责清理）。

        视觉分析直接调用 vision.analyze_fundus，消费统一的 EyeAnalysis。
        角色并发已委托给 ParallelOrchestrator（MULTI_AGENT_MODE=parallel 时等价于原有逻辑）。
        """
        from vision import analyze_fundus
        import imageio.v2 as imageio
        from agents import ParallelOrchestrator, SpecialistAgent

        if roles is None:
            roles = ["Ophthalmologist"]

        job_dir = Path(job_dir) if job_dir else new_job_dir("report")
        job_dir.mkdir(parents=True, exist_ok=True)

        # 直接消费病种结果，不再转换成另一套分析数据类。
        if hasattr(data_pth, "read"):
            image_path = job_dir / "input_image"
            image_path.write_bytes(data_pth.read())
        else:
            image_path = data_pth
        analysis: EyeAnalysis = analyze_fundus(image_path)
        glaucoma = analysis.diseases.get("glaucoma")
        ratio = glaucoma.measurements.get("area_equivalent_cdr") if glaucoma else None
        segmented_output_path = ""
        overlay = analysis.overlays.get("optic_disc_cup")
        if overlay is not None:
            segmented_output_path = str(job_dir / "segmented_image.png")
            imageio.imwrite(segmented_output_path, overlay)

        core_prompt = build_context(analysis, note)
        case_brief = core_prompt
        agents = [SpecialistAgent(role, self.chat_with_gpt, retrieve_evidence,
                  get_role(role).query_hint) for role in roles]
        role_evidence: dict[str, list[dict]] = {}
        for agent in agents:
            role_evidence[agent.name] = agent.gather_evidence(case_brief)

        # 全局编号
        evidence: list[dict] = []
        numbers: dict[str, int] = {}
        for role in roles:
            for item in role_evidence[role]:
                if item["id"] not in numbers:
                    numbers[item["id"]] = len(evidence) + 1
                    evidence.append({**item, "index": numbers[item["id"]]})
        evidence = evidence[: max(config.RAG_TOP_K * 2, 6)]

        if evidence:
            print(
                f"[RAG] 命中 {len(evidence)} 条证据：" +
                ", ".join(f"[{e['index']}]{e['id']}({e['score']})" for e in evidence)
            )

        # 只允许 Agent 引用最终保留在证据包中的条目。
        kept = {item["id"] for item in evidence}
        role_evidence = {role: [item for item in items if item["id"] in kept]
                         for role, items in role_evidence.items()}
        # ---- 角色并发（通过 ParallelOrchestrator）----
        # 目前只实现了 parallel 模式。其它模式若被打开却静默按 parallel 跑，
        # 会让人误以为协作模式已生效，所以这里显式拒绝。
        mode = config.MULTI_AGENT_MODE
        if mode != "parallel":
            raise NotImplementedError(
                f"MULTI_AGENT_MODE={mode} 尚未实现，当前仅支持 parallel。"
            )
        orchestrator = ParallelOrchestrator()
        expert_reports = orchestrator.run(agents, core_prompt, role_evidence, numbers)

        return SpecialistReports(expert_reports, ratio, segmented_output_path, evidence)


    def generate_synthesis(
        self,
        expert_reports: dict[str, str],
        evidence: list[dict[str, Any]] | None = None,
        avoid: list[dict[str, Any]] | None = None,
    ) -> str:
        from agents.director import DirectorAgent
        return DirectorAgent(self.chat_with_gpt).execute(expert_reports, evidence, avoid)

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
        if not config.VERIFY_ENABLED:
            from agents.tools.evidence import unknown_citation_issues
            issues = unknown_citation_issues(text, evidence)
            if issues:
                return None, {
                    "status": "rejected", "reason": "unknown_citations",
                    "remaining_issues": issues,
                }
            return text, {"status": "disabled"}
        if not text or text.startswith("Error:"):
            return None, {"status": "rejected", "reason": "empty_text"}

        try:
            from agents.verifier import CitationVerifier

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
