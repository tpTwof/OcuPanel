"""眼底分析入口。新增病种时明确注册实现，不返回未实现的空结果。"""
from pathlib import Path

from vision.models import EyeAnalysis

from .diseases.retinal import RETINAL_PROMPTS

DEFAULT_DISEASES = ("glaucoma",)
SUPPORTED_DISEASES = (*DEFAULT_DISEASES, *RETINAL_PROMPTS)


def validate_diseases(diseases: str | tuple[str, ...] | list[str]) -> tuple[str, ...]:
    selected = (diseases,) if isinstance(diseases, str) else tuple(diseases)
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("Select at least one disease, without duplicates")
    unsupported = set(selected) - set(SUPPORTED_DISEASES)
    if unsupported:
        raise ValueError(f"Unsupported diseases: {sorted(unsupported)}")
    return selected


def analyze_fundus(
    image_path: str | Path,
    *,
    diseases: str | tuple[str, ...] | list[str] = DEFAULT_DISEASES,
    device: str | None = None,
) -> EyeAnalysis:
    from .utils.images import check_fundus_input, read_rgb
    selected = validate_diseases(diseases)
    image = read_rgb(image_path)
    check_fundus_input(image)
    result = EyeAnalysis()
    if "glaucoma" in selected:
        from .diseases.glaucoma.analyzer import analyze
        result = analyze(image, device)
    retinal = tuple(disease for disease in selected if disease in RETINAL_PROMPTS)
    if retinal:
        from .diseases.retinal import analyze_retinal
        result.diseases.update(analyze_retinal(image, retinal, device))
    result.diseases = {disease: result.diseases[disease] for disease in selected}
    return result
