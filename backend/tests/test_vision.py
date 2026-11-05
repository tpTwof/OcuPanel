import sys
from pathlib import Path
import unittest
from types import ModuleType
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vision import analyze_fundus, EyeAnalysis, DiseaseResult

class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.images = ModuleType('vision.utils.images')
        self.image = object()
        self.images.read_rgb = Mock(return_value=self.image)
        self.worker = ModuleType('vision.diseases.glaucoma.analyzer')
        self.result = EyeAnalysis(diseases={'glaucoma': DiseaseResult(probability=0.7)})
        self.worker.analyze = Mock(return_value=self.result)
        self.modules = patch.dict(sys.modules, {'vision.utils.images': self.images, 'vision.diseases.glaucoma.analyzer': self.worker})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def test_read_once_and_keep_unknown_severity(self):
        result = analyze_fundus('example.png', device='cpu')
        self.images.read_rgb.assert_called_once_with('example.png')
        self.worker.analyze.assert_called_once_with(self.image, 'cpu')
        self.assertEqual(result.diseases['glaucoma'].probability, 0.7)
        self.assertIsNone(result.diseases['glaucoma'].severity)

    def test_invalid_selection_fails_before_reading(self):
        for diseases in [(), ('glaucoma', 'glaucoma'), ('diabetic_retinopathy',)]:
            with self.subTest(diseases=diseases), self.assertRaises(ValueError):
                analyze_fundus('missing.png', diseases=diseases)
        self.images.read_rgb.assert_not_called()

if __name__ == '__main__':
    unittest.main()
