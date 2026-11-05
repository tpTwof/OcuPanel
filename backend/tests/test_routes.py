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
                    files={'file': ('eye.png', b'bytes', 'image/png')})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, b"%PDF-test")
                self.assertFalse(job.exists())

    def test_user_request_model_and_authentication(self):
        self.assertEqual(self.client.post('/api/account/register',json={'username':'a','password':'1'}).status_code,422)
        app.dependency_overrides.clear()
        self.assertEqual(self.client.get('/api/account/me').status_code,401)

if __name__=='__main__':unittest.main()
