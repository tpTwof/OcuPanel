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
from utils import storage
from chat import service
from chat.models import SendMessageRequest, ChangeModeRequest
from chat.prompts import CHAT_SYSTEM_PROMPT
from llm.client import LLMClient
from utils.errors import ApplicationError

class ConversationModeStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = patch('utils.storage.DB_PATH', Path(self.temp.name) / 'test.db')
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
            with self.subTest(mode=mode), patch('chat.service.storage.get_conversation',return_value={'title':'Case','mode':mode}), patch('chat.service.storage.load_llm_config',return_value={'api_key':'test','model':'test','base_url':''}), patch('chat.service.storage.list_messages',return_value=[{'role':'user','content':'Analyze this'}, {'role':'assistant','content':'Saved report'}]), patch('chat.service.storage.add_message',return_value={'id':'m'}), patch('chat.service.LLMClient') as client:
                client.return_value.chat_with_history.return_value='Reply'
                result = await service.send_message({'id':'u'},'c',SendMessageRequest(message='Question'))
                self.assertEqual(result['reply'],'Reply')
                args,kwargs=client.return_value.chat_with_history.call_args
                self.assertEqual(args[0],[{'role':'user','content':'Analyze this'}, {'role':'assistant','content':'Saved report'}])
                self.assertEqual(kwargs['system'], CHAT_SYSTEM_PROMPT['content'] if mode=='ophthalmic' else None)

    async def test_other_users_mode_is_not_changed(self):
        with patch('chat.service.storage.set_conversation_mode',return_value=False):
            with self.assertRaises(ApplicationError) as caught:
                await service.change_mode({'id':'other'},'c',ChangeModeRequest(mode='ophthalmic'))
            self.assertEqual(caught.exception.status_code,404)

class TransportPromptTests(unittest.TestCase):
    def test_general_call_has_no_business_system_prompt(self):
        with patch('llm.client.openai.OpenAI') as sdk:
            sdk.return_value.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='Reply'))])
            client=LLMClient(api_key='test')
            client.chat_with_history([], 'Hello')
            messages=sdk.return_value.chat.completions.create.call_args.kwargs['messages']
            self.assertEqual(messages,[{'role':'user','content':'Hello'}])
            client.chat_with_history([], 'Question', system='Eye role')
            self.assertEqual(sdk.return_value.chat.completions.create.call_args.kwargs['messages'][0], {'role':'system','content':'Eye role'})

class AnalysisConversationTests(unittest.IsolatedAsyncioTestCase):
    async def test_analysis_activates_mode_and_saves_case_and_reply(self):
        from report import service as reports
        from report.models import ReportSubmission, ReportResult
        with tempfile.TemporaryDirectory() as folder, patch('utils.storage.DB_PATH', Path(folder) / 'db.sqlite'):
            storage.init_db()
            with storage.connect() as conn:
                conn.execute('INSERT INTO users VALUES (?,?,?,?,?)', ('u', 'u', 'hash', 'u', 1))
            conv = storage.create_conversation('u')
            result = ReportResult('Analysis result', {'status':'pass'}, .6, '', [])
            with patch('report.service._load_generator', new_callable=AsyncMock), patch('report.service._run_report_pipeline', new_callable=AsyncMock, return_value=result), patch('report.service.imageio.imread', return_value=[]):
                response = await reports.generate_content(
                    {'id':'u'}, ReportSubmission(b'image', 'eye.png', 'Case note', conv['id']),
                )
            self.assertFalse(response['rejected'])
            self.assertEqual(storage.get_conversation('u', conv['id'])['mode'], 'ophthalmic')
            messages = storage.list_messages('u',conv['id'])
            self.assertEqual([m['role'] for m in messages], ['user','assistant'])
            self.assertIn('Case note', messages[0]['content'])
            self.assertEqual(messages[1]['content'],'Analysis result')

if __name__=='__main__': unittest.main()
