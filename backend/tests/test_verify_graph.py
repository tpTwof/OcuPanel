"""核查状态机（LangGraph）的边界回归。

`test_verifier.py` 证明分支语义与迁移前一致；这里补的是"图不会失控"：
轮数有界、整篇重生成最多一次、核查故障一定落到 error、且不靠框架的
recursion_limit 兜底（那只是保险丝，不是计数器）。
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.agent.graphs.verify import MAX_ISSUES_PER_ROUND, run_verification
from modules.agent.verifier import CitationVerifier

EVIDENCE = [{'index': 1, 'text': 'Evidence'}]
CORE_ISSUE = {'claims': [{
    'quote': '应每周复查 [1]。', 'citations': [1], 'verdict': 'unsupported',
    'impact': 'core', 'basis': 'recommendation', 'reason': '资料未给出该周期',
}]}
DRAFT = '左眼尚未见明确损害。\n应每周复查 [1]。'


class VerifyGraphBoundTests(unittest.TestCase):
    def test_rounds_are_bounded_by_max_rounds(self):
        """每轮 = 一次重写 + 一次复核，绝不因路由写错而多跑。"""
        llm = Mock(side_effect=[json.dumps(CORE_ISSUE)] * 40)
        with patch('core.config.VERIFY_SOFT_DELIVERY', False):
            text, record = CitationVerifier(llm).execute(DRAFT, EVIDENCE, max_rounds=8)
        self.assertIsNone(text)
        self.assertEqual(record['status'], 'rejected')
        # 首轮核查 1 次 + 每轮（重写 + 复核）2 次
        self.assertEqual(llm.call_count, 1 + 8 * 2)
        self.assertEqual(record['rounds'], 1 + 8)

    def test_regeneration_runs_at_most_once(self):
        llm = Mock(side_effect=[json.dumps(CORE_ISSUE)] * 40)
        regenerate = Mock(return_value='')  # 重生成失败也不能重试第二次
        with patch('core.config.VERIFY_SOFT_DELIVERY', False):
            text, record = CitationVerifier(llm).execute(
                DRAFT, EVIDENCE, max_rounds=2, regenerate=regenerate)
        self.assertIsNone(text)
        self.assertEqual(regenerate.call_count, 1)
        self.assertEqual(record['status'], 'rejected')

    def test_verify_failure_inside_graph_ends_in_error(self):
        # 首轮核查有问题 → 重写（无改动）→ 复核时模型故障 → 必须落到 error
        llm = Mock(side_effect=[
            json.dumps(CORE_ISSUE), '{"replacements": []}', 'Error: timeout',
        ])
        text, record = CitationVerifier(llm).execute(DRAFT, EVIDENCE, max_rounds=2)
        self.assertIsNone(text)
        self.assertEqual(record['status'], 'error')
        self.assertEqual(record['failure_kind'], 'llm_error')

    def test_clean_draft_never_enters_the_loop(self):
        llm = Mock(return_value='{"claims": []}')
        text, record = CitationVerifier(llm).execute('Case findings [1].', EVIDENCE)
        self.assertEqual(text, 'Case findings [1].')
        self.assertEqual(record['status'], 'pass')
        self.assertEqual(llm.call_count, 1)

    def test_max_issues_per_round_is_capped(self):
        self.assertEqual(MAX_ISSUES_PER_ROUND, 12)

    def test_graph_returns_the_same_contract_as_the_class_api(self):
        text, record = run_verification(
            CitationVerifier(Mock(return_value='{"claims": []}')), 'Case findings [1].', EVIDENCE)
        self.assertEqual(text, 'Case findings [1].')
        self.assertEqual(record['status'], 'pass')
        self.assertIn('review_log', record)


if __name__ == '__main__':
    unittest.main()
