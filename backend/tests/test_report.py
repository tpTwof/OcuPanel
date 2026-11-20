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
from report.context import format_visual_findings
from agents.verifier import CitationVerifier
from agents.models import SpecialistRole
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
        def analyze(path, *, diseases):
            self.assertEqual(Path(path).read_bytes(), b'uploaded-image')
            self.assertEqual(diseases, ('glaucoma',))
            return analysis
        with tempfile.TemporaryDirectory() as folder, patch('vision.analyze_fundus', side_effect=analyze), patch('report.generation.retrieve_evidence', return_value=evidence), patch('report.generation.get_retriever', return_value=Mock(similarity=lambda a,b: 0)), patch('utils.config.VERIFY_ENABLED', True), patch('utils.config.MULTI_AGENT_MODE','parallel'):
            result = generator.generate(io.BytesIO(b'uploaded-image'), 'clinical note', folder)
            self.assertIsNotNone(result.summary)
            self.assertEqual(result.verification['status'], 'pass')
            self.assertEqual(result.cup_to_disc_ratio, .6)
            self.assertTrue(Path(result.image_path).exists())
            self.assertEqual(len(result.evidence), 1)
            drafts = [prompt for prompt, kwargs in calls if not kwargs.get('system')]
            self.assertEqual(len(drafts), 1)
            self.assertIn('As a Glaucoma Specialist', drafts[0])
            self.assertIn('Write the final report', drafts[0])
            self.assertTrue(all(kwargs.get('reset') is True for _,kwargs in calls))
            self.assertTrue(any('not assessed' in prompt for prompt,_ in calls))
            self.assertEqual(generator.messages,[generator.system_prompt])

    def test_disease_retrieval_deduplicates_and_scopes_the_evidence(self):
        diseases = ("glaucoma", "diabetic_retinopathy", "age_related_macular_degeneration")
        analysis = EyeAnalysis(diseases={
            diseases[0]: DiseaseResult(probability=.8),
            diseases[1]: DiseaseResult(prompt_similarity_margin=2.5),
            diseases[2]: DiseaseResult(prompt_similarity_margin=-1.5),
        })
        common = {"id": "shared", "text": "Shared evidence"}
        dr_only = {"id": "dr", "text": "DR-only evidence"}
        generator = MedicalReportGenerator(api_key="test")
        llm = Mock(return_value="Findings")
        generator.chat_with_gpt = llm
        with tempfile.TemporaryDirectory() as folder, \
             patch("vision.analyze_fundus", return_value=analysis) as analyze, \
             patch("report.generation.retrieve_evidence", side_effect=[[common], [common, dr_only], []]) as retrieve, \
             patch("utils.config.VERIFY_ENABLED", False):
            result = generator.generate(io.BytesIO(b"image"), "Case note", folder, diseases)
        analyze.assert_called_once()
        self.assertEqual(analyze.call_args.kwargs["diseases"], diseases)
        self.assertEqual(retrieve.call_count, 3)
        self.assertNotIn("Diabetic retinopathy", retrieve.call_args_list[0].args[0])
        self.assertIn("Case note", retrieve.call_args_list[2].args[0])
        self.assertEqual([(item["id"], item["index"]) for item in result.evidence],
                         [("shared", 1), ("dr", 2)])
        self.assertEqual(result.verification["missing_evidence_diseases"], [diseases[2]])
        self.assertEqual(llm.call_count, 4)
        prompts = [call.args[0] for call in llm.call_args_list]
        dr_prompt = next(prompt for prompt in prompts if "As a Diabetic Retinopathy Specialist" in prompt)
        amd_prompt = next(prompt for prompt in prompts if "As a AMD Specialist" in prompt)
        self.assertIn("DR-only evidence", dr_prompt)
        self.assertNotIn("-1.500000", dr_prompt)
        self.assertNotIn("Shared evidence", amd_prompt)
        self.assertIn("No reference was retrieved", amd_prompt)
        self.assertIn("AMD Specialist: no evidence retrieved", prompts[-1])

    def test_single_disease_draft_with_unknown_citation_reaches_verifier_and_regenerates(self):
        analysis = EyeAnalysis(diseases={"glaucoma": DiseaseResult(probability=.9)})
        evidence = [{"id": "guide", "text": "Reference"}]
        generator = MedicalReportGenerator(api_key="test")
        llm = Mock(side_effect=["Draft [99]", "Revised [1]"])
        generator.chat_with_gpt = llm

        def verify(draft, items, regenerate):
            self.assertEqual(draft, "Draft [99]")
            self.assertEqual(items[0]["index"], 1)
            issues = [{"quote": "Draft [99]", "reason": "Unknown citation numbers: [99]"}]
            return regenerate(issues), {"status": "rewritten"}

        with tempfile.TemporaryDirectory() as folder, \
             patch("vision.analyze_fundus", return_value=analysis), \
             patch("report.generation.retrieve_evidence", return_value=evidence), \
             patch.object(generator, "verify_synthesis", side_effect=verify):
            result = generator.generate(io.BytesIO(b"image"), "", folder)
        self.assertEqual(result.summary, "Revised [1]")
        self.assertEqual(llm.call_count, 2)
        self.assertTrue(all("As a Glaucoma Specialist" in call.args[0] for call in llm.call_args_list))
        self.assertIn("Unknown citation numbers", llm.call_args.args[0])

    def test_retinal_findings_remain_in_report_and_pdf_without_an_overlay(self):
        disease = 'diabetic_retinopathy'
        analysis = EyeAnalysis(diseases={disease: DiseaseResult(prompt_similarity_margin=-2.5)})
        generator = MedicalReportGenerator(api_key='test')
        with tempfile.TemporaryDirectory() as folder, \
             patch('vision.analyze_fundus', return_value=analysis) as analyze, \
             patch('report.generation.retrieve_evidence', return_value=[]), \
             patch.object(generator, 'chat_with_gpt', return_value='Assessment'), \
             patch('utils.config.VERIFY_ENABLED', False):
            result = generator.generate(io.BytesIO(b'input'), '',
                                        Path(folder), diseases=(disease,))
            self.assertEqual(analyze.call_args.kwargs['diseases'], (disease,))
            self.assertEqual(result.summary, "Assessment")
            self.assertEqual(result.visual_findings[disease]["prompt_similarity_margin"], -2.5)
            findings_text = format_visual_findings(result.visual_findings)
            self.assertIn("-2.500", findings_text)
            self.assertIn("FLAIR", findings_text)
            self.assertIsNone(result.cup_to_disc_ratio)
            self.assertEqual(result.image_path, '')
            pdf = Path(folder) / 'report.pdf'
            generator.generate_pdf_report(result.image_path, result.cup_to_disc_ratio,
                                          result.summary, str(pdf), visual_findings_text=findings_text)
            self.assertTrue(pdf.read_bytes().startswith(b'%PDF'))

    def test_verifier_rejects_missing_evidence_and_invalid_response(self):
        agent = CitationVerifier(lambda *a,**k:'{}')
        text, result = agent.execute('Draft',[])
        self.assertIsNone(text)
        self.assertEqual(result['reason'],'no_evidence')
        text, result = agent.execute('Draft',[{'index':1,'text':'Evidence'}])
        self.assertIsNone(text)
        self.assertEqual(result['status'],'error')

    def test_pdf_supports_a_table_row_longer_than_one_page(self):
        from report.pdf import PDFRenderer

        text = "| Test | Notes |\n| --- | --- |\n| OCT | " + ("Long clinical observation. " * 160) + " |"
        with tempfile.TemporaryDirectory() as folder:
            pdf = Path(folder) / "table.pdf"
            PDFRenderer().generate_pdf_report("", None, text, str(pdf))
            content = pdf.read_bytes()
            self.assertTrue(content.startswith(b"%PDF"))
            self.assertGreater(content.count(b"/Type /Page\n"), 1)

    def test_no_evidence_keeps_findings_and_skips_all_llm_calls(self):
        diseases = ("glaucoma", "diabetic_retinopathy")
        analysis = EyeAnalysis(diseases={key: DiseaseResult() for key in diseases})
        generator = MedicalReportGenerator(api_key="test")
        with tempfile.TemporaryDirectory() as folder, \
             patch("vision.analyze_fundus", return_value=analysis), \
             patch("report.generation.retrieve_evidence", return_value=[]), \
             patch("utils.config.VERIFY_ENABLED", True), patch.object(generator, "chat_with_gpt") as llm:
            result = generator.generate(io.BytesIO(b"image"), "", folder, diseases)
        llm.assert_not_called()
        self.assertIsNone(result.summary)
        self.assertEqual(result.verification["reason"], "no_evidence")
        self.assertEqual(result.verification["missing_evidence_diseases"], list(diseases))
        self.assertEqual(set(result.visual_findings), set(diseases))

    def test_specialist_failure_is_not_a_report(self):
        agent = SpecialistAgent(SpecialistRole('Eye', 'Review the case.'), lambda *a,**k:'Error: timeout')
        with self.assertRaises(RuntimeError):
            agent.execute('case',[],{})

if __name__ == '__main__':
    unittest.main()
