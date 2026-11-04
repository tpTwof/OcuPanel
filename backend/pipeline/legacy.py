"""LegacyPipeline —— 封装现有 SwinV2 + SegFormer，保持系统可运行。

这是唯一在套壳阶段产出真实结果的 Pipeline。
"""

from __future__ import annotations

import sys
from pathlib import Path

import imageio.v2 as imageio

from .types import DiseaseFinding, FundusAnalysis


class LegacyPipeline:
    """将现有青光眼分类器 + 分割器包装为 AnalysisPipeline。"""

    def analyze(self, image_path: str, job_dir: Path) -> FundusAnalysis:
        from classifier import GlaucomaProb2Text, predict_glaucoma
        from segmenter import calculate_cup_to_disc_ratio, segment_optic_disc_cup

        # 读取并转换图片（与 report_generator.generate_reports 原有逻辑一致）
        slo_fundus_image = imageio.imread(image_path)
        temp_jpg_path = str(job_dir / "fundus.png")
        imageio.imwrite(temp_jpg_path, slo_fundus_image)

        # 分割视杯/视盘
        segmented_image = segment_optic_disc_cup(temp_jpg_path)
        ratio = calculate_cup_to_disc_ratio(temp_jpg_path)

        segmented_output_path = str(job_dir / "segmented_image.png")
        imageio.imwrite(segmented_output_path, segmented_image)

        # 青光眼概率
        disease_prob = predict_glaucoma(temp_jpg_path)
        disease_class = GlaucomaProb2Text(disease_prob)

        # Sanity check：确保封装后的值与原函数一致
        assert isinstance(disease_prob, float), "predict_glaucoma must return float"
        assert isinstance(ratio, float), "calculate_cup_to_disc_ratio must return float"

        # 清理临时文件
        try:
            import os
            os.remove(temp_jpg_path)
        except OSError:
            pass

        return FundusAnalysis(
            glaucoma_prob=disease_prob,
            cup_to_disc_ratio=ratio,
            segmented_image_path=segmented_output_path,
            diseases_detected=[
                DiseaseFinding(
                    disease="glaucoma",
                    severity=_prob_to_severity(disease_prob),
                    confidence=disease_prob,
                    source="swinv2",
                )
            ],
            vlm_narrative=disease_class.promptB(),
            raw_model_outputs={
                "swinv2_prob": disease_prob,
                "segformer_cdr": ratio,
                "prompt_b": disease_class.promptB(),
            },
        )


def _prob_to_severity(prob: float) -> str:
    """将青光眼概率映射为严重度标签，与 GlaucomaProb2Text.grading() 对齐。"""
    if prob < 0.2:
        return "none"
    elif prob < 0.5:
        return "possible"
    elif prob < 0.9:
        return "likely"
    else:
        return "definitive"
