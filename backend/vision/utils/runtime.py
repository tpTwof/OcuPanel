"""模型生命周期：按模型和设备缓存，锁住加载和推理。"""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from transformers import BaseImageProcessor, PreTrainedModel
from functools import lru_cache
from threading import RLock
import torch
from transformers import AutoImageProcessor

MODEL_LOCK = RLock()

def resolve_device(device: str | torch.device | None = None) -> str:
    if device is not None:
        return str(torch.device(device))
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"

@lru_cache(maxsize=4)
def load_model(
    model_name: str,
    model_class: type[PreTrainedModel],
    device: str | torch.device | None,
) -> tuple[BaseImageProcessor, PreTrainedModel]:
    processor = AutoImageProcessor.from_pretrained(model_name, use_fast=False)
    model = model_class.from_pretrained(model_name).to(device)
    model.eval()
    return processor, model

def clear_model_cache() -> None:
    with MODEL_LOCK:
        load_model.cache_clear()
