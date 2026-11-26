import json
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from modules.agent.verifier import CitationVerifier
from modules.agent.tools.text_revision import locate, apply_replacements
from modules.agent.tools.json_response import parse_json
from modules.report.utils.messages import reject_message

class VerificationTests(unittest.TestCase):
    evidence=[{'index':1,'text':'Evidence'}]
    issue={'claims':[{'quote':'Bad claim.','citations':[1],'verdict':'unsupported','reason':'Not supported'}]}

    def test_unchanged_replacement_is_not_counted_as_a_fix(self):
        draft = '单测眼压会漏检，不能独立完成开角型青光眼的筛查评估 [1]。'
        text, applied, deleted = apply_replacements(draft, [
            {'quote': draft, 'new': draft, 'citation': [1]},
        ])
        self.assertEqual(text, draft)
        self.assertEqual(applied, [])
        self.assertEqual(deleted, 0)

    def test_repairs_require_unique_complete_quote_and_cannot_edit_unflagged_facts(self):
        text, applied, _ = apply_replacements(
            '左眼记录完整。\n建议按指定周期复查 [1]。',
            [{'quote': '左眼记录完整。', 'new': '左眼记录缺失。'},
             {'quote': '建议按指定周期复查 [1]。后续不存在的长句', 'new': '6. **用。'}],
            allowed_quotes=['建议按指定周期复查 [1]。'],
        )
        self.assertEqual(text, '左眼记录完整。\n建议按指定周期复查 [1]。')
        self.assertEqual(applied, [])
        self.assertIsNone(locate('First sentence. First sentence.', 'First sentence.'))

    def test_markdown_omitted_from_quote_does_not_break_matching_or_editing(self):
        text = '- **角膜厚度（CCT）**：未提供，影响眼压测量值的校正与解读。'
        quote = '角膜厚度（CCT）：未提供，影响眼压测量值的校正与解读'
        changed, applied, _ = apply_replacements(text, [{'quote': quote, 'new': '未提供此项记录'}])
        self.assertEqual(changed, '- 未提供此项记录。')
        self.assertEqual(len(applied), 1)

    def test_mixed_sentence_repairs_only_the_recommendation_clause(self):
        fact = '左眼眼压偏高但结构与功能检查尚未见明确损害'
        advice = '应每周复查 [1]'
        issue = {'claims': [{'quote': advice, 'verdict': 'unsupported', 'citations': [1],
                             'impact': 'core', 'basis': 'recommendation'}]}
        llm = Mock(side_effect=[json.dumps(issue), json.dumps({'replacements': [{
            'quote': advice, 'new': '具体复查安排需结合接诊评估确定', 'citation': [],
        }]}), '{"claims":[]}'])
        text, record = CitationVerifier(llm, case_context=fact).execute(
            fact + '，' + advice + '。', self.evidence, max_rounds=1)
        self.assertEqual(text, fact + '，具体复查安排需结合接诊评估确定。')
        self.assertEqual(record['status'], 'rewritten')
        self.assertIn(fact, llm.call_args_list[0].args[0])
        self.assertIn(fact, llm.call_args_list[1].args[0])
        self.assertEqual(record['fixed'][0]['basis'], 'recommendation')

    def test_case_fact_is_grounded_in_input_rather_than_external_guideline(self):
        fact = '左眼尚未见明确损害。'
        issue = {'claims': [{'quote': fact, 'verdict': 'uncited', 'citations': [],
                             'impact': 'core', 'basis': 'case_fact', 'reason': '指南未包含该病例'}]}
        text, record = CitationVerifier(Mock(return_value=json.dumps(issue)), case_context=fact).execute(
            fact, self.evidence, max_rounds=0)
        self.assertEqual(text, fact)
        self.assertEqual(record['status'], 'pass')
        self.assertEqual(record['case_fact_matches'][0]['quote'], fact)
        self.assertEqual(record['policy_version'], 2)
        self.assertEqual(record['review_log'][0]['issue_count'], 0)

    def test_case_fact_label_does_not_bypass_missing_source_or_unknown_reference(self):
        # 带不存在的编号：无论怎么标 basis 都不能交付
        issue = {'claims': [{'quote': '左眼尚未见明确损害。[99]', 'verdict': 'unsupported',
                             'citations': [99], 'impact': 'core', 'basis': 'case_fact'}]}
        text, record = CitationVerifier(Mock(return_value=json.dumps(issue)),
                                        case_context='左眼尚未见明确损害。').execute(
            '左眼尚未见明确损害。[99]', self.evidence, max_rounds=0)
        self.assertIsNone(text)
        self.assertEqual(record['status'], 'rejected')

    def test_invented_case_measurements_cannot_be_annotated_away(self):
        """标成病例事实却凭空给出检查数值：编造患者数据，必须改掉。"""
        quote = '左眼眼压 18 mmHg，杯盘比 0.5。'
        issue = {'claims': [{'quote': quote, 'verdict': 'unsupported', 'citations': [],
                             'impact': 'core', 'basis': 'case_fact'}]}
        text, record = CitationVerifier(Mock(return_value=json.dumps(issue)),
                                        case_context='右眼眼压 26 mmHg。').execute(
            quote, self.evidence, max_rounds=0)
        self.assertIsNone(text)
        self.assertEqual(record['status'], 'rejected')

    def test_qualitative_case_claim_is_annotated_not_dropped(self):
        """没有数值的定性复述（资料恰好没写到）标注后交付，不整份扣留。"""
        quote = '左眼尚未见明确损害。'
        issue = {'claims': [{'quote': quote, 'verdict': 'unsupported', 'citations': [],
                             'impact': 'core', 'basis': 'case_fact'}]}
        text, record = CitationVerifier(Mock(return_value=json.dumps(issue)),
                                        case_context='其他病例资料。').execute(
            quote, self.evidence, max_rounds=0)
        self.assertIsNotNone(text)
        self.assertIn('〔未获资料支持〕', text)
        self.assertEqual(record['annotations'][0]['quote'], quote)

    def test_final_reference_links_and_review_versions_are_preserved(self):
        text, record = CitationVerifier(Mock(return_value='{"claims":[]}'), case_context='Case data.').execute(
            'Supported explanation [1].', self.evidence)
        self.assertEqual(record['reference_links'][0]['citations'], [1])
        self.assertEqual(record['source_manifest']['evidence'][0]['index'], 1)
        self.assertEqual(len(record['source_manifest']['case_sha256']), 64)
        self.assertEqual(record['review_log'][-1]['text_sha256'], record['final_text_sha256'])

    def test_local_issue_is_omitted_then_entire_report_is_rechecked(self):
        fact = '本例右眼眼压 26 mmHg。'
        extra = '糖尿病黄斑水肿需要另一项检查 [1]。'
        issues = {'claims': [{'quote': extra, 'citations': [1], 'verdict': 'unsupported',
                              'impact': 'local', 'reason': '与本次病例无关'}]}
        llm = Mock(side_effect=[json.dumps(issues), '{"replacements":[]}',
                                json.dumps(issues), '{"claims":[]}'])
        regenerate = Mock()
        text, record = CitationVerifier(llm).execute(fact + '\n' + extra, self.evidence,
                                                    max_rounds=1, regenerate=regenerate)
        self.assertEqual(text, fact)
        self.assertEqual(record['status'], 'rewritten')
        self.assertEqual(record['deleted'], 1)
        self.assertEqual(record['fixed'][0]['reason'], '与本次病例无关')
        self.assertEqual(record['fixed'][0]['method'], 'local_omission')
        self.assertIn(fact, llm.call_args.args[0])
        current_body = llm.call_args.args[0].split('【报告正文】')[1].split('【参考资料】')[0]
        self.assertNotIn(extra, current_body)
        regenerate.assert_not_called()

    def test_local_cleanup_still_rechecks_and_annotates_what_remains(self):
        """局部删减后必须重新核查；余留的无依据断言改为就地标注后交付。"""
        local = {'claims': [{'quote': 'Extra statement [1].', 'verdict': 'unsupported',
                            'citations': [1], 'impact': 'local'}]}
        llm = Mock(side_effect=[json.dumps(local), json.dumps(self.issue)])
        text, record = CitationVerifier(llm).execute(
            'Bad claim.\nExtra statement [1].', self.evidence, max_rounds=0)
        # 重新核查确实发生过（两次调用），余留问题被记录而不是被丢弃
        self.assertEqual(llm.call_count, 2)
        self.assertEqual(record['review_log'][-1]['issue_count'], 1)
        self.assertIsNotNone(text)
        self.assertIn('〔未获资料支持〕', text)
        self.assertEqual([a['quote'] for a in record['annotations']], ['Bad claim.'])

    def test_core_or_unclassified_issue_is_annotated_not_dropped(self):
        """无法判断影响时不再整份扣留，但必须留下标注与审计记录。"""
        for impact in (None, 'core'):
            with self.subTest(impact=impact):
                claim = dict(self.issue['claims'][0])
                if impact:
                    claim['impact'] = impact
                llm = Mock(return_value=json.dumps({'claims': [claim]}))
                text, record = CitationVerifier(llm).execute('Case data.\nBad claim.', self.evidence,
                                                           max_rounds=0)
                self.assertIsNotNone(text)
                self.assertEqual(record['reason'], 'delivered_with_annotations')
                self.assertEqual(record['deleted'], 0)
                self.assertIn('Bad claim.〔未获资料支持〕', text)
                self.assertEqual(record['annotations'][0]['quote'], 'Bad claim.')

    def test_unknown_number_cannot_be_downgraded_to_local(self):
        llm = Mock(return_value=json.dumps({'claims': [{
            'quote': 'Extra [99].', 'citations': [99], 'verdict': 'unsupported', 'impact': 'local',
        }]}))
        text, record = CitationVerifier(llm).execute('Case data.\nExtra [99].', self.evidence,
                                                   max_rounds=0)
        self.assertIsNone(text)
        self.assertEqual(record['remaining_issues'][0]['impact'], 'core')

    def test_unlocatable_local_issue_does_not_allow_delivery(self):
        llm = Mock(return_value=json.dumps({'claims': [{
            'quote': 'Missing sentence.', 'citations': [], 'verdict': 'unsupported', 'impact': 'local',
        }]}))
        text, record = CitationVerifier(llm).execute('Case facts.', self.evidence, max_rounds=0)
        self.assertIsNone(text)
        self.assertEqual(record['status'], 'error')
        self.assertIn('uniquely match', record['failure_detail'])

    def test_misquoted_issue_is_corrected_before_any_edit(self):
        llm = Mock(side_effect=[json.dumps({'claims': [{
            'quote': 'Sentence not in this report.', 'verdict': 'unsupported', 'citations': [],
        }]}), '{"claims":[]}'])
        text, record = CitationVerifier(llm).execute('Original case data.', self.evidence)
        self.assertEqual(text, 'Original case data.')
        self.assertEqual(record['fixed'], [])
        self.assertEqual(record['format_retries'], 1)

    def test_source_fact_cannot_be_deleted_through_a_mixed_sentence(self):
        fact = '左眼眼压偏高但结构与功能检查尚未见明确损害'
        mixed = fact + '，应每周复查 [1]。'
        issue = {'claims': [{'quote': mixed, 'verdict': 'unsupported', 'citations': [1],
                             'impact': 'local', 'basis': 'recommendation'}]}
        llm = Mock(side_effect=[json.dumps(issue), json.dumps({'replacements': [{
            'quote': mixed, 'new': '', 'citation': [],
        }]}), json.dumps(issue)])
        text, record = CitationVerifier(llm, case_context=fact).execute(mixed, self.evidence, max_rounds=1)
        self.assertIsNone(text)
        self.assertEqual(record['deleted'], 0)
        self.assertEqual(record['remaining_issues'][0]['impact'], 'core')

    def test_local_cleanup_does_not_delete_a_fragment_or_duplicate_match(self):
        from modules.agent.tools.text_revision import omit_local_issues
        for draft, quote in (
            ('Diagnosis is not confirmed.', 'not'),
            ('Extra statement.\nExtra statement.', 'Extra statement.'),
        ):
            with self.subTest(draft=draft):
                cleaned, omitted = omit_local_issues(draft, [{'quote': quote, 'impact': 'local'}])
                self.assertEqual(cleaned, draft)
                self.assertEqual(omitted, [])

    def test_local_cleanup_removes_empty_section_and_list_marker(self):
        from modules.agent.tools.text_revision import omit_local_issues
        draft = '## 病例\n眼压 26 mmHg。\n## 附加说明\n- 无关条款 [1]。'
        cleaned, omitted = omit_local_issues(draft, [{
            'quote': '无关条款 [1]。', 'impact': 'local', 'citations': [1],
        }])
        self.assertEqual(cleaned, '## 病例\n眼压 26 mmHg。')
        self.assertEqual(len(omitted), 1)

    def test_local_cleanup_error_or_empty_result_withholds_report(self):
        issue = {'claims': [{'quote': 'Extra statement.', 'citations': [],
                             'verdict': 'unsupported', 'impact': 'local'}]}
        for draft, replies, status in (
            ('Case facts.\nExtra statement.', [json.dumps(issue), 'Error: unavailable'], 'error'),
            ('Extra statement.', [json.dumps(issue)], 'rejected'),
        ):
            with self.subTest(draft=draft):
                text, record = CitationVerifier(Mock(side_effect=replies)).execute(
                    draft, self.evidence, max_rounds=0)
                self.assertIsNone(text)
                self.assertEqual(record['status'], status)

    def test_mixed_core_and_local_issues_are_all_recorded(self):
        """core 与 local 并存时不能只处理 local 就放行；两者都要留痕。"""
        claims = [dict(self.issue['claims'][0], impact='core'),
                  {'quote': 'Extra statement.', 'verdict': 'unsupported', 'citations': [], 'impact': 'local'}]
        text, record = CitationVerifier(Mock(return_value=json.dumps({'claims': claims}))).execute(
            'Case facts.\nBad claim.\nExtra statement.', self.evidence, max_rounds=0)
        self.assertIsNotNone(text)
        self.assertEqual(record['deleted'], 0)
        annotated = {item['quote'] for item in record['annotations']}
        self.assertEqual(annotated, {'Bad claim.', 'Extra statement.'})
        self.assertIn('Bad claim.〔未获资料支持〕', text)
        self.assertIn('Extra statement.〔未获资料支持〕', text)

    def test_verification_errors_identify_failure_without_exposing_response(self):
        for reply, kind in (("", "empty_response"),
                            ("Error: private provider details", "llm_error"),
                            ("not JSON", "invalid_json"),
                            ('{}', "invalid_claims"),
                            ('{"claims":[{}]}', "invalid_claims")):
            with self.subTest(kind=kind, reply=reply):
                text, record = CitationVerifier(Mock(return_value=reply)).execute(
                    "Case findings [1].", self.evidence)
                self.assertIsNone(text)
                self.assertEqual(record["reason"], "verify_call_failed")
                self.assertEqual(record["failure_kind"], kind)
                self.assertNotIn("private provider details", json.dumps(record))

    def test_verification_error_message_does_not_blame_missing_case_data(self):
        message = reject_message({"status": "error", "reason": "verify_call_failed"})
        self.assertIn("LLM", message)
        self.assertNotIn("补充视野", message)
        self.assertNotIn("刻意设计", message)

    def test_recheck_retains_failure_kind_and_withholds_draft(self):
        llm = Mock(side_effect=[json.dumps(self.issue), '{"replacements":[]}', '{}', '{}'])
        text, record = CitationVerifier(llm).execute('Bad claim.', self.evidence)
        self.assertIsNone(text)
        self.assertEqual(record['reason'], 'recheck_call_failed')
        self.assertEqual(record['failure_kind'], 'invalid_claims')

    def test_invalid_claims_are_retried_with_schema_feedback(self):
        malformed = {'claims': [{'quote': 'Case findings [1].', 'verdict': 'supported', 'citations': [1]}]}
        llm = Mock(side_effect=[json.dumps(malformed), '{"claims":[]}'])
        text, record = CitationVerifier(llm).execute('Case findings [1].', self.evidence)
        self.assertEqual(text, 'Case findings [1].')
        self.assertEqual(record['status'], 'pass')
        self.assertEqual(record['format_retries'], 1)
        retry_prompt = llm.call_args_list[1].args[0]
        self.assertIn('claims[0].verdict', retry_prompt)
        self.assertIn('Case findings [1].', retry_prompt)
        self.assertIn('Evidence', retry_prompt)

    def test_format_retry_does_not_ignore_unknown_citations(self):
        llm = Mock(side_effect=['{}', '{"claims":[]}'])
        text, record = CitationVerifier(llm).execute('Draft [99]', self.evidence, max_rounds=0)
        self.assertIsNone(text)
        self.assertEqual(record['status'], 'rejected')
        self.assertEqual(record['remaining_issues'][0]['citations'], [99])

    def test_persistent_format_error_is_bounded_and_explained(self):
        llm = Mock(return_value='{"claims":[{}]}')
        text, record = CitationVerifier(llm).execute('Case findings [1].', self.evidence)
        self.assertIsNone(text)
        self.assertEqual(record['status'], 'error')
        self.assertEqual(llm.call_count, 2)
        self.assertIn('claims[0].quote', record['failure_detail'])
        self.assertIn('claims[0].quote', reject_message(record))

    def test_request_failure_is_not_retried_as_a_format_error(self):
        llm = Mock(return_value='Error: private details')
        text, record = CitationVerifier(llm).execute('Case findings [1].', self.evidence)
        self.assertIsNone(text)
        self.assertEqual(llm.call_count, 1)

    def test_revision_rechecked(self):
        llm=Mock(side_effect=[json.dumps(self.issue),json.dumps({'replacements':[{'quote':'Bad claim.','new':'Supported claim.','citation':[1]}]}),'{"claims":[]}'])
        text,record=CitationVerifier(llm,min_chars=1).execute('Bad claim.',self.evidence)
        self.assertEqual(text,'Supported claim.')
        self.assertEqual(record['status'],'rewritten')
        self.assertEqual(llm.call_count,3)

    def test_regeneration_and_recheck(self):
        llm=Mock(side_effect=[json.dumps(self.issue),'{"replacements":[]}',json.dumps(self.issue),'{"claims":[]}'])
        regenerate=Mock(return_value='New report.')
        text,record=CitationVerifier(llm).execute('Bad claim.',self.evidence,max_rounds=1,regenerate=regenerate)
        self.assertEqual(text,'New report.')
        self.assertTrue(record['regenerated'])
        regenerate.assert_called_once()

    def test_failed_regeneration_keeps_audit_and_annotates_remainder(self):
        llm = Mock(side_effect=[json.dumps(self.issue), '{"replacements":[]}', json.dumps(self.issue)])
        text, record = CitationVerifier(llm).execute('Bad claim.', self.evidence, max_rounds=1,
                                                    regenerate=Mock(side_effect=TimeoutError()))
        self.assertIsNotNone(text)
        self.assertEqual(record['regeneration_failure'], 'TimeoutError')
        self.assertEqual(len(record['review_log']), 2)
        self.assertEqual(record['annotations'][0]['quote'], 'Bad claim.')
        self.assertIn('〔未获资料支持〕', text)
        self.assertEqual(record['reason'], 'delivered_with_annotations')

    def test_unresolved_claim_is_annotated_after_last_round(self):
        llm=Mock(side_effect=[json.dumps(self.issue),'{"replacements":[]}',json.dumps(self.issue)])
        text,record=CitationVerifier(llm).execute('Bad claim.',self.evidence,max_rounds=1)
        self.assertIsNotNone(text)
        self.assertEqual(record['reason'],'delivered_with_annotations')
        self.assertEqual(record['rounds'], len(record['review_log']))
        self.assertIn('〔未获资料支持〕', text)

    def test_malformed_claims_fail_verification(self):
        for item in (None, {}, {"quote": "Bad claim.", "verdict": "unknown"},
                     {"quote": "Bad claim.", "verdict": "unsupported", "citations": "1"}):
            with self.subTest(item=item):
                llm = Mock(return_value=json.dumps({"claims": [item]}))
                text, record = CitationVerifier(llm).execute("Bad claim.", self.evidence)
                self.assertIsNone(text)
                self.assertEqual(record["status"], "error")

    def test_empty_draft_and_deleted_last_claim_are_rejected(self):
        llm = Mock(side_effect=[json.dumps(self.issue),
                               json.dumps({"replacements": [{"quote": "Bad claim.", "new": ""}]})])
        verifier = CitationVerifier(llm)
        for draft in ("## [1]", "Bad claim."):
            text, record = verifier.execute(draft, self.evidence)
            self.assertIsNone(text)
            self.assertEqual(record["reason"], "empty_text")
        self.assertEqual(llm.call_count, 2)

    def test_text_tools(self):
        self.assertEqual(locate('A B\nC','ABC'),(0,5))
        text,applied,deleted=apply_replacements('First. Second.',[{'quote':'First.','new':''}])
        self.assertEqual(text,'Second.')
        self.assertEqual(deleted,1)
        self.assertEqual(len(applied),1)
        self.assertEqual(parse_json('```json\n{"claims": []}\n```'),{'claims':[]})

if __name__=='__main__':unittest.main()
