"""模型网关与报告链路的错误语义回归。

两件事必须同时成立：
1. `complete()` 把模型故障抛成带排查提示的 `LLMUnavailable`；
2. 报告链路把它翻成用户能据此动手的提示，而不是队列兜底的「请联系管理员」。
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.exceptions import ApplicationError
from core.llm.client import LLMClient, LLMUnavailable
from modules.agent.tools.text_revision import content_len
from modules.report import service


class _BindingClient:
    """替身：记录 bind 参数并可让 invoke 抛错。"""

    def __init__(self, error=None, reply='Reply', sent=None):
        self.error = error
        self.reply = reply
        self.sent = sent if sent is not None else []
        self.bound = {}

    def bind(self, **kwargs):
        self.bound.update(kwargs)
        return self

    def invoke(self, payload):
        if self.error is not None:
            raise self.error
        self.sent.append(payload)
        from types import SimpleNamespace
        return SimpleNamespace(content=self.reply)


class LLMGatewayTests(unittest.TestCase):
    def test_complete_raises_readable_unavailable(self):
        failing = _BindingClient(error=RuntimeError('401 invalid_api_key'))
        with patch.object(LLMClient, '_build_client', return_value=failing):
            with self.assertRaises(LLMUnavailable) as caught:
                LLMClient(api_key='test').complete('核查这段正文')
        self.assertIn('鉴权失败', str(caught.exception))
        self.assertNotIn('Connection error', str(caught.exception))

    def test_chat_with_gpt_keeps_error_string_contract(self):
        failing = _BindingClient(error=RuntimeError('402 insufficient balance'))
        with patch.object(LLMClient, '_build_client', return_value=failing):
            reply = LLMClient(api_key='test').chat_with_gpt('写报告')
        self.assertTrue(reply.startswith('Error:'))
        self.assertIn('余额不足', reply)

    def test_complete_sends_system_then_prompt(self):
        client = _BindingClient(reply='ok')
        with patch.object(LLMClient, '_build_client', return_value=client):
            LLMClient(api_key='test').complete('正文', system='校对员', temperature=0.0)
        roles = [type(message).__name__ for message in client.sent[-1]]
        self.assertEqual(roles, ['SystemMessage', 'HumanMessage'])
        self.assertEqual(client.bound.get('temperature'), 0.0)

    def test_empty_reply_is_not_treated_as_content(self):
        client = _BindingClient(reply='   ')
        with patch.object(LLMClient, '_build_client', return_value=client):
            reply = LLMClient(api_key='test').complete('正文')
        self.assertEqual(content_len(reply), 0)


class _FailingGenerator:
    """两条报告流程都要把故障翻成可操作提示，所以两个入口都实现。"""

    def __init__(self, error):
        self.error = error
        self.calls = 0

    def generate(self, *args, **kwargs):
        self.calls += 1
        raise self.error

    def generate_v2(self, *args, **kwargs):
        return self.generate(*args, **kwargs)


class PipelineErrorMappingTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, error):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ApplicationError) as caught:
                await service._run_report_pipeline(
                    _FailingGenerator(error), b'image', 'note', Path(folder))
        return caught.exception

    async def test_model_failure_becomes_actionable_503(self):
        failure = await self._run(LLMUnavailable('鉴权失败：检查 API Key 是否正确、是否已过期。'))
        self.assertEqual(failure.status_code, 503)
        self.assertIn('模型服务不可用', failure.detail)
        self.assertIn('鉴权失败', failure.detail)
        self.assertNotIn('联系管理员', failure.detail)

    async def test_agent_protocol_failure_keeps_its_reason(self):
        failure = await self._run(
            RuntimeError('Agent Glaucoma Specialist failed: Error: timeout'))
        self.assertEqual(failure.status_code, 502)
        self.assertIn('报告生成中断', failure.detail)
        self.assertIn('timeout', failure.detail)
        self.assertNotIn('联系管理员', failure.detail)

    async def test_bad_citation_structure_is_not_a_business_error(self):
        failure = await self._run(ValueError('Malformed agent tool response'))
        self.assertEqual(failure.status_code, 502)
        self.assertIn('Malformed agent tool response', failure.detail)


if __name__ == '__main__':
    unittest.main()
