"""眼底分析入口。新增病种时明确注册实现，不返回未实现的空结果。"""
from pathlib import Path
from vision.models import EyeAnalysis

def analyze_fundus(
    image_path: str | Path,
    *,
    diseases: str | tuple[str, ...] | list[str] = ('glaucoma',),
    device: str | None = None,
) -> EyeAnalysis:
    from .utils.images import read_rgb
    selected = (diseases,) if isinstance(diseases, str) else tuple(diseases)
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("Select at least one disease, without duplicates")
    unsupported = set(selected) - {"glaucoma"}
    if unsupported:
        raise ValueError(f"Unsupported diseases: {sorted(unsupported)}")
    image = read_rgb(image_path)
    result = EyeAnalysis()
    for disease in selected:
        from .diseases.glaucoma.analyzer import analyze
        current = analyze(image, device)
        result.diseases.update(current.diseases)
        result.masks.update(current.masks)
        result.overlays.update(current.overlays)
    return result
