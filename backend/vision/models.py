"""独立于报告和前端的分析结果；数组保留在内存中。"""
from dataclasses import dataclass, field
from typing import Any

@dataclass
class DiseaseResult:
    """病种由 EyeAnalysis.diseases 的键标识，概率与分级独立。"""
    probability: float | None = None
    severity: str | None = None
    measurements: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    model_sources: dict[str, str] = field(default_factory=dict)

@dataclass
class EyeAnalysis:
    diseases: dict[str, DiseaseResult] = field(default_factory=dict)
    masks: dict[str, Any] = field(default_factory=dict)
    overlays: dict[str, Any] = field(default_factory=dict)
