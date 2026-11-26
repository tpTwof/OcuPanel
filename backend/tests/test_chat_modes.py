import asyncio
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import storage
from modules.chat import service
from modules.chat.schemas import SendMessageRequest, ChangeModeRequest
from modules.chat.prompts import CHAT_SYSTEM_PROMPT
from core.llm.client import LLMClient
from core.errors import ApplicationError

class ConversationModeStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = patch('core.storage.DB_PATH', Path(self.temp.name) / 'test.db')
        override.start()
        self.addCleanup(override.stop)

    def add_user(self, user_id):
        with storage.connect() as conn:
            conn.execute('INSERT INTO users VALUES (?,?,?,?,?)', (user_id, user_id, 'hash', user_id, 1))

    def test_default_persistence_and_isolation(self):
        storage.init_db()
        self.add_user('u1')
        self.add_user('u2')
        conv = storage.create_conversation('u1')
        self.assertEqual(conv['mode'], 'general')
        self.assertFalse(storage.set_conversation_mode('u2', conv['id'], 'ophthalmic'))
        self.assertTrue(storage.set_conversation_mode('u1', conv['id'], 'ophthalmic'))
        storage.init_db()
        self.assertEqual(storage.get_conversation('u1', conv['id'])['mode'], 'ophthalmic')
        self.assertEqual(storage.list_conversations('u1')[0]['mode'], 'ophthalmic')
        self.assertEqual(storage.list_conversations('u2'), [])

    def test_graph_preference_is_scoped_to_conversation_and_owner(self):
        storage.init_db()
        self.add_user('u1')
        self.add_user('u2')
        first = storage.create_conversation('u1', graph_enabled=True)
        second = storage.create_conversation('u1')
        self.assertFalse(storage.set_graph_enabled('u2', first['id'], False))
        self.assertTrue(storage.get_conversation('u1', first['id'])['graph_enabled'])
        self.assertTrue(storage.set_graph_enabled('u1', first['id'], False))
        storage.init_db()
        self.assertFalse(storage.get_conversation('u1', first['id'])['graph_enabled'])
        self.assertIsNone(storage.get_conversation('u1', second['id'])['graph_enabled'])

    def test_old_database_migration_is_idempotent(self):
        legacy = storage.SCHEMA.replace(
            "    mode       TEXT NOT NULL DEFAULT 'general' CHECK (mode IN ('general', 'ophthalmic')),\n", ''
        )
        with storage.connect() as conn:
            conn.executescript(legacy)
            conn.execute('INSERT INTO users VALUES (?,?,?,?,?)', ('u', 'u', 'hash', 'u', 1))
            conn.execute('INSERT INTO conversations VALUES (?,?,?,?,?)', ('c', 'u', 'Case', 1, 1))
            conn.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?)', ('m', 'c', 'u', 'assistant', 'Report', json.dumps({'kind':'report'}), 1))
        storage.init_db()
        self.assertEqual(storage.get_conversation('u','c')['mode'], 'ophthalmic')
        storage.set_conversation_mode('u','c','general')
        storage.init_db()
        self.assertEqual(storage.get_conversation('u','c')['mode'], 'general')
        self.assertEqual(len(storage.list_messages('u','c')),1)

class ChatModeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_mode_controls_only_system_prompt(self):
        for mode in ('general','ophthalmic'):
            with self.subTest(mode=mode), patch('core.config_impl.RAG_ENABLED', False), patch('core.config_impl.VERIFY_ENABLED', False), patch('modules.knowledge.service.get_retriever') as get_retriever, patch('modules.chat.repository.get_conversation',return_value={'title':'Case','mode':mode}), patch('modules.chat.repository.load_llm_config',return_value={'api_key':'test','model':'test','base_url':''}), patch('modules.chat.repository.list_messages',return_value=[{'role':'user','content':'Analyze this'}, {'role':'assistant','content':'Saved report'}]), patch('modules.chat.repository.add_message',return_value={'id':'m'}), patch('modules.chat.service.LLMClient') as client:
                client.return_value.chat_with_history.return_value='Reply'
                result = await service.send_message({'id':'u'},'c',SendMessageRequest(message='Question'))
                self.assertEqual(result['reply'],'Reply')
                args,kwargs=client.return_value.chat_with_history.call_args
                self.assertEqual(args[0],[{'role':'user','content':'Analyze this'}, {'role':'assistant','content':'Saved report'}])
                self.assertEqual(kwargs['system'], CHAT_SYSTEM_PROMPT['content'] if mode=='ophthalmic' else None)
                get_retriever.assert_not_called()

    async def test_other_users_mode_is_not_changed(self):
        with patch('modules.chat.repository.set_conversation_mode',return_value=False):
            with self.assertRaises(ApplicationError) as caught:
                await service.change_mode({'id':'other'},'c',ChangeModeRequest(mode='ophthalmic'))
            self.assertEqual(caught.exception.status_code,404)

