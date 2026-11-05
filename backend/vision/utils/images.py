"""图像输入统一为 RGB uint8；文件编码在算法之外处理。"""
from __future__ import annotations
from pathlib import Path
import cv2
import numpy as np

def read_rgb(path: str | Path) -> np.ndarray:
    encoded = np.frombuffer(Path(path).read_bytes(), dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None
    if image is None:
        raise ValueError(f"Cannot decode image: {path}")
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

def validate_rgb(image: np.ndarray) -> None:
    if (
        not isinstance(image, np.ndarray)
        or image.dtype != np.uint8
        or image.ndim != 3
        or image.shape[2] != 3
        or not image.size
    ):
        raise ValueError("Expected nonempty RGB uint8 image with shape (H, W, 3)")
