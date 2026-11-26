"""正向来源对照的确定性检查，不以假模型结果证明临床准确度。"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.agent.tools.grounding import parse_grounding, report_statements, SOFTWARE_BOUNDARY
from modules.agent.verifier import CitationVerifier


class GroundingTests(unittest.TestCase):
    evidence = [{'index': 1, 'id': 'guide', 'text': 'A reference clause supports an explanation.'}]
    quote = 'Explanation [1].'

    def entry(self):
        return {'quote': self.quote, 'basis': 'medical_knowledge', 'citations': [1],
                'sources': [{'kind': 'evidence', 'index': 1, 'quote': self.evidence[0]['text']}]}

    def test_accepted_clause_keeps_exact_support_excerpt(self):
        reply = {'claims': [], 'grounding': [self.entry()]}
        text, record = CitationVerifier(Mock(return_value=json.dumps(reply)), require_grounding=True).execute(
            self.quote, self.evidence)
        self.assertEqual(text, self.quote)
        self.assertEqual(record['grounding'][0]['sources'][0]['quote'], self.evidence[0]['text'])

    def test_statement_id_resolves_original_text_without_model_recopying_it(self):
        entry = dict(self.entry(), statement_id='R1', quote='A paraphrase, not the report text.')
        parsed = parse_grounding({'grounding': [entry]}, self.quote, self.evidence, '', required=True)
        self.assertEqual(parsed[0]['quote'], self.quote)
        self.assertEqual(parsed[0]['quote_resolution'], 'statement_id')

    def test_case_and_policy_sources_can_reference_actual_snapshots(self):
        quote = 'The model cannot diagnose.'
        entry = {'quote': quote, 'basis': 'software_limit', 'citations': [], 'sources': [{'kind': 'policy'}]}
        parsed = parse_grounding({'grounding': [entry]}, quote, [], '', required=True)
        self.assertEqual(parsed[0]['sources'][0]['quote'], SOFTWARE_BOUNDARY)
        self.assertEqual(parsed[0]['sources'][0]['excerpt_kind'], 'source_snapshot')

    def test_case_measurement_and_general_advice_have_separate_statement_ids(self):
        parts = report_statements('左眼眼压为 24 mmHg，RNFL 正常。后续安排由接诊医生决定。')
        self.assertEqual([item['text'] for item in parts], [
            '左眼眼压为 24 mmHg，', 'RNFL 正常。', '后续安排由接诊医生决定。',
        ])

    def test_statement_id_accepts_literal_fragment_inside_cross_clause_bold(self):
        text = '**模型概率来自右眼照片，不等同诊断。**'
        entry = {'statement_id': 'R1', 'basis': 'case_fact', 'citations': [],
                 'sources': [{'kind': 'case', 'quote': '模型概率来自右眼照片'}]}
        parsed = parse_grounding({'grounding': [entry]}, text, [], '模型概率来自右眼照片', required=True)
        self.assertEqual(parsed[0]['quote'], '**模型概率来自右眼照片，')

    def test_citation_number_alone_is_not_enough_to_pass(self):
        entry = self.entry()
        entry['sources'][0]['quote'] = 'Invented source text'
        llm = Mock(return_value=json.dumps({'claims': [], 'grounding': [entry]}))
        text, record = CitationVerifier(llm, require_grounding=True).execute(self.quote, self.evidence, max_rounds=0)
        self.assertIsNone(text)
        self.assertEqual(record['status'], 'rejected')
        self.assertEqual(record['remaining_issues'][0]['origin'], 'source_audit')
        self.assertEqual(llm.call_count, 1)

    def test_each_cited_clause_needs_its_own_source_link(self):
        """grounding 只覆盖一句时，另一句引用仍不能通过。

        以往这种情况让整次核查失败（invalid_claims）；现在改成把它当作
        「缺出处」的问题处理，但结论不变——仍然不交付正文。
        """
        reply = {'claims': [], 'grounding': [self.entry()]}
        text, record = CitationVerifier(Mock(return_value=json.dumps(reply)), require_grounding=True).execute(
            self.quote + '\nA different assertion [1].', self.evidence, max_rounds=0)
        self.assertIsNone(text)
        self.assertNotEqual(record['status'], 'pass')

    def test_inference_requires_case_and_external_support(self):
        entry = dict(self.entry(), basis='case_inference')
        with self.assertRaises(ValueError):
            parse_grounding({'grounding': [entry]}, self.quote, self.evidence, '', required=True)
        parsed = parse_grounding({'grounding': [entry]}, self.quote, self.evidence, 'Case fact.', required=True)
        self.assertEqual(parsed[0]['basis'], 'case_inference')
        self.assertEqual(parsed[0]['sources'][-1]['quote'], 'Case fact.')
        self.assertEqual(parsed[0]['sources'][-1]['excerpt_kind'], 'source_snapshot')

    def test_general_advice_cannot_carry_fake_evidence_support(self):
        entry = dict(self.entry(), basis='general_advice')
        with self.assertRaises(ValueError):
            parse_grounding({'grounding': [entry]}, self.quote, self.evidence, '', required=True)

    def test_list_number_is_not_a_treatment_quantity(self):
        quote = '1. 后续安排交由接诊医生决定。'
        entry = {'quote': quote, 'basis': 'general_advice', 'citations': [], 'sources': []}
        self.assertEqual(parse_grounding({'grounding': [entry]}, quote, [], '', required=True)[0]['basis'], 'general_advice')

    def test_scope_statement_can_trace_original_scope_metadata(self):
        evidence = [{**self.evidence[0], 'scope': '英国慢性开角型青光眼诊断'}]
        entry = {'quote': '该资料适用于英国诊断场景 [1]。', 'basis': 'scope_limit', 'citations': [1],
                 'sources': [{'kind': 'evidence', 'index': 1, 'quote': evidence[0]['scope']}]}
        parsed = parse_grounding({'grounding': [entry]}, entry['quote'], evidence, '', required=True)
        self.assertEqual(parsed[0]['sources'][0]['quote'], evidence[0]['scope'])
        with self.assertRaises(ValueError):
            parse_grounding({'grounding': [{**entry, 'basis': 'medical_knowledge'}]}, entry['quote'], evidence, '', required=True)

    def test_software_limits_trace_to_declared_policy(self):
        entry = {'quote': 'The model cannot diagnose.', 'basis': 'software_limit', 'citations': [],
                 'sources': [{'kind': 'policy', 'quote': SOFTWARE_BOUNDARY}]}
        parsed = parse_grounding({'grounding': [entry]}, entry['quote'], [], '', required=True)
        self.assertEqual(parsed[0]['sources'][0]['kind'], 'policy')

    def test_scope_limit_is_not_forced_to_invent_a_guideline_citation(self):
        quote = '本报告不对病因作推断。'
        entry = {'quote': quote, 'basis': 'scope_limit', 'citations': [],
                 'sources': [{'kind': 'policy', 'quote': SOFTWARE_BOUNDARY}]}
        parsed = parse_grounding({'grounding': [entry]}, quote, [], '', required=True)
        self.assertEqual(parsed[0]['basis'], 'scope_limit')

    def test_quantified_treatment_cannot_be_accepted_as_general_advice(self):
        quote = 'Use 10 mg every week.'
        reply = {'claims': [], 'grounding': [{'quote': quote, 'basis': 'general_advice',
                                            'citations': [], 'sources': []}]}
        text, record = CitationVerifier(Mock(return_value=json.dumps(reply)), require_grounding=True).execute(
            quote, self.evidence, max_rounds=0)
        self.assertIsNone(text)
        self.assertEqual(record['remaining_issues'][0]['origin'], 'source_audit')

    def test_source_classification_is_rechecked_before_editing_body(self):
        quote = '本报告不对病因作推断。'
        wrong = {'claims': [], 'grounding': [{'quote': quote, 'basis': 'case_inference',
                                             'citations': [], 'sources': []}]}
        corrected = {'claims': [], 'grounding': [{'quote': quote, 'basis': 'scope_limit',
            'citations': [], 'sources': [{'kind': 'policy', 'quote': SOFTWARE_BOUNDARY}]}]}
        llm = Mock(side_effect=[json.dumps(wrong), json.dumps(corrected)])
        text, record = CitationVerifier(llm, require_grounding=True).execute(quote, self.evidence)
        self.assertEqual(text, quote)
        self.assertTrue(record['adjudicated'])
        self.assertEqual(record['fixed'], [])
        self.assertEqual([step['stage'] for step in record['review_log']], ['initial', 'source_adjudication'])

    def test_negative_citation_is_still_rejected(self):
        text, record = CitationVerifier(Mock(return_value='{"claims":[]}')).execute(
            'Assertion [-1].', self.evidence, max_rounds=0)
        self.assertIsNone(text)
        self.assertEqual(record['remaining_issues'][0]['citations'], [-1])

    def test_grouped_citations_cannot_hide_an_unknown_number(self):
        for marker in ('[1,99]', '[1–99]'):
            text, record = CitationVerifier(Mock(return_value='{"claims":[]}')).execute(
                f'Assertion {marker}.', self.evidence, max_rounds=0)
            self.assertIsNone(text)
            self.assertIn(99, record['remaining_issues'][0]['citations'])

    def test_excerpt_from_another_number_is_renumbered_to_actual_source(self):
        """引文真实存在于另一条证据时，按实际来源接受，不因编号笔误判为编造。"""
        evidence = [{'index': 1, 'id': 'a', 'text': 'First clause about pressure.'},
                    {'index': 2, 'id': 'b', 'text': 'Second clause about visual field.'}]
        reply = {'claims': [], 'grounding': [{
            'quote': 'Field finding [1].', 'basis': 'medical_knowledge', 'citations': [1],
            'sources': [{'kind': 'evidence', 'index': 1,
                         'quote': 'Second clause about visual field.'}]}]}
        accepted = parse_grounding(reply, 'Field finding [1].', evidence, '', required=True)
        self.assertEqual(accepted[0]['sources'][0]['index'], 2)
        self.assertEqual(accepted[0]['sources'][0]['excerpt_kind'], 'renumbered')
        self.assertEqual(accepted[0]['sources'][0]['reported_index'], 1)

    def test_fabricated_excerpt_is_still_rejected(self):
        """放宽的是编号对应，不是原文真实性：编造的引文仍要阻断。"""
        reply = {'claims': [], 'grounding': [{
            'quote': 'Claim [1].', 'basis': 'medical_knowledge', 'citations': [1],
            'sources': [{'kind': 'evidence', 'index': 1, 'quote': 'Invented clause not in any source.'}]}]}
        with self.assertRaises(Exception):
            parse_grounding(reply, 'Claim [1].', self.evidence, '', required=True)

    def test_redundant_unknown_marker_is_stripped_without_using_a_round(self):
        """句子另有有效引用时，多余的错误编号只是笔误，直接去掉，不占用修订轮数。"""
        from modules.agent.tools.evidence import strip_unknown_citations
        cleaned, removed = strip_unknown_citations('Finding [1][9].', self.evidence)
        self.assertEqual(cleaned, 'Finding [1].')
        self.assertEqual([item['number'] for item in removed], [9])

    def test_sole_unknown_marker_is_not_stripped(self):
        """整句只靠无效引用时不能去掉，否则会变成无出处的断言。"""
        from modules.agent.tools.evidence import strip_unknown_citations
        cleaned, removed = strip_unknown_citations('Unsupported [9].', self.evidence)
        self.assertEqual(cleaned, 'Unsupported [9].')
        self.assertEqual(removed, [])


if __name__ == '__main__':
    unittest.main()
