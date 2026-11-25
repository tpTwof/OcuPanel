"""Real transactional import acceptance with temporary storage and no inference."""
import copy
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from main import app
from report import assets, service as reports
from report.models import ReportResult, ReportSubmission
from screening import repository
from utils import storage
from utils.auth import current_user
from test_screening import examination


class ImportTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        for target, value in [('utils.storage.DB_PATH', self.folder / 'db'), ('report.assets.ORIGINAL_STORE_DIR', self.folder / 'originals')]:
            patched = patch(target, value); patched.start(); self.addCleanup(patched.stop)
        storage.init_db()
        self.owner = storage.create_user('owner', 'test-password')
        self.other = storage.create_user('other', 'test-password')
        app.dependency_overrides[current_user] = lambda: self.owner
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)
        self.counter = 0

    def report(self, eye='right', legacy=False, rejected=False, status='pass'):
        if legacy:
            return storage.save_report(self.owner['id'], None, '', 'Legacy research', {'status': status}, [], rejected,
                                       cup_to_disc=.6, visual_findings={'glaucoma': {'measurements': {'area_equivalent_cdr': .6}}})
        findings = {'glaucoma': {'probability': .9, 'measurements': {'area_equivalent_cdr': .6}, 'model_sources': {'classifier': 'fixture@v1'}},
                    'diabetic_retinopathy': {'prompt_similarity_margin': -3, 'model_sources': {'image_text_model': 'fixture-FLAIR'}}}
        request = ReportSubmission(b'synthetic-image-bytes', 'fixture.png', '合成病例备注', diseases=tuple(findings),
                                   laterality=eye, captured_at=datetime(2026, 11, 25, 8, tzinfo=timezone.utc), device='fixture-camera', synthetic=True)
        result = ReportResult(None if rejected else 'Research summary', {'status': status}, .6, '', [], findings)
        return reports._archive_result(self.owner['id'], request, result, False)['report_id']

    def base(self):
        exam = examination()
        for eye in exam['eyes']:
            eye['captures'] = []
            eye['tasks'] = [{**eye['tasks'][0], 'status': 'not_captured', 'finding': 'not_assessed', 'reason': ''}]
        exam['note'] = ''
        return exam

    def preview(self, report_ids, case=None, **extra):
        body = {'examination': case['examination'] if case else self.base(),
                'bindings': [{'report_id': report_id, 'laterality': eye} for eye, report_id in zip(('right', 'left'), report_ids)],
                'note_policy': 'append', **extra}
        if case: body.update(case_id=case['id'], expected_revision=case['revision'])
        response = self.client.post('/api/screening/imports/preview', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def confirm(self, preview, key=None, expected=200):
        self.counter += 1
        response = self.client.post(f"/api/screening/imports/{preview['preview_id']}/confirm", json={
            'idempotency_key': key or f'confirm-import-{self.counter}', 'synthetic_rehearsal_confirmed': True, 'laterality_confirmed': True})
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def test_versioned_shared_images_follow_current_membership(self):
        report = self.report()
        image_name = "a" * 32
        self.enterContext(patch.object(reports, "IMG_STORE_DIR", self.folder))
        (self.folder / (image_name + ".jpg")).write_bytes(b"synthetic overlay")
        with storage.connect() as conn:
            conn.execute("UPDATE reports SET img_name=? WHERE id=?", (image_name, report))
            for actor, role in [(self.owner, "capture"), (self.other, "reader")]:
                conn.execute("INSERT INTO screening_members VALUES(?,?,?)", (actor["id"], "Demo", role))
        case = self.confirm(self.preview([report]))
        app.dependency_overrides[current_user] = lambda: self.other
        url = f"/api/screening/cases/{case['id']}/sources/{report}"
        self.assertEqual(self.client.get(url + "/overlay?revision=1").content, b"synthetic overlay")
        self.assertEqual(self.client.get(url + "/original?revision=1").content, b"synthetic-image-bytes")
        with storage.connect() as conn:
            conn.execute("DELETE FROM screening_members WHERE user_id=?", (self.other["id"],))
        self.assertEqual(self.client.get(url + "/overlay?revision=1").status_code, 404)
        self.assertEqual(self.client.get(url + "/original?revision=1").status_code, 404)

    def test_bilateral_import_preserves_raw_metrics_and_pending_human_assessment(self):
        right, left = self.report(), self.report('left')
        preview = self.preview([right, left])
        self.assertEqual(repository.list_cases(self.owner['id']), [])  # Preview has no case side effect.
        saved = self.confirm(preview)
        self.assertEqual(saved['stage'], 'draft')
        self.assertIsNone(saved['signature'])
        self.assertEqual(len(saved['analysis_sources']), 2)
        self.assertEqual(saved['examination']['note'], '合成病例备注')
        for eye in saved['examination']['eyes']:
            self.assertEqual(len(eye['captures']), 1)
            self.assertTrue(all(task['status'] == 'not_assessed' and task['finding'] == 'not_assessed' for task in eye['tasks']))
        self.assertEqual(saved['analysis_sources'][0]['report']['visual_findings']['diabetic_retinopathy']['prompt_similarity_margin'], -3)
        original = self.client.get(f'/api/reports/{right}/original')
        self.assertEqual(original.content, b'synthetic-image-bytes')

    def test_single_eye_leaves_other_eye_missing_and_requires_explicit_eye(self):
        report = self.report(legacy=True)
        saved = self.confirm(self.preview([report]))
        self.assertEqual(saved['examination']['eyes'][1]['tasks'][0]['status'], 'not_captured')
        self.assertEqual(saved['examination']['eyes'][0]['tasks'][0]['status'], 'not_assessed')
        self.assertEqual(saved['analysis_sources'][0]['original']['status'], 'missing')
        response = self.client.post(f"/api/screening/cases/{saved['id']}/commands", json={'action': 'review', 'expected_revision': 1,
            'idempotency_key': 'review-missing-image', 'original_images_checked': True, 'case_checked': True, 'comment': 'test'})
        self.assertEqual(response.status_code, 409)
        response = self.client.post('/api/screening/imports/preview', json={'examination': self.base(), 'bindings': [{'report_id': report}]})
        self.assertEqual(response.status_code, 422)

    def test_repeat_confirmation_and_repeat_import_do_not_duplicate_versions(self):
        report = self.report()
        preview = self.preview([report])
        first = self.confirm(preview, 'same-confirm-key')
        self.assertEqual(self.confirm(preview, 'same-confirm-key'), first)
        self.assertEqual(self.confirm(preview, 'different-confirm-key'), first)
        repeated = self.preview([report], first)
        self.assertTrue(repeated['no_changes'])
        self.assertEqual(self.confirm(repeated)['revision'], 1)
        self.assertEqual(len(repository.list_cases(self.owner['id'])), 1)

    def test_import_preserves_human_findings_and_signed_history(self):
        case = self.client.post('/api/screening/cases', json={'idempotency_key': 'human-case-create', 'examination': examination()}).json()
        original_task = copy.deepcopy(case['examination']['eyes'][0]['tasks'][0])
        for action, fields in [('review', {'original_images_checked': True, 'case_checked': True, 'comment': 'test'}), ('sign', {'plan': 'human plan'})]:
            case = self.client.post(f"/api/screening/cases/{case['id']}/commands", json={'action': action, 'expected_revision': case['revision'], 'idempotency_key': f'human-case-{action}', **fields}).json()
        report = self.report()
        saved = self.confirm(self.preview([report], case, note_policy='keep'))
        self.assertEqual(saved['examination']['eyes'][0]['tasks'][0], original_task)
        self.assertEqual(saved['stage'], 'draft')
        self.assertIsNone(saved['signature'])
        self.assertEqual(repository.get_case(self.owner['id'], case['id'], 3)['signature']['plan'], 'human plan')
        self.assertEqual(saved['examination']['eyes'][1], case['examination']['eyes'][1])

    def test_catalog_detail_original_preview_and_confirmation_are_account_isolated(self):
        report = self.report()
        preview = self.preview([report])
        app.dependency_overrides[current_user] = lambda: self.other
        self.assertEqual(self.client.get('/api/reports').json(), [])
        for suffix in ('', '/original'):
            self.assertEqual(self.client.get(f'/api/reports/{report}{suffix}').status_code, 404)
        self.assertEqual(self.client.post('/api/screening/imports/preview', json={'examination': self.base(), 'bindings': [{'report_id': report, 'laterality': 'right'}]}).status_code, 404)
        self.confirm(preview, expected=404)

    def test_source_mutation_and_stale_preview_are_rejected(self):
        report = self.report()
        preview = self.preview([report])
        with storage.connect() as conn: conn.execute('UPDATE reports SET summary=? WHERE id=?', ('changed', report))
        self.confirm(preview, expected=409)
        first = self.confirm(self.preview([report]))
        stale = self.preview([report], first)
        self.client.post(f"/api/screening/cases/{first['id']}/commands", json={'action': 'handoff', 'expected_revision': 1, 'idempotency_key': 'mutate-after-preview', 'followup_owner': 'next', 'reason': 'concurrent'})
        self.confirm(stale, expected=409)

    def test_expiry_and_tampered_original_are_not_ignored(self):
        report = self.report()
        preview = self.preview([report])
        with storage.connect() as conn: conn.execute('UPDATE screening_import_previews SET expires_at=0 WHERE id=?', (preview['preview_id'],))
        self.confirm(preview, expected=409)
        metadata = storage.get_report(self.owner['id'], report)['source_metadata']
        assets.original_path(metadata).write_bytes(b'tampered')
        self.assertEqual(self.client.get(f'/api/reports/{report}/original').status_code, 404)
        preview = self.preview([report])
        self.assertEqual(preview['candidate']['analysis_sources'][0]['original']['status'], 'hash_mismatch')

    def test_rejected_and_disabled_reports_remain_research_not_signed_plans(self):
        for status in ('rejected', 'disabled', 'error'):
            with self.subTest(status=status):
                report = self.report(rejected=status != 'disabled', status=status)
                saved = self.confirm(self.preview([report]))
                self.assertEqual(saved['analysis_sources'][0]['report']['verification']['status'], status)
                self.assertIsNone(saved['signature'])
                self.assertEqual(saved['analysis_sources'][0]['source_kind'], 'model_research')

    def test_synthetic_declaration_and_known_eye_mismatch_cannot_be_bypassed(self):
        report = self.report('left')
        bad = self.client.post('/api/screening/imports/preview', json={'examination': self.base(), 'bindings': [{'report_id': report, 'laterality': 'right'}]})
        self.assertEqual(bad.status_code, 422)
        preview = self.preview([self.report()])
        response = self.client.post(f"/api/screening/imports/{preview['preview_id']}/confirm", json={'idempotency_key': 'invalid-declaration', 'synthetic_rehearsal_confirmed': False, 'laterality_confirmed': True})
        self.assertEqual(response.status_code, 422)
        exam = self.base(); exam['eyes'][0]['analysis_refs'] = ['forged-report']
        self.assertEqual(self.client.post('/api/screening/cases', json={'idempotency_key': 'forged-analysis-ref', 'examination': exam}).status_code, 422)

    def test_correcting_capture_metadata_keeps_a_single_source_and_original(self):
        report = self.report()
        first = self.confirm(self.preview([report]))
        body = {'case_id': first['id'], 'expected_revision': 1, 'examination': first['examination'], 'bindings': [
            {'report_id': report, 'laterality': 'right', 'device': 'corrected-camera', 'captured_at': '2026-11-25T16:00:00+08:00'}]}
        preview = self.client.post('/api/screening/imports/preview', json=body).json()
        saved = self.confirm(preview)
        self.assertEqual(len(saved['analysis_sources']), 1)
        self.assertEqual(len(saved['examination']['eyes'][0]['captures']), 1)
        self.assertEqual(saved['analysis_sources'][0]['device'], 'corrected-camera')
        self.assertEqual(saved['examination']['note'], '合成病例备注')
        self.assertEqual(repository.get_case(self.owner['id'], saved['id'], 1)['analysis_sources'][0]['device'], 'fixture-camera')

    def test_declared_real_source_is_rejected_even_with_synthetic_confirmation(self):
        report = storage.save_report(self.owner['id'], None, '', 'real-source-marker', {}, [], False,
                                     source_metadata={'data_kind': 'clinical'})
        response = self.client.post('/api/screening/imports/preview', json={'examination': self.base(), 'bindings': [{'report_id': report, 'laterality': 'right'}]})
        self.assertEqual(response.status_code, 422)

    def test_import_failure_rolls_back_case_snapshot_and_receipt(self):
        import sqlite3
        preview = self.preview([self.report()])
        with storage.connect() as conn:
            conn.execute("CREATE TRIGGER fail_import BEFORE INSERT ON screening_versions BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.confirm(preview)
        self.assertEqual(repository.list_cases(self.owner['id']), [])
        with storage.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM screening_requests').fetchone()[0], 0)
            conn.execute('DROP TRIGGER fail_import')
        self.assertEqual(self.confirm(preview)['revision'], 1)

    def test_import_sources_are_identical_in_context_json_and_signed_pdf(self):
        from report.pdf import PDFRenderer
        report = self.report()
        saved = self.confirm(self.preview([report]))
        context = self.client.get(f"/api/screening/cases/{saved['id']}/context?revision=1").json()
        exported = self.client.get(f"/api/screening/cases/{saved['id']}/export?revision=1").json()
        self.assertEqual(context['analysis_sources'], exported['analysis_sources'])
        updated = copy.deepcopy(saved['examination'])
        for eye in updated['eyes']:
            for task in eye['tasks']:
                if task['status'] == 'not_assessed':
                    task.update(status='ungradable', reason='人工确认不可判读', next_step='安排人工检查')
        commands = [('revise', {'examination': updated, 'reason': '人工修订'}), ('review', {'original_images_checked': True, 'case_checked': True, 'comment': '核对原图'}), ('sign', {'plan': '合成逐眼人工计划'})]
        for index, (action, fields) in enumerate(commands):
            response = self.client.post(f"/api/screening/cases/{saved['id']}/commands", json={'action': action, 'expected_revision': saved['revision'], 'idempotency_key': f'pdf-import-action-{index}', **fields})
            self.assertEqual(response.status_code, 200, response.text)
            saved = response.json()
        with patch.object(PDFRenderer, 'generate_pdf_report', side_effect=PDFRenderer().generate_pdf_report) as render:
            response = self.client.get(f"/api/screening/cases/{saved['id']}/pdf?revision={saved['revision']}")
        self.assertEqual(response.status_code, 200)
        text = render.call_args.args[2]
        self.assertIn(exported['analysis_sources'][0]['report_hash'], text)
        self.assertIn('model_research', exported['analysis_sources'][0]['source_kind'])
        self.assertIn('area_equivalent_cdr', text)
        self.assertEqual(repository.get_case(self.owner['id'], saved['id'], 1)['examination'], exported['examination'])


if __name__ == '__main__': unittest.main()
