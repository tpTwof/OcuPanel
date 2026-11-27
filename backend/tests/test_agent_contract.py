"""引用核查返回契约的回归测试。

核查记录会被前端结果条、PDF 校验记录和数据库存档同时消费；迁移到 LangGraph
后状态在节点间流转，最容易出的问题是"图里多出/少了某个键"。这里按终态固定
断言，作为迁移的验收标准。
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.agent.contracts import (
    BASE_FIELDS,
    DELIVERED_FIELDS,
    ERROR_FIELDS,
    FIELDS,
    REJECTED_FIELDS,
)
from modules.agent.verifier import CitationVerifier

EVIDENCE = [{'index': 1, 'text': 'Evidence'}]


class VerificationContractTests(unittest.TestCase):
    def assertKnownKeys(self, record):
        unknown = set(record) - FIELDS
        self.assertFalse(unknown, f'verification 里出现了未登记的键：{sorted(unknown)}')

    def test_pass_record_carries_base_and_delivery_fields(self):
        text, record = CitationVerifier(Mock(return_value='{"claims":[]}')).execute(
            'Case findings [1].', EVIDENCE)
        self.assertEqual(record['status'], 'pass')
        self.assertKnownKeys(record)
        self.assertLessEqual(BASE_FIELDS, set(record))
        self.assertLessEqual(DELIVERED_FIELDS, set(record))
        self.assertEqual(text, 'Case findings [1].')
        self.assertEqual(record['review_log'][0]['issue_count'], 0)

    def test_rejected_record_reports_a_reason(self):
        # 整句无依据的处置建议必须补依据，不能靠标注降级交付。
        issue = {'claims': [{'quote': '应每周复查 [1]。', 'citations': [1],
                             'verdict': 'unsupported', 'impact': 'core',
                             'basis': 'recommendation'}]}
        text, record = CitationVerifier(Mock(return_value=json.dumps(issue))).execute(
            '左眼尚未见明确损害。\n应每周复查 [1]。', EVIDENCE, max_rounds=0)
        self.assertIsNone(text)
        self.assertEqual(record['status'], 'rejected')
        self.assertKnownKeys(record)
        self.assertLessEqual(REJECTED_FIELDS, set(record))
        self.assertTrue(record['remaining_issues'])

    def test_error_record_carries_failure_kind(self):
        text, record = CitationVerifier(Mock(return_value='Error: timeout')).execute(
            'Case findings [1].', EVIDENCE)
        self.assertIsNone(text)
        self.assertEqual(record['status'], 'error')
        self.assertKnownKeys(record)
        self.assertLessEqual(ERROR_FIELDS, set(record))
        self.assertEqual(record['failure_kind'], 'llm_error')

    def test_no_evidence_short_form_stays_within_contract(self):
        record = CitationVerifier.no_evidence_result()
        self.assertKnownKeys(record)
        self.assertEqual(record['status'], 'rejected')
        self.assertLessEqual(REJECTED_FIELDS, set(record))

    def test_missing_evidence_refuses_instead_of_passing(self):
        text, record = CitationVerifier(Mock(return_value='{"claims":[]}')).execute(
            'Case findings.', [])
        self.assertIsNone(text)
        self.assertEqual(record['status'], 'rejected')
        self.assertEqual(record['reason'], 'no_evidence')


if __name__ == '__main__':
    unittest.main()
