import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vision import EyeAnalysis, DiseaseResult
from report.generation import MedicalReportGenerator
from agents.verifier import CitationVerifier
from agents.specialist import SpecialistAgent

class ReportTests(unittest.TestCase):
    def test_uploaded_stream_runs_agents_and_verifier(self):
        analysis = EyeAnalysis(diseases={'glaucoma': DiseaseResult(probability=.8, measurements={'area_equivalent_cdr': .6})}, overlays={'optic_disc_cup': np.zeros((8,8,3), dtype=np.uint8)})
        evidence = [{'id':'a','title':'Guide','section':'One','source':'test','text':'Evidence','score':1}]
        generator = MedicalReportGenerator(api_key='test')
        calls = []
        def llm(prompt, **kwargs):
            calls.append((prompt, kwargs))
            return '{"claims": []}' if kwargs.get('system') else 'Measured findings and evidence [1].'
        generator.chat_with_gpt = llm
        def analyze(path):
            self.assertEqual(Path(path).read_bytes(), b'uploaded-image')
            return analysis
        with tempfile.TemporaryDirectory() as folder, patch('vision.analyze_fundus', side_effect=analyze), patch('report.generation.retrieve_evidence', return_value=evidence), patch('report.generation.get_retriever', return_value=Mock(similarity=lambda a,b: 0)), patch('utils.config.VERIFY_ENABLED', True), patch('utils.config.MULTI_AGENT_MODE','parallel'):
            summary, verification, ratio, image, ev = generator.generate(io.BytesIO(b'uploaded-image'), 'clinical note', ['Ophthalmologist','Optometrist'], folder)
            self.assertIsNotNone(summary)
            self.assertEqual(verification['status'], 'pass')
            self.assertEqual(ratio,.6)
            self.assertTrue(Path(image).exists())
            self.assertEqual(len(ev),1)
            self.assertTrue(all(kwargs.get('reset') is True for _,kwargs in calls))
            self.assertTrue(any('not assessed' in prompt for prompt,_ in calls))
            self.assertEqual(generator.messages,[generator.system_prompt])

    def test_verifier_rejects_missing_evidence_and_invalid_response(self):
        agent = CitationVerifier(lambda *a,**k:'{}')
        text, result = agent.execute('Draft',[])
        self.assertIsNone(text)
        self.assertEqual(result['reason'],'no_evidence')
        text, result = agent.execute('Draft',[{'index':1,'text':'Evidence'}])
        self.assertIsNone(text)
        self.assertEqual(result['status'],'error')

    def test_specialist_failure_is_not_a_report(self):
        agent = SpecialistAgent('Eye', lambda *a,**k:'Error: timeout', lambda *a,**k:[])
        with self.assertRaises(RuntimeError):
            agent.execute('case',[],{})

if __name__ == '__main__':
    unittest.main()
