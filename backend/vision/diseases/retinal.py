"""FLAIR zero-shot comparison of disease-specific text prompts on color fundus photos."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from vision.models import DiseaseResult

if TYPE_CHECKING:
    import numpy as np
    from flair import FLAIRModel

MODEL_NAME = "jusiro2/FLAIR"
MODEL_REVISION = "5f6bdd0a068353dc41a896ba3abdd7c0f6d35938"
RETINAL_PROMPTS = {
    "diabetic_retinopathy": ("no diabetic retinopathy", "diabetic retinopathy"),
    "age_related_macular_degeneration": (
        "no age related macular degeneration", "age related macular degeneration",
    ),
}


class RetinalModelUnavailable(RuntimeError):
    """The optional model or its weights could not be loaded."""


@lru_cache(maxsize=1)
def _load_model(device: str) -> FLAIRModel:
    from flair import FLAIRModel
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file

    config_path = hf_hub_download(MODEL_NAME, "config.json", revision=MODEL_REVISION)
    checkpoint_path = hf_hub_download(MODEL_NAME, "model.safetensors", revision=MODEL_REVISION)
    model_config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    model_config["vision_pretrained"] = False
    model = FLAIRModel(**model_config)
    state = load_file(checkpoint_path)
    # Transformers now regenerates this buffer and omits it from the state dict.
    state.pop("text_model.model.embeddings.position_ids", None)
    model.load_state_dict(state, strict=True)
    return model.to(device).eval()


def analyze_retinal(
    image: np.ndarray, diseases: tuple[str, ...], device: str | None,
) -> dict[str, DiseaseResult]:
    import torch
    from ..utils.images import validate_rgb
    from ..utils.runtime import MODEL_LOCK, resolve_device

    validate_rgb(image)
    device = resolve_device(device)
    results = {}
    with MODEL_LOCK, torch.inference_mode():
        try:
            from flair.modeling import model as flair_runtime
        except (ImportError, OSError, RuntimeError) as exc:
            raise RetinalModelUnavailable("Cannot import the optional FLAIR runtime") from exc

        # The pinned upstream model uses a module-level device for both input encoders.
        previous_device = flair_runtime.device
        flair_runtime.device = device
        try:
            try:
                model = _load_model(device)
            except (OSError, RuntimeError, ValueError) as exc:
                raise RetinalModelUnavailable("Cannot load the FLAIR checkpoint") from exc
            image_embedding = model.vision_model(model.preprocess_image(image))
            for disease in diseases:
                # FLAIR averages token positions, including padding. Tokenize each pair
                # separately so another selected disease cannot change its score.
                tokens = model.preprocess_text(RETINAL_PROMPTS[disease])
                text_embeddings = model.text_model(*tokens)
                logits = model.compute_logits(image_embedding, text_embeddings)
                if logits.shape != (1, 2) or not torch.isfinite(logits).all():
                    raise ValueError("Expected two finite FLAIR similarities per disease")
                results[disease] = DiseaseResult(
                    prompt_similarity_margin=logits[0, 1].item() - logits[0, 0].item(),
                    model_sources={"image_text_model": f"{MODEL_NAME}@{MODEL_REVISION}"},
                )
        finally:
            flair_runtime.device = previous_device
    return results
