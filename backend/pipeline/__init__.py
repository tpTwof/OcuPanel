"""视觉分析管线（AnalysisPipeline）—— 统一所有视觉模型的输出契约。

三种实现：
- LegacyPipeline  封装现有 SwinV2 + SegFormer，完整可用
- VLMPipeline     眼科 VLM 后端（stub，待选定模型后填入）
- EnsemblePipeline Legacy + VLM 融合（stub，依赖 VLMPipeline）

选择哪个由 config.ANALYSIS_PIPELINE 控制（legacy / vlm / ensemble）。
"""

from .types import FundusAnalysis, DiseaseFinding, LesionDescription
from .protocol import AnalysisPipeline
from .legacy import LegacyPipeline
from .vlm_stub import VLMPipeline
from .ensemble_stub import EnsemblePipeline

__all__ = [
    "FundusAnalysis",
    "DiseaseFinding",
    "LesionDescription",
    "AnalysisPipeline",
    "LegacyPipeline",
    "VLMPipeline",
    "EnsemblePipeline",
]


def get_pipeline() -> AnalysisPipeline:
    """根据配置返回对应的 Pipeline 实例。"""
    import config

    mode = (config.ANALYSIS_PIPELINE or "legacy").lower()
    if mode == "vlm":
        return VLMPipeline()
    if mode == "ensemble":
        return EnsemblePipeline()
    return LegacyPipeline()
