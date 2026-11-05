import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents.specialist import SpecialistAgent
from agents.director import DirectorAgent
from agents.verifier import CitationVerifier

class ReviewRegressionTests(unittest.TestCase):
    evidence = [{'id':'a', 'index':1, 'title':'Guide', 'section':'Test', 'source':'fixture', 'text':'Evidence'}]

    def test_fenced_tool_request_is_executed(self):
        llm = Mock(side_effect=['```json\n{"action":"read_evidence","id":"a"}\n```', 'Analysis [1]'])
        result = SpecialistAgent('Eye', llm, lambda *a, **k: []).execute('Case', self.evidence, {'a':1})
        self.assertEqual(result, 'Analysis [1]')
        self.assertEqual(llm.call_count, 2)

    def test_malformed_tool_request_is_not_a_report(self):
        for reply in ['```json\n{"action":"read_evidence",\n```', '{"action":', '[{"action":"final"}]']:
            with self.subTest(reply=reply), self.assertRaises(ValueError):
                SpecialistAgent('Eye', lambda *a, **k: reply, lambda *a, **k: []).execute('Case', self.evidence, {'a':1})

    def test_director_invalid_citation_reaches_repair(self):
        draft = DirectorAgent(lambda *a, **k: 'Draft [99]').execute({'Eye':'Analysis [1]'}, self.evidence)
        llm = Mock(side_effect=['{"claims":[]}', '{"replacements":[{"quote":"Draft [99]","new":"Draft [1]","citation":[1]}]}', '{"claims":[]}'])
        final, report = CitationVerifier(llm).execute(draft, self.evidence, max_rounds=1)
        self.assertEqual(final, 'Draft [1]')
        self.assertEqual(report['status'], 'rewritten')

    def test_invalid_citation_cannot_pass_even_if_llm_misses_it(self):
        final, report = CitationVerifier(lambda *a, **k: '{"claims":[]}').execute('Draft [99]', self.evidence, max_rounds=0)
        self.assertIsNone(final)
        self.assertEqual(report['status'], 'rejected')

class ConfigurationRegressionTests(unittest.TestCase):
    def test_removed_visual_backend_is_rejected(self):
        import os
        import subprocess
        env = dict(os.environ)
        env["ANALYSIS_PIPELINE"] = "vlm"
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        result = subprocess.run(
            [sys.executable, "-c", "from utils import config"],
            env=env, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ANALYSIS_PIPELINE was removed", result.stderr)

    def test_unknown_citation_rejected_when_llm_verification_disabled(self):
        from unittest.mock import patch
        from report.generation import MedicalReportGenerator
        with patch('utils.config.VERIFY_ENABLED', False):
            final, record = MedicalReportGenerator(api_key='test').verify_synthesis(
                'Draft [99]', ReviewRegressionTests.evidence,
            )
        self.assertIsNone(final)
        self.assertEqual(record['reason'], 'unknown_citations')

if __name__ == '__main__':
    unittest.main()
