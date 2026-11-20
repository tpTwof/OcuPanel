import sys
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from main import app
from utils.auth import current_user
from utils.errors import ApplicationError
from report.models import ReportSubmission, ReportDownload
from knowledge.retrieval import Retriever
import tempfile

class RouteTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app)
        self.user={'id':'test','username':'tester','display_name':'Tester'}
        app.dependency_overrides[current_user]=lambda:self.user
        self.addCleanup(app.dependency_overrides.clear)

    def test_report_multipart_binds_typed_request(self):
        result={'summary':'text','cup_to_disc_ratio':None,'img_name':'','evidence':[], 'verification':{'status':'pass'},'rejected':False,'report_id':'r'}
        with patch('report.service.generate_content',new_callable=AsyncMock,return_value=result) as service:
            response=self.client.post('/api/generate-report-content/',files={'file':('eye.png',b'bytes','image/png')},data={'note':'Clinical note','conversation_id':'c'})
            self.assertEqual(response.status_code,200,response.text)
            user,request=service.call_args.args
            self.assertEqual(user,self.user)
            self.assertIsInstance(request,ReportSubmission)
            self.assertEqual(request.image_bytes,b'bytes')
            self.assertEqual(request.note,'Clinical note')
            self.assertEqual(request.conversation_id,'c')
            self.assertEqual(request.diseases, ('glaucoma',))

            diseases = ['diabetic_retinopathy', 'age_related_macular_degeneration']
            response = self.client.post('/api/generate-report-content/',
                files={'file': ('eye.png', b'bytes', 'image/png')}, data={'diseases': diseases})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(service.call_args.args[1].diseases, tuple(diseases))

            service.reset_mock()
            response = self.client.post('/api/generate-report-content/',
                files={'file': ('eye.png', b'bytes', 'image/png')}, data={'diseases': ['unsupported']})
            self.assertEqual(response.status_code, 422, response.text)
            service.assert_not_called()

    def test_upload_required_and_error_mapping(self):
        self.assertEqual(self.client.post('/api/generate-report-content/').status_code,422)
        with patch('report.service.generate_content',new_callable=AsyncMock,side_effect=ApplicationError(409,'Configuration missing')):
            response=self.client.post('/api/generate-report-content/',files={'file':('eye.png',b'bytes','image/png')})
            self.assertEqual(response.status_code,409)
            self.assertEqual(response.json(),{'detail':'Configuration missing'})

    def test_pdf_response_cleans_up_after_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            job = Path(folder) / "job"
            job.mkdir()
            pdf = job / "report.pdf"
            pdf.write_bytes(b"%PDF-test")
            with patch('report.service.generate_report', new_callable=AsyncMock,
                       return_value=ReportDownload(pdf, job)):
                response = self.client.post('/api/generate-report/',
                    files={'file': ('eye.png', b'bytes', 'image/png')},
                    data={'diseases': ['diabetic_retinopathy']})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, b"%PDF-test")
                self.assertFalse(job.exists())

    def test_export_uses_saved_report_and_checks_ownership(self):
        from report.pdf import PDFRenderer
        from utils import storage

        with tempfile.TemporaryDirectory() as directory, patch.object(storage, "DB_PATH", Path(directory) / "test.db"):
            storage.init_db()
            owner = storage.create_user("owner", "example-password")
            report_id = storage.save_report(owner["id"], None, "", "Saved report", {"status": "rewritten"}, [], False)
            rejected_id = storage.save_report(owner["id"], None, "", "Rejected", {}, [], True)
            with storage.connect() as connection:
                connection.execute("ALTER TABLE reports DROP COLUMN visual_findings")
            storage.init_db()
            self.assertEqual(storage.get_report(owner["id"], report_id)["visual_findings"], {})
            findings = {"diabetic_retinopathy": {
                "prompt_similarity_margin": -2.5, "model_sources": {"image_text_model": "FLAIR@test"},
            }}
            new_id = storage.save_report(
                owner["id"], None, "", "Case interpretation", {"status": "pass"},
                [], False, visual_findings=findings,
            )
            path = f"/api/reports/{report_id}/pdf"
            self.assertEqual(self.client.get(path).status_code, 404)
            app.dependency_overrides[current_user] = lambda: owner
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertTrue(response.content.startswith(b"%PDF"))
            self.assertEqual(self.client.get(f"/api/reports/{rejected_id}/pdf").status_code, 422)
            self.assertEqual(storage.get_report(owner["id"], new_id)["visual_findings"], findings)
            with patch.object(PDFRenderer, "generate_pdf_report",
                              side_effect=PDFRenderer().generate_pdf_report) as render:
                response = self.client.get(f"/api/reports/{new_id}/pdf")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(render.call_args.kwargs["synthesis_text"], "Case interpretation")
            self.assertIn("-2.500", render.call_args.kwargs["visual_findings_text"])
            self.assertIn("FLAIR@test", render.call_args.kwargs["visual_findings_text"])

    def test_direct_pdf_archives_overlay_for_owner_and_history(self):
        from PIL import Image
        from report.models import ReportResult
        from utils import storage

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            overlay = folder / "segmented.png"
            Image.new("RGB", (64, 64), "green").save(overlay)
            result = ReportResult("Findings", {"status": "pass"}, .5, str(overlay), [])
            with patch.object(storage, "DB_PATH", folder / "test.db"), \
                 patch("report.service.IMG_STORE_DIR", folder), \
                 patch("report.service._load_generator", new_callable=AsyncMock), \
                 patch("report.service._run_report_pipeline", new_callable=AsyncMock, return_value=result) as pipeline:
                storage.init_db()
                owner = storage.create_user("owner", "example-password")
                app.dependency_overrides[current_user] = lambda: owner
                response = self.client.post("/api/generate-report/", files={"file": ("eye.png", b"test")})
                self.assertEqual(response.status_code, 200)
                report, = storage.list_reports(owner["id"])
                image_url = f"/api/get-report-image/{report['img_name']}"
                image = self.client.get(image_url)
                self.assertEqual(image.status_code, 200)
                self.assertEqual(image.headers["cache-control"], "no-store")
                pdf = self.client.get(f"/api/reports/{report['id']}/pdf")
                self.assertEqual(pdf.status_code, 200)
                self.assertIn(b"/Subtype /Image", pdf.content)
                pipeline.assert_awaited_once()
                app.dependency_overrides[current_user] = lambda: self.user
                self.assertEqual(self.client.get(image_url).status_code, 404)
                app.dependency_overrides[current_user] = lambda: owner
                (folder / f"{report['img_name']}.jpg").unlink()
                self.assertEqual(self.client.get(image_url).status_code, 404)

    def test_pdf_requires_saved_verification_on_both_routes(self):
        from report.models import ReportResult
        from utils import storage

        with tempfile.TemporaryDirectory() as directory, patch.object(storage, "DB_PATH", Path(directory) / "db"):
            storage.init_db()
            owner = storage.create_user("owner", "example-password")
            app.dependency_overrides[current_user] = lambda: owner
            for verification in ({"status": "disabled"}, {}):
                result = ReportResult("Research draft", verification, None, "", [])
                with self.subTest(verification=verification), \
                     patch("report.service._load_generator", new_callable=AsyncMock), \
                     patch("report.service._run_report_pipeline", new_callable=AsyncMock, return_value=result):
                    response = self.client.post("/api/generate-report/", files={"file": ("eye.png", b"test")})
                    self.assertEqual(response.status_code, 422)
                    report = storage.list_reports(owner["id"])[0]
                    self.assertEqual(self.client.get(f"/api/reports/{report['id']}/pdf").status_code, 422)

    def test_user_request_model_and_authentication(self):
        self.assertEqual(self.client.post('/api/account/register',json={'username':'a','password':'1'}).status_code,422)
        app.dependency_overrides.clear()
        self.assertEqual(self.client.get('/api/account/me').status_code,401)

    def test_unusable_image_prompts_retake_on_both_report_routes(self):
        from io import BytesIO
        from PIL import Image
        from report.generation import MedicalReportGenerator

        image = BytesIO()
        Image.new("RGB", (64, 64)).save(image, format="PNG")
        generator = MedicalReportGenerator(api_key="test")
        with patch("report.service._load_generator", new_callable=AsyncMock, return_value=generator), \
             patch("vision.diseases.retinal.analyze_retinal") as model, \
             patch.object(generator, "chat_with_gpt") as llm:
            for path in ("/api/generate-report-content/", "/api/generate-report/"):
                with self.subTest(path=path):
                    response = self.client.post(path, files={"file": ("eye.png", image.getvalue(), "image/png")},
                                                data={"diseases": "diabetic_retinopathy"})
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertIn("图像不可判读", response.json()["detail"])
                    response = self.client.post(
                        path, files={"file": ("eye.png", b"not an image", "image/png")},
                    )
                    self.assertEqual(response.status_code, 400, response.text)
            model.assert_not_called()
            llm.assert_not_called()

    def test_ophthalmic_message_returns_and_saves_evidence_with_either_retriever(self):
        from contextlib import ExitStack

        cases = (
            (True, "英国医院眼科发现硬性渗出", "nice-ng242-1.6.11", "1.6.11", "graph"),
            (False, "年龄相关性黄斑变性 AMD 直线变弯 检查", "nei-amd-symptoms-and-exam", "美国国家眼科研究所", "text"),
            (True, "英国停车收费是否有优惠？", None, None, "empty"),
        )
        for graph_enabled, question, evidence_id, source_text, retrieval_result in cases:
            with self.subTest(question=question), ExitStack() as stack:
                stack.enter_context(patch("utils.config.GRAPH_RAG_ENABLED", graph_enabled))
                stack.enter_context(patch("utils.config.RAG_ENABLED", True))
                stack.enter_context(patch("utils.config.VERIFY_ENABLED", True))
                retriever = Retriever.from_corpus(mode="bm25")
                stack.enter_context(patch("knowledge.service.get_retriever", return_value=retriever))
                stack.enter_context(patch("chat.service.storage.get_conversation",
                                          return_value={"title": "Case", "mode": "ophthalmic"}))
                stack.enter_context(patch("chat.service.storage.load_llm_config",
                                          return_value={"api_key": "test", "model": "test", "base_url": ""}))
                stack.enter_context(patch("chat.service.storage.list_messages", return_value=[]))
                save = stack.enter_context(patch("chat.service.storage.add_message", return_value={"id": "m"}))
                llm = stack.enter_context(patch("chat.service.LLMClient")).return_value
                llm.chat_with_history.return_value = "可参考眼科检查 [1]"
                llm.chat_with_gpt.return_value = '{"claims": []}'

                response = self.client.post("/api/chat/conversations/c/messages", json={"message": question})

                self.assertEqual(response.status_code, 200, response.text)
                data = response.json()
                self.assertEqual(data["retrieval"], {
                    "result": retrieval_result, "graph": "ready" if graph_enabled else "disabled",
                })
                if evidence_id:
                    expected = next(item for item in data["evidence"] if item["id"] == evidence_id)
                    self.assertEqual(len(expected.get("graph_path") or []), 2 if graph_enabled else 0)
                    self.assertIn(source_text, llm.chat_with_history.call_args.kwargs["system"])
                    self.assertEqual(data["verification"]["status"], "pass")
                else:
                    self.assertNotIn("evidence", data)
                    self.assertEqual(data["verification"]["status"], "rejected")
                    self.assertNotIn("[1]", data["reply"])
                self.assertEqual(save.call_args.args[-1], {
                    key: data[key] for key in ("retrieval", "verification", "evidence") if key in data
                })

if __name__=='__main__':unittest.main()
