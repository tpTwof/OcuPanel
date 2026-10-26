# SwinV2 青光眼分类器
from pathlib import Path

import cv2
import torch
from transformers import AutoImageProcessor, Swinv2ForImageClassification

def predict_glaucoma(image_path: str):
    """
    Processes the image, runs the glaucoma classification model,
    and returns the probability of glaucoma.
    """
    # Load and preprocess image
    image = cv2.imread(image_path)
    
    if image is None:
        raise FileNotFoundError(f"Image file not found: {image_path}")

    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    # Load model and processor
    processor = AutoImageProcessor.from_pretrained("pamixsun/swinv2_tiny_for_glaucoma_classification")
    model = Swinv2ForImageClassification.from_pretrained("pamixsun/swinv2_tiny_for_glaucoma_classification")

    # Prepare image for model input
    inputs = processor(image, return_tensors="pt")

    # Run inference
    with torch.no_grad():
        logits = model(**inputs).logits

    # Compute softmax probabilities
    probs = torch.nn.functional.softmax(logits, dim=-1)

    confidence_score = probs[0, 1].item()

    return confidence_score  # Return the probability score

# Example usage:
if __name__ == "__main__":
    image_path = str(Path(__file__).resolve().parents[2] / "samples" / "fundus_right_eye.png")
    prob = predict_glaucoma(image_path)
    print(f"Glaucoma Probability: {prob:.4f}")
