import cv2
import torch
import numpy as np
import matplotlib.pyplot as plt

from torch import nn
from transformers import AutoImageProcessor, SegformerForSemanticSegmentation

def segment_optic_disc_cup(image_path: str):
    """
    Loads a fundus image, applies segmentation using the SegFormer model, 
    and returns the image overlaid with the optic disc & cup segmentation mask.
    
    Args:
        image_path (str): Path to the fundus image.
    
    Returns:
        np.ndarray: The original image with the segmentation mask applied.
    """
    
    # Load and preprocess the image
    image = cv2.imread(image_path)
    if image is None:
        raise FileNotFoundError(f"Image file not found: {image_path}")

    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)  # Convert to RGB

    # Load the processor and model
    processor = AutoImageProcessor.from_pretrained("pamixsun/segformer_for_optic_disc_cup_segmentation")
    model = SegformerForSemanticSegmentation.from_pretrained("pamixsun/segformer_for_optic_disc_cup_segmentation")

    # Prepare inputs
    inputs = processor(image, return_tensors="pt")

    # Run inference
    with torch.no_grad():
        outputs = model(**inputs)
        logits = outputs.logits.cpu()

    # Upsample the logits to match the original image size
    upsampled_logits = nn.functional.interpolate(
        logits,
        size=image.shape[:2],
        mode="bilinear",
        align_corners=False,
    )

    # Convert logits to a segmentation mask
    pred_disc_cup = upsampled_logits.argmax(dim=1)[0].numpy().astype(np.uint8)

    # Create a more opaque segmentation mask
    mask_colormap = np.zeros_like(image)

    # Assign colors with higher intensity
    mask_colormap[:, :, 0] = (pred_disc_cup == 1) * 255  # Red for optic disc
    mask_colormap[:, :, 1] = (pred_disc_cup == 2) * 255  # Green for optic cup
    mask_colormap[:, :, 2] = (pred_disc_cup == 1) * 100  # Blue component to make the red more visible

    # Increase the mask opacity (higher alpha for the mask)
    overlaid_image = cv2.addWeighted(image, 0.5, mask_colormap, 0.5, 0)

    return overlaid_image  # Returns the processed image with segmentation overlay

def calculate_cup_to_disc_ratio(image_path: str) -> float:
    """
    Loads a fundus image, applies segmentation, and computes the cup-to-disc pixel ratio.

    Args:
        image_path (str): Path to the fundus image.

    Returns:
        float: Ratio of optic cup pixels to optic disc pixels.
    """
    
    # Load and preprocess the image
    image = cv2.imread(image_path)
    if image is None:
        raise FileNotFoundError(f"Image file not found: {image_path}")

    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    # Load processor and model
    processor = AutoImageProcessor.from_pretrained("pamixsun/segformer_for_optic_disc_cup_segmentation")
    model = SegformerForSemanticSegmentation.from_pretrained("pamixsun/segformer_for_optic_disc_cup_segmentation")

    # Process input
    inputs = processor(image, return_tensors="pt")

    # Model inference
    with torch.no_grad():
        outputs = model(**inputs)
        logits = outputs.logits.cpu()

    # Resize prediction to match image size
    upsampled_logits = nn.functional.interpolate(
        logits,
        size=image.shape[:2],
        mode="bilinear",
        align_corners=False,
    )

    # Get the segmentation mask
    pred_mask = upsampled_logits.argmax(dim=1)[0].numpy()

    # Count pixels
    cup_pixels = np.sum(pred_mask == 2)
    disc_pixels = np.sum(pred_mask == 1)

    if disc_pixels == 0:
        raise ValueError("No optic disc detected in image.")

    ratio = cup_pixels / disc_pixels
    return ratio * 100  # Return as percentage

# === Example Usage ===
if __name__ == "__main__":
    image_path = "/Users/philipliu/Downloads/research/llm_research/spring_2025/FairCLIP/data/slo_fundus_00004.jpg"

    ratio = calculate_cup_to_disc_ratio(image_path)
    print(f"Cup-to-Disc Ratio: {ratio:.4f}")

    """
    save_path = "./segmented_fundus_image.png"

    # Get the image with the segmentation overlay
    segmented_image = segment_optic_disc_cup(image_path)

    plt.imsave(save_path, segmented_image)
    print(f"Segmented image saved at: {save_path}")

    # Display the result
    plt.figure(figsize=(6, 6))
    plt.imshow(segmented_image)
    plt.title("Optic Disc & Cup Segmentation Overlay")
    plt.axis("off")
    plt.show()"
    """
