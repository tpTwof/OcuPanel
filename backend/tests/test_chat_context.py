import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chat.context import select_history
from chat import service
from chat.models import SendMessageRequest
from llm.client import LLMClient
from utils.errors import ApplicationError

class ContextWindowTests(unittest.TestCase):
    def select(self, history, current='Q', **overrides):
        options=dict(system=None, mode='general', max_messages=4, max_chars=1000, report_max_chars=100)
        options.update(overrides)
        return select_history(history,current,**options)

    def test_window_selects_recent_messages_without_changing_history(self):
        history=[{'role':'user' if i%2==0 else 'assistant','content':str(i)} for i in range(20)]
        original=copy.deepcopy(history)
        self.assertEqual([m['content'] for m in self.select(history)], ['16','17','18','19'])
        self.assertEqual(history,original)

    def test_total_character_budget_includes_system_and_current(self):
        history=[{'role':'user','content':'A'*10},{'role':'assistant','content':'B'*10}]
        selected=self.select(history,current='Q'*10,system='S'*10,max_chars=40)
        self.assertEqual(sum(len(m['content']) for m in selected)+20,40)
        with self.assertRaises(ValueError):self.select([],current='Q'*41,max_chars=40)

    def test_latest_report_retained_outside_window_and_marked_when_truncated(self):
        history=[{'role':'assistant','content':'Old report','meta':{'kind':'report'}}, {'role':'assistant','content':'REPORT '*100,'meta':{'kind':'report'}}]
        history += [{'role':'user' if i%2==0 else 'assistant','content':str(i)} for i in range(10)]
        selected=self.select(history,mode='ophthalmic',max_messages=3)
        self.assertIn('报告节选',selected[0]['content'])
        self.assertLessEqual(len(selected[0]['content']),100)
        self.assertEqual([m['content'] for m in selected[1:]],['8','9'])
        self.assertNotIn('Old report',[m['content'] for m in selected])

    def test_large_recent_message_does_not_skip_to_unrelated_old_messages(self):
        history=[{'role':'user','content':'old'}, {'role':'user','content':'X'*100}]
        self.assertEqual(self.select(history,max_chars=20),[])

    def test_chat_output_cap_passed_to_provider(self):
        with patch('llm.client.openai.OpenAI') as sdk, patch('utils.config.CHAT_MAX_OUTPUT_TOKENS',123):
            sdk.return_value.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='Reply'))])
            LLMClient(api_key='test').chat_with_history([], 'Question')
            self.assertEqual(sdk.return_value.chat.completions.create.call_args.kwargs['max_tokens'],123)

class ContextRejectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_oversized_question_is_not_saved_or_sent(self):
        with patch('chat.service.storage.get_conversation',return_value={'mode':'general','title':'Case'}), patch('chat.service.storage.load_llm_config',return_value={'api_key':'x','model':'x','base_url':''}), patch('chat.service.storage.list_messages',return_value=[]), patch('chat.service.storage.add_message') as save, patch('chat.service.LLMClient') as client, patch('utils.config.CHAT_CONTEXT_MAX_CHARS',5):
            with self.assertRaises(ApplicationError) as caught:
                await service.send_message({'id':'u'},'c',SendMessageRequest(message='x'*10))
            self.assertEqual(caught.exception.status_code,413)
            save.assert_not_called()
            client.return_value.chat_with_history.assert_not_called()

if __name__=='__main__':unittest.main()
