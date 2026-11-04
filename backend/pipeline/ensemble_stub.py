"""EnsemblePipeline stub —— Legacy + VLM 融合占位。

依赖 VLMPipeline，待 VLM 接入后实现融合逻辑。
当前退化为纯 LegacyPipeline 结果。
"""

from __future__ import annotations

import sys
from pathlib import Path

from .types import FundusAnalysis
from .legacy import LegacyPipeline


class EnsemblePipeline:
    """Legacy + VLM 融合管线（stub）。

    TODO: VLM 接入后实现以下融合策略：
      - 同时运行 LegacyPipeline 和 VLMPipeline
      - 合并 diseases_detected（冲突时标记来源）
      - 合并 lesion_descriptions
      - 拼接 vlm_narrative
    """

    def __init__(self):
        self._legacy = LegacyPipeline()

    def analyze(self, image_path: str, job_dir: Path) -> FundusAnalysis:
        print(
            "[ENSEMBLE] VLMPipeline 尚未接入，EnsemblePipeline 退化为 LegacyPipeline。",
            file=sys.stderr,
        )
        result = self._legacy.analyze(image_path, job_dir)
        result.raw_model_outputs["ensemble_mode"] = "legacy_only"
        return result
