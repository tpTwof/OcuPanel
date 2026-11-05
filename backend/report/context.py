"""把分析事实和临床记录组织成请求内上下文，不复制分析数据结构。"""
from vision.models import EyeAnalysis

def build_context(analysis: EyeAnalysis, note: str) -> str:
    observations = []
    for disease, finding in analysis.diseases.items():
        observations.append(f"Analyzed disease: {disease}.")
        if finding.probability is not None:
            observations.append(f"Model probability: {finding.probability:.6f}.")
        observations.append(f"Severity: {finding.severity or 'not assessed'}.")
        for name, value in finding.measurements.items():
            observations.append(f"{name}: {value:.6f}.")
        observations.extend(f"Warning: {w}" for w in finding.warnings)
    clinical_note = note.strip() or "No clinical note provided."
    return " ".join(observations) + "\nClinician note: " + clinical_note
