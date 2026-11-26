import sys
from pathlib import Path
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call, patch
import numpy as np
import torch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.vision import analyze_fundus, EyeAnalysis, DiseaseResult
from modules.vision.diseases import retinal

class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.images = ModuleType('modules.vision.utils.images')
        self.image = object()
        self.images.read_rgb = Mock(return_value=self.image)
        self.images.check_fundus_input = Mock()
        self.worker = ModuleType('modules.vision.diseases.glaucoma.analyzer')
        self.result = EyeAnalysis(diseases={'glaucoma': DiseaseResult(probability=0.7)})
        self.worker.analyze = Mock(return_value=self.result)
        self.modules = patch.dict(sys.modules, {'modules.vision.utils.images': self.images, 'modules.vision.diseases.glaucoma.analyzer': self.worker})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def test_read_once_and_keep_unknown_severity(self):
        result = analyze_fundus('example.png', device='cpu')
        self.images.read_rgb.assert_called_once_with('example.png')
        self.worker.analyze.assert_called_once_with(self.image, 'cpu')
        self.assertEqual(result.diseases['glaucoma'].probability, 0.7)
        self.assertIsNone(result.diseases['glaucoma'].severity)

    def test_invalid_selection_fails_before_reading(self):
        for diseases in [(), ('glaucoma', 'glaucoma'), ('unsupported_disease',)]:
            with self.subTest(diseases=diseases), self.assertRaises(ValueError):
                analyze_fundus('missing.png', diseases=diseases)
        self.images.read_rgb.assert_not_called()

    def test_unusable_image_skips_all_models(self):
        from modules.vision.models import FundusImageUnusable

        self.images.check_fundus_input.side_effect = FundusImageUnusable("不可判读")
        with patch('modules.vision.diseases.retinal.analyze_retinal') as retinal_model:
            with self.assertRaises(FundusImageUnusable):
                analyze_fundus('example.png', diseases=('glaucoma', 'diabetic_retinopathy'))
        self.worker.analyze.assert_not_called()
        retinal_model.assert_not_called()

    def test_multiple_retinal_diseases_share_image_and_model_call(self):
        dr = 'diabetic_retinopathy'
        amd = 'age_related_macular_degeneration'
        retinal = {dr: DiseaseResult(prompt_similarity_margin=-1.5),
                   amd: DiseaseResult(prompt_similarity_margin=2.5)}
        with patch('modules.vision.diseases.retinal.analyze_retinal', return_value=retinal) as model:
            result = analyze_fundus('example.png', diseases=(dr, 'glaucoma', amd), device='cpu')
        self.images.read_rgb.assert_called_once_with('example.png')
        model.assert_called_once_with(self.image, (dr, amd), 'cpu')
        self.assertEqual(list(result.diseases), [dr, 'glaucoma', amd])
        self.assertEqual(result.diseases[dr].prompt_similarity_margin, -1.5)
        self.assertIsNone(result.diseases[amd].probability)


class RetinalInferenceTests(unittest.TestCase):
    def test_technical_input_check(self):
        from modules.vision.models import FundusImageUnusable
        from modules.vision.utils.images import check_fundus_input, read_rgb

        for image in (np.zeros((64, 64, 3), dtype=np.uint8), np.zeros((20, 64, 3), dtype=np.uint8)):
            with self.assertRaises(FundusImageUnusable):
                check_fundus_input(image)
        sample = Path(__file__).resolve().parents[2] / 'samples' / 'fundus_right_eye.png'
        check_fundus_input(read_rgb(sample))

    def test_two_prompt_pairs_produce_independent_similarity_margins(self):
        diseases = ('diabetic_retinopathy', 'age_related_macular_degeneration')
        upstream = ModuleType('flair.modeling')
        upstream.model = SimpleNamespace(device='original')
        model = Mock()
        model.preprocess_text.return_value = ('tokens', 'mask')
        model.compute_logits.side_effect = [torch.tensor([[8., 5.]]), torch.tensor([[2., 7.]])]
        image = np.zeros((16, 16, 3), dtype=np.uint8)
        with patch.dict(sys.modules, {'flair.modeling': upstream}), \
             patch.object(retinal, '_load_model', return_value=model):
            result = retinal.analyze_retinal(image, diseases, device='cpu')
            model.vision_model.assert_called_once_with(model.preprocess_image.return_value)
            self.assertEqual(model.preprocess_text.call_args_list, [
                call(('no diabetic retinopathy', 'diabetic retinopathy')),
                call(('no age related macular degeneration', 'age related macular degeneration')),
            ])
            self.assertEqual([item.prompt_similarity_margin for item in result.values()], [-3., 5.])
            self.assertTrue(all(item.probability is None and item.severity is None for item in result.values()))
            self.assertEqual(upstream.model.device, 'original')
            model.compute_logits.side_effect = None
            model.compute_logits.return_value = torch.tensor([[0., torch.nan]])
            with self.assertRaisesRegex(ValueError, 'finite FLAIR similarities'):
                retinal.analyze_retinal(image, diseases, device='cpu')

if __name__ == '__main__':
    unittest.main()
