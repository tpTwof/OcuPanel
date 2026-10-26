# 把青光眼概率映射成自然语言描述
from pathlib import Path

import torch
from classifier.swinv2_classifier import predict_glaucoma

class GlaucomaProb2Text:
    def __init__(self, prob: float):
        self.prob = prob
        self.levelprompt = {
            "0": "no indication of glaucoma.",
            "1": "a small possibility of glaucoma.",
            "2": "a strong likelihood of glaucoma.",
            "3": "definitive signs of glaucoma detected.",
        }
        self.grade = self.grading()

    def grading(self):
        """
        Classifies the probability into different levels of glaucoma likelihood.
        """
        if self.prob < 0.2:
            return "0"  # No sign
        elif self.prob < 0.5:
            return "1"  # Small possibility
        elif self.prob < 0.9:
            return "2"  # Likely
        else:
            return "3"  # Definitive

    def promptA(self):
        """Outputs the direct probability score."""
        return f"Glaucoma classification confidence: {self.prob:.3f}."

    def promptB(self):
        """Outputs a descriptive text based on probability classification."""
        return "Network A suggests " + self.levelprompt[self.grade]

    def promptC(self):
        """Outputs a diagnostic statement based on probability threshold."""
        if self.prob >= 0.5:
            return "Network A suggests a likely presence of glaucoma."
        else:
            return "Network A does not find strong evidence of glaucoma."

if __name__ == "__main__":
    # Example usage
    image_path = str(Path(__file__).resolve().parents[2] / "samples" / "fundus_right_eye.png")
    
    # Get probability from model
    prob = predict_glaucoma(image_path)
    
    # Generate text output
    glaucoma_text = GlaucomaProb2Text(prob)

    print("\nPrompt A:", glaucoma_text.promptA())
    print("Prompt B:", glaucoma_text.promptB())
    print("Prompt C:", glaucoma_text.promptC())
