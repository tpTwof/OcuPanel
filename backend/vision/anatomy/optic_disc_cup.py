"""视杯视盘分割与面积指标，可供多个病种分析复用。"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import torch
from torch import nn
from transformers import SegformerForSemanticSegmentation
from ..utils.runtime import MODEL_LOCK, resolve_device, load_model
from ..utils.images import validate_rgb

MODEL_NAME = "pamixsun/segformer_for_optic_disc_cup_segmentation"
# 当前权重标签约定：0 背景，1 视盘环，2 视杯。
def predict_mask(
    image: np.ndarray,
    device: str | torch.device | None = None,
) -> np.ndarray:
    validate_rgb(image)
    device = resolve_device(device)
    with MODEL_LOCK:
        processor, model = load_model(MODEL_NAME, SegformerForSemanticSegmentation, device)
        inputs = {k: v.to(device) for k, v in processor(image, return_tensors="pt").items()}
        with torch.inference_mode():
            logits = model(**inputs).logits
            if logits.shape[1] != 3:
                raise ValueError("Expected three optic disc/cup classes")
            logits = nn.functional.interpolate(logits, size=image.shape[:2], mode="bilinear", align_corners=False)
            return logits.argmax(dim=1)[0].cpu().numpy().astype(np.uint8)

def overlay(image: np.ndarray, mask: np.ndarray, alpha: float = 0.5) -> np.ndarray:
    if not 0 <= alpha <= 1:
        raise ValueError("alpha must be between 0 and 1")
    result = image.copy()
    for label, color in ((1, (255, 0, 100)), (2, (0, 255, 0))):
        selected = mask == label
        result[selected] = np.rint(
            image[selected].astype(np.float32) * (1 - alpha)
            + np.asarray(color, dtype=np.float32) * alpha
        ).astype(np.uint8)
    return result


def cup_to_disc_ratio(mask: np.ndarray) -> float:
    """面积等效直径比，不是直接测量的垂直 CDR。视盘包含视杯。"""
    cup = np.count_nonzero(mask == 2)
    total_disc = np.count_nonzero((mask == 1) | (mask == 2))
    if total_disc == 0:
        raise ValueError("No optic disc detected in image.")
    return float(np.sqrt(cup / total_disc))



def analyze_optic_disc_cup(
    image_path: str | Path,
    *,
    device: str | torch.device | None = None,
    alpha: float = 0.5,
) -> tuple[np.ndarray, float]:
    """独立分割入口：一次推理返回 RGB 叠加图和面积等效 CDR。"""
    from ..utils.images import read_rgb
    if not 0 <= alpha <= 1:
        raise ValueError("alpha must be between 0 and 1")
    image = read_rgb(image_path)
    mask = predict_mask(image, device)
    return overlay(image, mask, alpha), cup_to_disc_ratio(mask)
