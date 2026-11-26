import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.vision import EyeAnalysis, DiseaseResult
from modules.report.generation import MedicalReportGenerator
from modules.report.context import format_visual_findings
from modules.agent.verifier import CitationVerifier
from modules.agent.models import SpecialistRole
from modules.agent.specialist import SpecialistAgent


def verified_reply(quote='', source='Evidence'):
    grounding = []
    if '[1]' in quote:
        grounding = [{'quote': quote, 'basis': 'medical_knowledge', 'citations': [1],
                      'sources': [{'kind': 'evidence', 'index': 1, 'quote': source}], 'reason': 'Fixture support'}]
    return json.dumps({'claims': [], 'grounding': grounding})


class ReportTests(unittest.TestCase):
    def test_unresolved_clinical_draft_retains_only_original_case_input(self):
        analysis = EyeAnalysis(diseases={'glaucoma': DiseaseResult(probability=.8)})
        note = '原始病例：左眼 24 mmHg。'
        verification = {'status': 'rejected', 'reason': 'unverified_claims_remain', 'policy_version': 2,
                        'remaining_issues': [{'quote': 'Unsupported diagnosis.', 'impact': 'core'}]}
        generator = MedicalReportGenerator(api_key='test')
        generator.chat_with_gpt = Mock(return_value='Unsupported diagnosis.')
        with tempfile.TemporaryDirectory() as folder, \
             patch('modules.vision.analyze_fundus', return_value=analysis), \
             patch('modules.report.generation.retrieve_evidence', return_value=[{'id': 'guide', 'text': 'Reference'}]), \
             patch.object(generator, 'verify_synthesis', return_value=(None, verification)):
            result = generator.generate(io.BytesIO(b'image'), note, folder)
        self.assertEqual(result.verification['status'], 'limited')
        self.assertEqual(result.verification['diagnostic_status'], 'rejected')
        self.assertIn(note, result.summary)
        self.assertNotIn('Unsupported diagnosis.', result.summary)
        self.assertEqual(result.verification['remaining_issues'][0]['quote'], 'Unsupported diagnosis.')

    def test_source_summary_does_not_mask_model_or_format_failure(self):
        from modules.report.source_summary import case_source_summary
        for verification in ({'status': 'error', 'policy_version': 2, 'reason': 'verify_call_failed'},
                             {'status': 'rejected', 'policy_version': 2, 'reason': 'no_evidence'}):
            text, record = case_source_summary('Input data.', verification)
            self.assertIsNone(text)
            self.assertEqual(record, verification)

    def test_local_reference_gap_preserves_case_data_and_delivers_rechecked_report(self):
        import json
        analysis = EyeAnalysis(diseases={'glaucoma': DiseaseResult(
            probability=.8, measurements={'area_equivalent_cdr': .6})})
        fact = '本例右眼眼压 26 mmHg。'
        extra = '与本例无关的检查条款 [1]。'
        issue = json.dumps({'grounding': [], 'claims': [{'quote': extra, 'verdict': 'unsupported',
                                        'citations': [1], 'impact': 'local', 'reason': '条款不适用'}]})
        generator = MedicalReportGenerator(api_key='test')
        generator.chat_with_gpt = Mock(side_effect=[
            fact + '\n' + extra, issue, '{"replacements":[]}', issue, verified_reply(),
        ])
        with tempfile.TemporaryDirectory() as folder, \
             patch('modules.vision.analyze_fundus', return_value=analysis), \
             patch('modules.report.generation.retrieve_evidence', return_value=[{'id': 'guide', 'text': 'Evidence'}]), \
             patch('modules.report.generation.get_retriever', return_value=Mock(similarity=lambda a, b: 0)), \
             patch('core.config_impl.VERIFY_ENABLED', True), patch('core.config_impl.VERIFY_MAX_ROUNDS', 1):
            result = generator.generate(io.BytesIO(b'fixture-image'), fact, folder)
        self.assertEqual(result.summary, fact)
        self.assertEqual(result.cup_to_disc_ratio, .6)
        self.assertEqual(result.verification['status'], 'rewritten')
        self.assertEqual(result.verification['fixed'][0]['quote'], extra)
        self.assertEqual(result.verification['fixed'][0]['reason'], '条款不适用')

    def test_sample_note_report_recovers_from_invalid_verifier_claims(self):
        analysis = EyeAnalysis(diseases={'glaucoma': DiseaseResult(probability=.8)})
        evidence = [{'id': 'guide', 'text': 'Evidence', 'index': 1}]
        note = (Path(__file__).resolve().parents[2] / 'samples' / 'clinical_note.txt').read_text(encoding='utf-8')
        generator = MedicalReportGenerator(api_key='test')
        generator.chat_with_gpt = Mock(side_effect=[
            'Case findings [1].', '{"claims":[{}]}', verified_reply('Case findings [1].'),
        ])
        with tempfile.TemporaryDirectory() as folder, \
             patch('modules.vision.analyze_fundus', return_value=analysis), \
             patch('modules.report.generation.retrieve_evidence', return_value=evidence), \
             patch('modules.report.generation.get_retriever', return_value=Mock(similarity=lambda a, b: 0)), \
             patch('core.config_impl.VERIFY_ENABLED', True):
            result = generator.generate(io.BytesIO(b'fixture-image'), note, folder)
        self.assertEqual(result.summary, 'Case findings [1].')
        self.assertEqual(result.verification['status'], 'pass')
        self.assertEqual(result.verification['format_retries'], 1)

    def test_uploaded_stream_runs_agents_and_verifier(self):
        analysis = EyeAnalysis(diseases={'glaucoma': DiseaseResult(probability=.8, measurements={'area_equivalent_cdr': .6})}, overlays={'optic_disc_cup': np.zeros((8,8,3), dtype=np.uint8)})
        evidence = [{'id':'a','title':'Guide','section':'One','source':'test','text':'Evidence','score':1}]
        generator = MedicalReportGenerator(api_key='test')
        calls = []
        def llm(prompt, **kwargs):
            calls.append((prompt, kwargs))
            return verified_reply('Measured findings and evidence [1].') if kwargs.get('system') else 'Measured findings and evidence [1].'
        generator.chat_with_gpt = llm
        def analyze(path, *, diseases):
            self.assertEqual(Path(path).read_bytes(), b'uploaded-image')
            self.assertEqual(diseases, ('glaucoma',))
            return analysis
        with tempfile.TemporaryDirectory() as folder, patch('modules.vision.analyze_fundus', side_effect=analyze), patch('modules.report.generation.retrieve_evidence', return_value=evidence), patch('modules.report.generation.get_retriever', return_value=Mock(similarity=lambda a,b: 0)), patch('core.config_impl.VERIFY_ENABLED', True), patch('core.config.MULTI_AGENT_MODE','parallel'):
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
             patch("modules.vision.analyze_fundus", return_value=analysis) as analyze, \
             patch("modules.report.generation.retrieve_evidence", side_effect=[[common], [common, dr_only], []]) as retrieve, \
             patch("core.config_impl.VERIFY_ENABLED", False):
            result = generator.generate(io.BytesIO(b"image"), "Case note", folder, diseases)
        analyze.assert_called_once()
        self.assertEqual(analyze.call_args.kwargs["diseases"], diseases)
        self.assertEqual(retrieve.call_count, 3)
        self.assertIn('青光眼', retrieve.call_args_list[0].kwargs['boost'])
        self.assertIn('diabetic retinopathy', retrieve.call_args_list[1].kwargs['boost'])
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

        def verify(draft, items, regenerate, *, case_context):
            self.assertIn('Clinician note:', case_context)
            self.assertEqual(draft, "Draft [99]")
            self.assertEqual(items[0]["index"], 1)
            issues = [{"quote": "Draft [99]", "reason": "Unknown citation numbers: [99]"}]
            return regenerate(issues), {"status": "rewritten"}

        with tempfile.TemporaryDirectory() as folder, \
             patch("modules.vision.analyze_fundus", return_value=analysis), \
             patch("modules.report.generation.retrieve_evidence", return_value=evidence), \
             patch.object(generator, "verify_synthesis", side_effect=verify):
            result = generator.generate(io.BytesIO(b"image"), "", folder)
        self.assertEqual(result.summary, "Revised [1]")
        self.assertEqual(llm.call_count, 2)
        self.assertTrue(all("As a Glaucoma Specialist" in call.args[0] for call in llm.call_args_list))
        self.assertIn("Unknown citation numbers", llm.call_args.args[0])

    def test_multi_disease_revision_reuses_specialists_and_can_still_reject(self):
        diseases = ("glaucoma", "diabetic_retinopathy")
        analysis = EyeAnalysis(diseases={key: DiseaseResult() for key in diseases})
        generator = MedicalReportGenerator(api_key="test")
        def llm(prompt, **kwargs):
            return "Specialist opinion [1]" if "As a " in prompt else "Draft [99]"

        generator.chat_with_gpt = Mock(side_effect=llm)

        def verify(draft, evidence, regenerate, *, case_context):
            self.assertIn('Clinician note:', case_context)
            self.assertEqual(draft, "Draft [99]")
            self.assertEqual(evidence[0]["index"], 1)
            issues = [{"quote": draft, "reason": "Unknown citation [99]"}]
            self.assertEqual(regenerate(issues), draft)
            return None, {"status": "rejected", "remaining_issues": issues}

        with tempfile.TemporaryDirectory() as folder, \
             patch("modules.vision.analyze_fundus", return_value=analysis), \
             patch("modules.report.generation.retrieve_evidence", return_value=[{"id": "guide", "text": "Evidence"}]), \
             patch.object(generator, "verify_synthesis", side_effect=verify):
            result = generator.generate(io.BytesIO(b"image"), "", folder, diseases)

        prompts = [call.args[0] for call in generator.chat_with_gpt.call_args_list]
        self.assertEqual(len(prompts), 4)
        self.assertIn("Glaucoma Specialist Report:", prompts[2])
        self.assertIn("Diabetic Retinopathy Specialist Report:", prompts[3])
        self.assertIn("Unknown citation [99]", prompts[3])
        self.assertIsNone(result.summary)
        self.assertEqual(result.verification["status"], "rejected")

    def test_retinal_findings_remain_in_report_and_pdf_without_an_overlay(self):
        disease = 'diabetic_retinopathy'
        analysis = EyeAnalysis(diseases={disease: DiseaseResult(prompt_similarity_margin=-2.5)})
        generator = MedicalReportGenerator(api_key='test')
        with tempfile.TemporaryDirectory() as folder, \
             patch('modules.vision.analyze_fundus', return_value=analysis) as analyze, \
             patch('modules.report.generation.retrieve_evidence', return_value=[]), \
             patch.object(generator, 'chat_with_gpt', return_value='Assessment'), \
             patch('core.config_impl.VERIFY_ENABLED', False):
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
            pdf = Path(folder) / 'modules.report.pdf'
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
        from modules.report.pdf import PDFRenderer

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
             patch("modules.vision.analyze_fundus", return_value=analysis), \
             patch("modules.report.generation.retrieve_evidence", return_value=[]), \
             patch("core.config_impl.VERIFY_ENABLED", True), patch.object(generator, "chat_with_gpt") as llm:
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
