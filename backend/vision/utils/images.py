"""图像输入统一为 RGB uint8；文件编码在算法之外处理。"""
from __future__ import annotations
from pathlib import Path
import cv2
import numpy as np
from vision.models import FundusImageDecodeError, FundusImageUnusable

def read_rgb(path: str | Path) -> np.ndarray:
    encoded = np.frombuffer(Path(path).read_bytes(), dtype=np.uint8)
    try:
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None
    except cv2.error as exc:
        raise FundusImageDecodeError("Cannot decode image") from exc
    if image is None:
        raise FundusImageDecodeError("Cannot decode image")
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


def check_fundus_input(image: np.ndarray) -> None:
    """Reject clear technical failures before requesting model inference."""
    validate_rgb(image)
    if min(image.shape[:2]) < 32:
        raise FundusImageUnusable("图像不可判读：图片尺寸过小，请重新拍摄或上传原始眼底照。")
    if not np.any(np.ptp(image, axis=(0, 1))):
        raise FundusImageUnusable("图像不可判读：图片没有可见细节，请重新拍摄眼底照。")
