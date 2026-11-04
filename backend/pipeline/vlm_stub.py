"""VLMPipeline stub —— 眼科 VLM 后端占位。

待选定模型后，在此文件中实现真正的 VLM 推理逻辑。
当前返回空但合法的 FundusAnalysis，下游无需判空。
"""

from __future__ import annotations

import sys
from pathlib import Path

from .types import FundusAnalysis


class VLMPipeline:
    """眼科 VLM 分析管线（stub）。

    TODO: 选定模型后实现以下功能：
      - 加载 VLM 权重或连接 API
      - 对眼底图进行多病种检测
      - 生成自然语言描述
      - 填充 diseases_detected / lesion_descriptions / vlm_narrative
    """

    def analyze(self, image_path: str, job_dir: Path) -> FundusAnalysis:
        print(
            "[VLM] VLMPipeline 尚未接入模型，返回空结果。"
            "请在 pipeline/vlm_stub.py 中实现具体 VLM 推理逻辑。",
            file=sys.stderr,
        )
        return FundusAnalysis(
            glaucoma_prob=None,
            cup_to_disc_ratio=None,
            segmented_image_path=None,
            diseases_detected=[],
            lesion_descriptions=[],
            # 空串而非"[VLM 未接入]"这类哨兵：下游只用 `or "..."` 兜底，
            # 非空哨兵会被当成真实视觉描述塞进角色提示词，污染报告。
            vlm_narrative="",
            raw_model_outputs={"status": "stub"},
        )
