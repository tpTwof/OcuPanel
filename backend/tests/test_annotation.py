"""无依据断言的就地标注：可交付、但不得放行与资料冲突的断言。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.agent.tools.annotation import (  # noqa: E402
    MARK,
    annotate_unverified,
    is_annotation_only,
    unannotated,
)


class AnnotationTests(unittest.TestCase):
    def test_uncited_claim_is_marked_and_delivered(self):
        text = "右眼眼压 26 mmHg。建议定期随访复查。"
        issue = {"quote": "建议定期随访复查。", "verdict": "uncited", "impact": "local",
                 "reason": "未给出来源"}
        cleaned, marked = annotate_unverified(text, [issue])
        self.assertEqual(len(marked), 1)
        self.assertIn(f"建议定期随访复查。{MARK}", cleaned)
        self.assertNotIn(MARK, "右眼眼压 26 mmHg。")

    def test_conflicting_number_is_not_annotation_only(self):
        """资料写 5–6 个月、报告写 2 个月：属于可修正错误，不能被标注放行。"""
        issue = {"quote": "建议每 2 个月复查。", "verdict": "unsupported", "impact": "core",
                 "reason": "资料为 5–6 个月"}
        self.assertFalse(is_annotation_only(issue))
        _, marked = annotate_unverified("建议每 2 个月复查。", [issue])
        self.assertEqual(marked, [])

    def test_core_impact_blocks_annotation(self):
        """core 或未分类的问题不得降级交付：可能是本例的诊断依据或处置。"""
        for impact in ("core", None):
            issue = {"quote": "这些与开角型青光眼的损害方向一致。",
                     "verdict": "unsupported", "impact": impact,
                     "reason": "资料未覆盖该表述"}
            self.assertFalse(is_annotation_only(issue), impact)

    def test_citation_mismatch_partial_is_annotated_and_number_removed(self):
        """句子内容成立、只是挂错编号：标注并把该编号去掉。"""
        issue = {"quote": "杯盘比可用于描述影像所见 [7]。", "verdict": "partial",
                 "impact": "local", "citations": [7],
                 "reason": "病例可支持，[7]未涉及"}
        self.assertTrue(is_annotation_only(issue))
        cleaned, marked = annotate_unverified("杯盘比可用于描述影像所见 [7]。", [issue])
        self.assertEqual(len(marked), 1)
        self.assertNotIn("[7]", cleaned)
        self.assertIn(MARK, cleaned)

    def test_partial_without_citation_mismatch_is_not_annotated(self):
        issue = {"quote": "左眼未见损害。", "verdict": "partial", "impact": "core",
                 "reason": "资料支持结构但未提功能"}
        self.assertFalse(is_annotation_only(issue))

    def test_missing_citation_is_never_annotated(self):
        """引用编号不存在属于引用错误，不是「资料没覆盖到」。"""
        issue = {"quote": "建议复查 [9]。", "verdict": "unsupported", "impact": "local",
                 "reason": "Unknown citation numbers: [9]", "origin": "citation_control"}
        self.assertFalse(is_annotation_only(issue))

    def test_unlocatable_quote_is_left_for_rejection(self):
        cleaned, marked = annotate_unverified("正文内容。", [
            {"quote": "不存在的句子。", "verdict": "uncited", "impact": "local"}])
        self.assertEqual(marked, [])
        self.assertEqual(cleaned, "正文内容。")

    def test_blocking_list_excludes_annotated_ones(self):
        issues = [
            {"quote": "a", "verdict": "uncited", "impact": "local"},
            {"quote": "b", "verdict": "partial", "impact": "core", "reason": "冲突"},
        ]
        self.assertEqual([i["quote"] for i in unannotated(issues)], ["b"])

    def test_marker_is_not_added_twice(self):
        text = f"建议复查{MARK}。"
        _, marked = annotate_unverified(text, [
            {"quote": "建议复查　。", "verdict": "uncited", "impact": "local"}])
        self.assertEqual(marked, [])


if __name__ == "__main__":
    unittest.main()