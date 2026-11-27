"""专科成稿的契约：一次调用、证据全文入提示词、不再有工具循环。

工具循环（模型先 search/read 再成稿）已移除：证据全文本来就整块拼在提示词里，
循环只是多花 1-3 次模型调用。这里的测试锁定新的调用次数与提示词内容，
防止有人"顺手"把循环加回来。
"""
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.agent.models import SpecialistRole
from modules.agent.specialist import SpecialistAgent, build_specialist_prompt
from modules.agent.tools.evidence import EvidenceTools


class SpecialistAgentTests(unittest.TestCase):
    def setUp(self):
        self.evidence = [{'id': 'a', 'title': 'Guide', 'section': 'test',
                          'source': 'fixture', 'text': 'optic disc evidence', 'index': 1}]

    def test_single_call_keeps_full_evidence_in_prompt(self):
        llm = Mock(return_value='Analysis [1]')
        agent = SpecialistAgent(SpecialistRole('Eye', 'Review the case.'), llm)
        self.assertEqual(agent.execute('case', self.evidence, {'a': 1}), 'Analysis [1]')
        self.assertEqual(llm.call_count, 1)
        prompt = llm.call_args.args[0]
        self.assertIn('optic disc evidence', prompt)
        self.assertIn('Review the case.', prompt)
        self.assertEqual(llm.call_args.kwargs, {'reset': True})

    def test_tool_protocol_is_gone_from_the_prompt(self):
        prompt = build_specialist_prompt('case', 'Eye', 'Review.', self.evidence, {'a': 1})
        self.assertNotIn('search_evidence', prompt)
        self.assertNotIn('read_evidence', prompt)

    def test_final_report_prompt_keeps_reader_requirements(self):
        prompt = build_specialist_prompt(
            'case', 'Eye', 'Review.', self.evidence, {'a': 1}, final_report=True)
        self.assertIn('Write the final report for the reader', prompt)
        self.assertIn('Final report requirements', prompt)

    def test_evidence_gap_is_stated_when_nothing_was_retrieved(self):
        prompt = build_specialist_prompt('case', 'Eye', 'Review.', [], {})
        self.assertIn('No reference was retrieved for this disease', prompt)

    def test_unsupported_action_is_rejected_instead_of_retried(self):
        llm = Mock(return_value='{"action":"read_evidence","id":"a"}')
        with self.assertRaises(ValueError):
            SpecialistAgent(SpecialistRole('Eye', 'Review the case.'), llm).execute(
                'case', self.evidence, {'a': 1})
        self.assertEqual(llm.call_count, 1)

    def test_invalid_citation_and_access(self):
        tools = EvidenceTools(self.evidence, {'a': 1})
        with self.assertRaises(ValueError):
            tools.validate_citations('Invented [99]')
        with self.assertRaises(ValueError):
            tools.validate_citations('Mixed [1,2] markers')


if __name__ == '__main__':
    unittest.main()