class TransportPromptTests(unittest.TestCase):
    def test_general_call_has_no_business_system_prompt(self):
        """普通聊天不注入业务系统提示词；传入 system 时才带在首条消息。"""
        sent = []

        class FakeRunnable:
            def invoke(self, payload):
                sent.append(payload)
                return SimpleNamespace(content='Reply')

        class FakeClient:
            def bind(self, **kwargs):
                return FakeRunnable()

        with patch.object(LLMClient, '_build_client', return_value=FakeClient()):
            client = LLMClient(api_key='test')
            client.chat_with_history([], 'Hello')
            self.assertEqual([getattr(m, 'content', m) for m in sent[-1]], ['Hello'])
            client.chat_with_history([], 'Question', system='Eye role')
            self.assertEqual(
                [getattr(m, 'content', m) for m in sent[-1]], ['Eye role', 'Question'])

class AnalysisConversationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        original_folder = tempfile.TemporaryDirectory()
        self.addCleanup(original_folder.cleanup)
        original_patch = patch('modules.report.assets.ORIGINAL_STORE_DIR', Path(original_folder.name))
        original_patch.start()
        self.addCleanup(original_patch.stop)

    async def test_failed_chat_archive_rolls_back_report_messages_and_overlay(self):
        from PIL import Image
        from modules.report import service as reports
        from modules.report.models import ReportSubmission, ReportResult

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with patch.object(storage, "DB_PATH", folder / "db"), patch.object(reports, "IMG_STORE_DIR", folder):
                storage.init_db()
                owner = storage.create_user("owner", "test-password")
                conv = storage.create_conversation(owner["id"])
                with storage.connect() as conn:
                    conn.execute("CREATE TRIGGER fail_reply BEFORE INSERT ON messages "
                                 "WHEN NEW.role='assistant' BEGIN SELECT RAISE(ABORT, 'write failed'); END")
                overlay = folder / "segmented.png"
                Image.new("RGB", (32, 32)).save(overlay)
                result = ReportResult("Case", {"status": "pass"}, .5, str(overlay), [])
                request = ReportSubmission(b"image", "eye.png", "", conv["id"])
                with patch.object(reports, "_load_generator", new_callable=AsyncMock), \
                     patch.object(reports, "_run_report_pipeline", new_callable=AsyncMock, return_value=result):
                    with self.assertRaises(sqlite3.IntegrityError):
                        await reports.generate_content(owner, request)
                self.assertEqual(storage.list_reports(owner["id"]), [])
                self.assertEqual(storage.list_messages(owner["id"], conv["id"]), [])
                self.assertEqual(list(folder.glob("*.jpg")), [])
                self.assertEqual(storage.get_conversation(owner["id"], conv["id"])["title"], "新对话")

    async def test_analysis_activates_mode_and_saves_case_and_reply(self):
        from modules.report import service as reports
        from modules.report.models import ReportSubmission, ReportResult
        with tempfile.TemporaryDirectory() as folder, patch('core.storage.DB_PATH', Path(folder) / 'db.sqlite'):
            storage.init_db()
            with storage.connect() as conn:
                conn.execute('INSERT INTO users VALUES (?,?,?,?,?)', ('u', 'u', 'hash', 'u', 1))
            conv = storage.create_conversation('u')
            findings = {'glaucoma': {'measurements': {'area_equivalent_cdr': .6}}}
            result = ReportResult('Analysis result', {'status':'pass'}, .6, '', [], findings)
            with patch('modules.report.service._load_generator', new_callable=AsyncMock), patch('modules.report.service._run_report_pipeline', new_callable=AsyncMock, return_value=result):
                response = await reports.generate_content(
                    {'id':'u'}, ReportSubmission(b'image', 'eye.png', 'Case note', conv['id']),
                )
            self.assertFalse(response['rejected'])
            self.assertEqual(storage.get_conversation('u', conv['id'])['mode'], 'ophthalmic')
            messages = storage.list_messages('u',conv['id'])
            self.assertEqual([m['role'] for m in messages], ['user','assistant'])
            self.assertIn('Case note', messages[0]['content'])
            self.assertEqual(messages[1]['content'],'Analysis result')
            self.assertEqual(response['visual_findings'], findings)
            self.assertIn('0.60', response['visual_findings_text'])
            self.assertEqual(messages[1]['meta']['visual_findings_text'], response['visual_findings_text'])

if __name__=='__main__': unittest.main()
