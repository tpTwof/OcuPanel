"""Synthetic queue, archive recovery and pilot-role acceptance."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "backend")]
from archive_maintenance import expire_originals, materialize
from configure_screening_site import Site, configure
from screening_operations import summarize
from modules.screening.access import check_endpoint
from core.exceptions import ApplicationError
from fastapi.testclient import TestClient
from main import app
from modules.report import queue
from modules.report.models import ReportResult
from modules.screening import repository
from test_screening import examination
from core import storage
from common.deps import current_user


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.source = self.root / "source"
        for target, path in [("core.storage.DB_PATH", "ocupanel.db"), ("modules.report.assets.ORIGINAL_STORE_DIR", "original_store"),
                             ("modules.report.service.IMG_STORE_DIR", "img_store")]:
            self.enterContext(patch(target, self.source / path))
        storage.init_db()
        self.owner = storage.create_user("nurse", "fixture-password")
        self.reader = storage.create_user("reader", "fixture-password")
        self.other = storage.create_user("other", "fixture-password")
        self.actor = self.owner
        app.dependency_overrides[current_user] = lambda: self.actor
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def post_job(self, key="fixture-job-1", image=b"synthetic-fixture"):
        return self.client.post("/api/report-jobs", files={"file": ("test.png", image, "image/png")},
                                data={"request_key": key, "synthetic": "true"})

    def test_duplicate_submission_recovery_and_archive_restore(self):
        with ThreadPoolExecutor(2) as pool:
            jobs = list(pool.map(lambda _: self.post_job().json()["id"], range(2)))
        self.assertEqual(jobs[0], jobs[1])
        self.assertEqual(self.post_job(image=b"different").status_code, 409)
        job = jobs[0]
        with patch("modules.report.service._load_generator", new_callable=AsyncMock), patch(
            "modules.report.service._run_report_pipeline", new_callable=AsyncMock,
            return_value=ReportResult("fixture", {"status": "pass"}, None, "", [], {})
        ) as inference:
            self.assertTrue(queue.run_one())
            self.assertEqual(queue.status(self.owner["id"], job)["content"]["summary"], "fixture")
            # Recreate the crash window between archive commit and worker acknowledgement.
            with storage.connect() as conn:
                conn.execute("UPDATE report_jobs SET state='running' WHERE id=?", (job,))
            self.assertTrue(queue.run_one())
            inference.assert_awaited_once()
        self.actor = self.other
        self.assertEqual(self.client.get("/api/report-jobs/" + job).status_code, 404)
        backup, restored = self.root / "backup", self.root / "restored"
        materialize(self.source, backup, restore=False)
        materialize(backup, restored, restore=True)
        original, = (restored / "original_store").glob("*.bin")
        self.assertEqual(original.read_bytes(), b"synthetic-fixture")
        self.assertEqual(expire_originals(restored, 1, True), 0)
        with patch("modules.report.assets.time.time", return_value=storage.now() + 3 * 86400):
            self.assertEqual(expire_originals(restored, 1, False), 1)
            self.assertTrue(original.is_file())
            self.assertEqual(expire_originals(restored, 1, True), 1)
        self.assertFalse(original.exists())
        (backup / "original_store" / original.name).write_bytes(b"corrupted fixture")
        with self.assertRaises(ValueError):
            materialize(backup, self.root / "bad", restore=True)
        self.assertFalse((self.root / "bad").exists())

    def test_interrupted_unarchived_job_reaches_terminal_failure(self):
        job = self.post_job().json()["id"]
        with storage.connect() as conn:
            conn.execute("UPDATE report_jobs SET state='running'")
        self.assertTrue(queue.run_one())
        result = self.client.get("/api/report-jobs/" + job).json()
        self.assertEqual(result["state"], "failed")
        self.assertIn("配置", result["error"])
        self.assertFalse(queue.run_one())

    def test_endpoint_policy_pause_and_operations(self):
        site = Site(organization="Demo", receiving_unit="Fixture", emergency_contact="Fixture", daily_capacity=1,
                    members={"nurse": "capture"}, allowed_llm_endpoints=["https://fixture.invalid/v1"])
        configure(site)
        with storage.connect() as conn:
            check_endpoint(conn, self.owner["id"], "https://fixture.invalid/v1/")
            with self.assertRaises(ApplicationError):
                check_endpoint(conn, self.owner["id"], "https://other.invalid/v1")
        first = self.post_job()
        self.assertEqual(first.status_code, 202)
        configure(site.model_copy(update={"analysis_paused": True}))
        self.assertEqual(self.post_job("fixture-job-2").status_code, 409)
        self.assertTrue(queue.run_one())
        self.assertIn("暂停", queue.status(self.owner["id"], first.json()["id"])["error"])
        stats = summarize("Demo", 0, storage.now() + 1)
        self.assertEqual(stats["jobs"], {"failed": 1})
        self.assertIsNotNone(stats["queue_wait_p95_seconds"])
        self.assertIsNone(stats["cost_per_signature"])

    def test_shared_workflow_and_revocation(self):
        site = Site(organization="Demo", receiving_unit="合成接收科", emergency_contact="合成值班席",
                    daily_capacity=5, members={"nurse": "capture", "reader": "reader"})
        configure(site)
        response = self.client.post("/api/screening/cases", json={"idempotency_key": "fixture-case", "examination": examination()})
        case = response.json()
        url = "/api/screening/cases/" + case["id"]
        review = {"action": "review", "expected_revision": 1, "idempotency_key": "fixture-review",
                  "original_images_checked": True, "case_checked": True, "comment": "fixture review"}
        self.assertEqual(self.client.post(url + "/commands", json=review).status_code, 403)
        self.actor = self.reader
        self.assertEqual(len(repository.list_cases(self.reader["id"])), 1)
        self.assertEqual(self.client.post(url + "/commands", json=review).status_code, 200)
        signed = self.client.post(url + "/commands", json={"action": "sign", "expected_revision": 2,
            "plan": "synthetic plan", "idempotency_key": "fixture-sign"}).json()
        self.assertEqual(signed["signature"]["actor_id"], self.reader["id"])
        revoked = self.client.post(url + "/commands", json={"action": "revoke", "expected_revision": 3,
            "reason": "fixture correction", "idempotency_key": "fixture-revoke"}).json()
        self.assertIsNone(revoked["signature"])
        self.assertEqual(self.client.get(url + "/context?revision=3").json()["signed_plan"], "synthetic plan")
        configure(site.model_copy(update={"members": {"nurse": "capture"}}))
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url + "/commands", json=review).status_code, 404)
        self.assertFalse(repository.list_cases(self.reader["id"]))
        self.actor = self.other
        self.assertEqual(self.client.get(url + "/export?revision=3").status_code, 404)
