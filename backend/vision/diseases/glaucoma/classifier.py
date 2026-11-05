"""SwinV2 青光眼概率；该权重约定索引 1 为青光眼。"""
from __future__ import annotations
import numpy as np
import torch
from transformers import Swinv2ForImageClassification
from ...utils.images import validate_rgb
from ...utils.runtime import MODEL_LOCK, resolve_device, load_model

MODEL_NAME = "pamixsun/swinv2_tiny_for_glaucoma_classification"

def predict_probability(
    image: np.ndarray,
    device: str | torch.device | None = None,
) -> float:
    validate_rgb(image)
    device = resolve_device(device)
    with MODEL_LOCK:
        processor, model = load_model(MODEL_NAME, Swinv2ForImageClassification, device)
        inputs = {k: v.to(device) for k, v in processor(image, return_tensors="pt").items()}
        with torch.inference_mode():
            logits = model(**inputs).logits
            if logits.shape != (1, 2) or not torch.isfinite(logits).all():
                raise ValueError("Expected finite binary glaucoma logits")
            return float(logits.softmax(dim=-1)[0, 1].item())
