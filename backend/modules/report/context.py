"""把分析事实和临床记录组织成请求内上下文，不复制分析数据结构。"""
from typing import Any
from modules.vision.models import DiseaseResult
from core.config import REPORT_LANGUAGE

DISEASE_LABELS = {
    "glaucoma": ("青光眼", "Glaucoma"),
    "diabetic_retinopathy": ("糖尿病视网膜病变（DR）", "Diabetic retinopathy (DR)"),
    "age_related_macular_degeneration": ("年龄相关性黄斑变性（AMD）", "Age-related macular degeneration (AMD)"),
}

def build_context(findings: dict[str, DiseaseResult], note: str) -> str:
    observations = []
    has_retinal_scores = False
    for disease, finding in findings.items():
        name = DISEASE_LABELS.get(disease, (disease, disease))[1]
        observations.append(f"Analyzed disease: {name}.")
        if finding.probability is not None:
            observations.append(f"Model probability: {finding.probability:.6f}.")
        if finding.prompt_similarity_margin is not None:
            has_retinal_scores = True
            observations.append(f"FLAIR prompt similarity margin: {finding.prompt_similarity_margin:+.6f}.")
        observations.append(f"Severity: {finding.severity or 'not assessed'}.")
        for name, value in finding.measurements.items():
            observations.append(f"{name}: {value:.6f}.")
        observations.extend(f"Warning: {w}" for w in finding.warnings)
    if has_retinal_scores:
        observations.append(
            "Each FLAIR result compares two text prompts on the fundus photo. The raw model scores "
            "are reported separately. They supply no diagnosis, disease exclusion, clinical threshold, "
            "stage, lesion localization or image quality assessment. Base clinical discussion on the "
            "note and cited evidence."
        )
    clinical_note = note.strip() or "No clinical note provided."
    return " ".join(observations) + "\nClinician note: " + clinical_note


def format_visual_findings(
    findings: dict[str, dict[str, Any]] | None,
    missing_evidence: list[str] | None = None,
) -> str:
    if not findings:
        return ""
    chinese = REPORT_LANGUAGE.startswith("zh")
    language = 0 if chinese else 1
    lines = ["## 影像模型结果" if chinese else "## Imaging model results", ""]
    has_retinal_scores = False
    warnings_zh = {
        "No optic disc rim detected; CDR is unavailable.": "未检测到视盘盘沿，无法计算杯盘比。",
        "No optic cup detected; estimated CDR is zero.": "未检测到视杯，估算杯盘比为零。",
    }
    for disease, finding in findings.items():
        label = DISEASE_LABELS.get(disease, (disease, disease))[language]
        lines.extend((f"### {label}", ""))
        probability = finding.get("probability")
        if probability is not None:
            label = "分类模型输出概率" if chinese else "Classifier output probability"
            lines.append(f"- {label} · {probability:.1%}")
        for metric, value in finding.get("measurements", {}).items():
            label = metric
            if metric == "area_equivalent_cdr":
                label = "面积等效杯盘比" if chinese else "Area-equivalent cup-to-disc ratio"
            lines.append(f"- {label} · {value:.2f}")
        margin = finding.get("prompt_similarity_margin")
        if margin is not None:
            has_retinal_scores = True
            label = "FLAIR 匹配差值（研究用途）" if chinese else "FLAIR matching margin (research use)"
            lines.append(f"- {label} · {margin:+.3f}")
        if sources := finding.get("model_sources"):
            label = "模型来源" if chinese else "Model sources"
            lines.append(f"- {label} · " + " · ".join(sources.values()))
        for warning in finding.get("warnings", []):
            lines.append(f"- {warnings_zh.get(warning, warning) if chinese else warning}")
        if disease in (missing_evidence or []):
            lines.append("- 本病种未检索到参考资料。" if chinese else "- No references retrieved for this disease.")
        lines.append("")
    if has_retinal_scores:
        lines.extend((
            "FLAIR 差值以模型分数为单位。正值偏向病变提示，负值偏向无病变提示。"
            "分数未经临床校准，无法用于确诊、排除疾病或分期。" if chinese else
            "FLAIR margins are in model score units. Positive values favor the disease prompt and "
            "negative values favor the reference prompt. These uncalibrated scores cannot diagnose, "
            "rule out or stage disease.",
            "",
        ))
    lines.append(
        "以上指标直接来自视觉分析。引用校验适用于报告正文中的外部知识陈述。" if chinese else
        "These results come from imaging models. Citation verification applies to external knowledge claims in the report text."
    )
    return "\n".join(lines)
