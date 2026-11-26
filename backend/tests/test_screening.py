"""Offline rehearsal acceptance: bilateral consistency, durable retries and isolation."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.main import app
from modules.screening import repository, service
from modules.screening.models import CreateCase
from core import storage
from common.auth import current_user


def examination() -> dict:
    captures = [{"image_ref": "synthetic:original", "captured_at": "2026-11-24T10:00:00+08:00",
                 "device": "synthetic-device", "field": "disc"}]
    return {"synthetic": True, "institution": "Demo", "encounter_id": "demo-001", "patient_group": "patient-001",
            "age": 50, "followup_owner": "operator", "eyes": [
                {"laterality": "right", "captures": captures, "tasks": [{"disease": "glaucoma", "status": "gradable",
                 "finding": "suspect", "visible_region": "disc", "next_step": "manual review"}]},
                {"laterality": "left", "captures": captures * 2, "tasks": [{"disease": "glaucoma", "status": "ungradable",
                 "visible_region": "disc not visible", "reason": "blur after retake", "next_step": "manual examination"}]}]}


class ScreeningTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.patch = patch.object(storage, "DB_PATH", Path(folder.name) / "db.sqlite")
        self.patch.start()
        self.addCleanup(self.patch.stop)
        storage.init_db()
        storage.init_db()  # Existing installations and repeated startups.
        self.owner = storage.create_user("reader", "test-password")
        self.other = storage.create_user("other", "test-password")
        self.client = TestClient(app)
        app.dependency_overrides[current_user] = lambda: self.owner
        self.addCleanup(app.dependency_overrides.clear)
        self.sequence = 0

    def create(self) -> dict:
        response = self.client.post("/api/screening/cases", json={"idempotency_key": "create-test-001", "examination": examination()})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def command(self, case: dict, action: str, expected: int = 200, **payload) -> dict:
        self.sequence += 1
        response = self.client.post(f"/api/screening/cases/{case['id']}/commands", json={
            "action": action, "expected_revision": case["revision"], "idempotency_key": f"command-test-{self.sequence}", **payload})
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def sign(self, case: dict) -> dict:
        case = self.command(case, "review", original_images_checked=True, case_checked=True, comment="synthetic check")
        return self.command(case, "sign", plan="right review; left manual exam")

    def test_urgent_handoff_and_same_eye_oct(self):
        exam = examination()
        exam["urgent_symptoms"] = ["curtain"]
        exam["urgent_handoff"] = False
        payload = {"examination": exam, "idempotency_key": "synthetic-oct"}
        self.assertEqual(self.client.post("/api/screening/cases", json=payload).status_code, 422)
        exam["urgent_handoff"] = True
        right, left = [eye["tasks"][0] for eye in exam["eyes"]]
        right["disease"] = left["disease"] = "dme"
        left["reference_exam"] = {"modality": "OCT", "source": "synthetic record",
                                  "acquired_on": "2026-11-24", "interpretation": "synthetic finding"}
        case = self.client.post("/api/screening/cases", json=payload).json()
        reviewed = self.command(case, "review", original_images_checked=True, case_checked=True, comment="fixture")
        self.command(reviewed, "sign", expected=409, plan="fixture")
        right["reference_exam"] = left["reference_exam"].copy()
        revised = self.command(reviewed, "revise", examination=exam, reason="synthetic OCT added")
        self.assertEqual(self.sign(revised)["stage"], "signed")

    def test_followup_records_bind_to_a_signed_plan(self):
        case = self.create()
        data = {"adherence": "synthetic reminder received", "symptoms": "synthetic symptom report", "next_visit": "2026-12-10"}
        self.command(case, "followup", expected=409, **data)
        signed = self.sign(case)
        saved = self.command(signed, "followup", **data)
        self.assertEqual(saved["events"][-1]["detail"]["signed_revision"], signed["signature"]["signed_revision"])
        self.assertIn(data["adherence"], service.followup_context(self.owner["id"], saved["id"], saved["revision"])["explanation"])
        revoked = self.command(saved, "revoke", reason="synthetic correction")
        self.command(revoked, "followup", expected=409, **data)

    def test_bilateral_retake_review_referral_receipt_and_history(self):
        case = self.create()
        self.command(case, "sign", expected=409, plan="cannot sign before review")
        signed = self.sign(case)
        referred = self.command(signed, "refer", destination="demo receiving unit", followup_owner="tracker",
                                due_at="2026-11-25T18:00:00+08:00", eyes=["right", "left"])
        referral, = referred["referrals"]
        self.assertEqual(referral["signed_revision"], signed["revision"])
        accepted = self.command(referred, "receipt", referral_id=referral["id"], status="accepted", note="received")
        arrived = self.command(accepted, "receipt", referral_id=referral["id"], status="arrived", note="seen")
        self.command(arrived, "receipt", referral_id=referral["id"], status="lost", note="invalid", expected=409)
        context = self.client.get(f"/api/screening/cases/{case['id']}/context?revision={signed['revision']}").json()
        self.assertIn("左眼", context["explanation"])
        self.assertIn("不可判读", context["explanation"])
        self.assertEqual(context["eyes"][1]["tasks"][0]["finding"], "not_assessed")
        exported = self.client.get(f"/api/screening/cases/{case['id']}/export?revision={signed['revision']}")
        self.assertEqual(exported.json(), signed)
        self.assertEqual(exported.headers["cache-control"], "no-store")
        revised = self.command(arrived, "revise", examination=examination(), reason="new capture")
        self.assertIsNone(revised["signature"])
        self.assertEqual(revised["stage"], "draft")
        self.assertEqual(revised["referrals"][0]["signed_revision"], signed["revision"])
        self.assertEqual(repository.get_case(self.owner["id"], case["id"], signed["revision"]), signed)

    def test_idempotency_survives_restart_and_rejects_key_reuse(self):
        case = self.create()
        storage.init_db()
        self.assertEqual(self.create(), case)
        body = {"action": "review", "expected_revision": 1, "idempotency_key": "review-retry-001",
                "original_images_checked": True, "case_checked": True, "comment": "checked"}
        url = f"/api/screening/cases/{case['id']}/commands"
        first = self.client.post(url, json=body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.client.post(url, json=body).json(), first.json())
        self.assertEqual(self.client.post(url, json={**body, "comment": "changed"}).status_code, 409)
        self.assertEqual(len(repository.get_case(self.owner["id"], case["id"])["events"]), 2)

    def test_concurrent_same_submission_only_creates_one_case(self):
        request = CreateCase(idempotency_key="concurrent-request", examination=examination())
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: service.create_case(self.owner, request), range(4)))
        self.assertEqual(len({result["id"] for result in results}), 1)
        self.assertEqual(len(repository.list_cases(self.owner["id"])), 1)

    def test_stale_revision_and_manual_handoff(self):
        case = self.create()
        result = self.command(case, "handoff", followup_owner="backup reader", reason="model offline")
        self.command(case, "handoff", followup_owner="stale reader", reason="stale update", expected=409)
        self.assertEqual(result["examination"]["followup_owner"], "backup reader")
        self.assertEqual(result["events"][-1]["actor_id"], self.owner["id"])

    def test_account_isolation_on_every_path_and_authentication(self):
        case = self.create()
        app.dependency_overrides[current_user] = lambda: self.other
        root = f"/api/screening/cases/{case['id']}"
        self.assertEqual(self.client.get("/api/screening/cases").json(), [])
        for suffix in ("", "?revision=1", "/export?revision=1", "/context?revision=1", "/pdf?revision=1"):
            self.assertEqual(self.client.get(root + suffix).status_code, 404)
        self.command(case, "handoff", followup_owner="intruder", reason="test", expected=404)
        app.dependency_overrides.clear()
        self.assertEqual(self.client.get("/api/screening/cases").status_code, 401)

    def test_invalid_states_and_real_cases_rejected(self):
        cases = []
        for field, value in (("synthetic", False), ("age", 17), ("followup_owner", "  ")):
            exam = examination(); exam[field] = value; cases.append(exam)
        exam = examination(); exam["eyes"][1]["laterality"] = "right"; cases.append(exam)
        exam = examination(); exam["eyes"][1]["tasks"][0]["finding"] = "no_target_signs"; cases.append(exam)
        exam = examination(); exam["eyes"][0]["captures"][0]["image_ref"] = "real-patient.jpg"; cases.append(exam)
        exam = examination(); exam["eyes"][0]["captures"][0]["captured_at"] = "2026-11-24T10:00:00"; cases.append(exam)
        for exam in cases:
            with self.subTest(exam=exam):
                response = self.client.post("/api/screening/cases", json={"idempotency_key": "invalid-case", "examination": exam})
                self.assertEqual(response.status_code, 422, response.text)

    def test_pdf_uses_exact_snapshot_and_cleans_temporary_files(self):
        from modules.report.pdf import PDFRenderer
        case = self.create()
        root = f"/api/screening/cases/{case['id']}"
        self.assertEqual(self.client.get(root + "/pdf?revision=1").status_code, 422)
        signed = self.sign(case)
        with patch.object(PDFRenderer, "generate_pdf_report", side_effect=PDFRenderer().generate_pdf_report) as render:
            response = self.client.get(root + f"/pdf?revision={signed['revision']}")
        self.assertEqual(response.status_code, 200, response.text[:300])
        self.assertTrue(response.content.startswith(b"%PDF"))
        text = render.call_args.args[2]
        self.assertIn("合成病例演练", text)
        self.assertIn("不可判读", text)
        self.assertIn("补拍 1 次", text)
        self.assertNotIn("verification_status", render.call_args.kwargs)
        self.assertFalse(Path(render.call_args.kwargs["output_path"]).exists())


if __name__ == "__main__":
    unittest.main()
