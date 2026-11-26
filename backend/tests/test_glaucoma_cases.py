"""合成病例回放：固定分类、分割和语言模型输出，检查进入报告的结果。"""
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.report.generation import MedicalReportGenerator
from modules.vision.diseases.glaucoma import analyzer


class GlaucomaReportCases(unittest.TestCase):
    def replay(self, *, rim_pixels, cup_pixels, evidence, verifier_reply='{"claims": []}'):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            image = np.zeros((64, 64, 3), dtype=np.uint8)
            image[16:48, 16:48] = 100
            path = folder / "fixture.png"
            Image.fromarray(image).save(path)
            mask = np.zeros(image.shape[:2], dtype=np.uint8)
            mask.flat[:rim_pixels] = 1
            mask.flat[rim_pixels:rim_pixels + cup_pixels] = 2
            generator = MedicalReportGenerator(api_key="fixture")

            def reply(prompt, **kwargs):
                if not kwargs.get("system"):
                    return "Synthetic report [1]."
                if verifier_reply != '{"claims": []}':
                    return verifier_reply
                return json.dumps({'claims': [], 'grounding': [{
                    'quote': 'Synthetic report [1].', 'basis': 'medical_knowledge', 'citations': [1],
                    'sources': [{'kind': 'evidence', 'index': 1, 'quote': evidence[0]['text']}],
                }]})

            generator.chat_with_gpt = Mock(side_effect=reply)
            with patch.object(analyzer, "predict_probability", return_value=0.9), \
                 patch.object(analyzer, "predict_mask", return_value=mask), \
                 patch("modules.report.generation.retrieve_evidence", return_value=evidence), \
                 patch("modules.report.generation.get_retriever", return_value=Mock(similarity=lambda a, b: 0)), \
                 patch("core.config.VERIFY_ENABLED", True):
                result = generator.generate(path, "Synthetic case. Stage unknown.", folder)

            self.assertTrue(Path(result.image_path).is_file())
            finding = result.visual_findings["glaucoma"]
            self.assertIsNone(finding["severity"])
            self.assertEqual(finding["model_sources"]["segmenter"], analyzer.SEGMENTER)
            return result, generator.chat_with_gpt.call_count

    def test_measurable_disc_preserves_ratio_and_evidence(self):
        result, _ = self.replay(rim_pixels=75, cup_pixels=25,
                                evidence=[{"id": "fixture-guide", "text": "Synthetic reference."}])
        self.assertEqual(result.cup_to_disc_ratio, 0.5)
        self.assertEqual(result.verification["status"], "pass")
        self.assertEqual(result.summary, "Synthetic report [1].")
        self.assertEqual([(item["id"], item["index"]) for item in result.evidence], [("fixture-guide", 1)])

    def test_missing_rim_keeps_warning_and_withholds_ratio(self):
        result, _ = self.replay(rim_pixels=0, cup_pixels=25,
                                evidence=[{"id": "fixture-guide", "text": "Synthetic reference."}])
        self.assertIsNone(result.cup_to_disc_ratio)
        self.assertIn("No optic disc rim detected; CDR is unavailable.",
                      result.visual_findings["glaucoma"]["warnings"])

    def test_missing_evidence_keeps_measurement_and_skips_drafting(self):
        result, calls = self.replay(rim_pixels=75, cup_pixels=25, evidence=[])
        self.assertEqual(result.cup_to_disc_ratio, 0.5)
        self.assertIsNone(result.summary)
        self.assertEqual(result.verification["reason"], "no_evidence")
        self.assertEqual(calls, 0)

    def test_invalid_verifier_reply_withholds_draft(self):
        result, _ = self.replay(rim_pixels=75, cup_pixels=25, verifier_reply="{}",
                                evidence=[{"id": "fixture-guide", "text": "Synthetic reference."}])
        self.assertIsNone(result.summary)
        self.assertEqual(result.verification["status"], "error")
