"""视觉分析结果的数据类 —— 所有下游消费者只看这些结构。

每个数据类都有 `extra: dict` 兜底字段，用于未来模型返回的非预期输出
（如 attention map、OCT 指标等），避免频繁改签名。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DiseaseFinding:
    """单个疾病检测结果。"""

    disease: str  # "diabetic_retinopathy", "glaucoma", "amd", ...
    severity: str  # "mild_npdr", "moderate_npdr", "severe_npdr", "pdr", ...
    confidence: float
    source: str  # "vlm", "swinv2", "ensemble"
    extra: dict = field(default_factory=dict)


@dataclass
class LesionDescription:
    """单个病灶描述。"""

    type: str  # "microaneurysm", "hard_exudate", "hemorrhage", ...
    location: str  # "macula", "periphery", "optic_disc", ...
    description: str  # 自然语言描述
    confidence: float | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class FundusAnalysis:
    """统一的视觉分析结果。

    向后兼容字段（LegacyPipeline 填充）：
      glaucoma_prob, cup_to_disc_ratio, segmented_image_path

    新增多病种字段（VLMPipeline / EnsemblePipeline 填充）：
      diseases_detected, lesion_descriptions, vlm_narrative

    raw_model_outputs: 各模型原始输出留痕，供调试和审计。
    extra: 未来扩展字段的兜底容器。
    """

    # 向后兼容
    glaucoma_prob: float | None = None
    cup_to_disc_ratio: float | None = None
    segmented_image_path: str | None = None

    # 多病种
    diseases_detected: list[DiseaseFinding] = field(default_factory=list)
    lesion_descriptions: list[LesionDescription] = field(default_factory=list)
    vlm_narrative: str = ""

    # 留痕 & 扩展
    raw_model_outputs: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)
