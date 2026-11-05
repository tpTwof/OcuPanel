"""组合青光眼分类和解剖结构测量，保留可独立使用的部分结果。"""
import numpy as np
from .classifier import predict_probability, MODEL_NAME as CLASSIFIER
from ...anatomy.optic_disc_cup import (
    predict_mask,
    overlay,
    cup_to_disc_ratio,
    MODEL_NAME as SEGMENTER,
)
from vision.models import EyeAnalysis, DiseaseResult

def analyze(image, device=None):
    probability = predict_probability(image, device)
    mask = predict_mask(image, device)
    result = DiseaseResult(probability=probability,
        model_sources={"classifier": CLASSIFIER, "segmenter": SEGMENTER})
    if not np.any(mask == 1):
        result.warnings.append("No optic disc rim detected; CDR is unavailable.")
    else:
        result.measurements["area_equivalent_cdr"] = cup_to_disc_ratio(mask)
        if not np.any(mask == 2):
            result.warnings.append("No optic cup detected; estimated CDR is zero.")
    return EyeAnalysis(diseases={"glaucoma": result},
        masks={"optic_disc_cup": mask}, overlays={"optic_disc_cup": overlay(image, mask)})
