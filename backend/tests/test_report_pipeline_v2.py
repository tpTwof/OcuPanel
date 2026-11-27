"""按需检索与统一报告流程的离线回归。

覆盖方案验收要求：不检索、正常检索、补检、无结果、工具故障、规划格式错误、
预算耗尽、证据冲突、不适用来源、重复检查建议、多病种、左右眼混淆和未知引用编号。
全部使用固定工具结果与固定模型回复，不访问真实模型或网络。
"""

import asyncio
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import config
from modules.agent.planner import (
    RetrievalPlan,
    RetrievalPlanner,
    RetrievalQuestion,
    fallback_plan,
    parse_plan,
)
from modules.agent.prompts.planner import build_planner_prompt
from modules.agent.prompts.report import (
    REPORT_PROMPT_VERSION,
    REPORT_REQUIREMENTS,
    report_section_titles,
)
from modules.agent.tools.applicability import (
    evidence_scope_issues,
    fabricated_value_issues,
    lateral_mismatch_issues,
)
from modules.knowledge.question_retrieval import (
    QuestionResult,
    RetrievalBudget,
    RetrievalOutcome,
    retrieve_for_plan,
)
from modules.knowledge.retrieval import format_evidence_block
from modules.report import service
from modules.report.case_facts import build_case_facts
from modules.report.generation import MedicalReportGenerator
from modules.vision import DiseaseResult, EyeAnalysis


# -- 固定输入 -----------------------------------------------------------------

def evidence(index=1, **extra):
    item = {
        "id": f"e{index}", "index": index, "source": "cn-glaucoma-2020",
        "title": "青光眼指南摘要", "section": "随访与监测",
        "text": "青光眼随访应结合视野与视神经结构评估。",
        "version": "2020 摘要", "url": "https://example.org/guideline",
        "material_type": "guideline", "review_status": "pending", "content_hash": f"hash{index}",
    }
    item.update(extra)
    return item


def make_plan(*, need=True, topic="followup", disease="glaucoma", question="本病例如何随访？", questions=None):
    items = questions if questions is not None else (
        (RetrievalQuestion(question=question, topic=topic, filters={"disease": disease}),)
        if need else ()
    )
    return RetrievalPlan(need_retrieval=need, reason="需要外部依据", questions=tuple(items))


def make_outcome(items=None, *, status="ok", questions=None, failures=None, queries=1):
    items = items or []
    if questions is None:
        questions = [QuestionResult(
            question="本病例如何随访？", topic="followup", disease="glaucoma",
            answered=bool(items), evidence_ids=[item["id"] for item in items],
        )]
    return RetrievalOutcome(
        status=status, evidence=items, questions=questions, failures=failures or [],
        queries=queries,
    )


class FakeRetriever:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def search(self, query, **kwargs):
        self.calls.append((query, kwargs))
        value = self.results.pop(0) if self.results else []
        if isinstance(value, Exception):
            raise value
        return value


BUDGET = RetrievalBudget(
    max_queries=5, max_seconds=5, max_evidence=4, supplemental_rounds=1,
    top_k=4, min_score=0.0,
)


# -- 病例事实 -----------------------------------------------------------------

class CaseFactTests(unittest.TestCase):
    def test_fact_ids_are_stable_and_unique(self):
        note = "右眼眼压 26 mmHg。右眼视野检查示鼻侧阶梯。"
        first = build_case_facts({}, note, laterality="right", filename="eye.png")
        second = build_case_facts({}, note, laterality="right", filename="eye.png")
        self.assertEqual([f.id for f in first.all], [f.id for f in second.all])
        self.assertEqual(len({f.id for f in first.all}), len(first.all))
        eyes = {f.eye for f in first.facts if f.source == "clinical_note"}
        self.assertEqual(eyes, {"right"})

    def test_unprovided_is_not_rewritten_as_not_examined(self):
        facts = build_case_facts(
            {"glaucoma": {"probability": .8, "measurements": {}, "warnings": []}},
            "眼压偏高。", laterality="right",
        )
        missing = [fact.text for fact in facts.missing]
        self.assertTrue(any(text.startswith("未提供") for text in missing))
        self.assertNotIn("未检查", " ".join(fact.text for fact in facts.all))
        self.assertIn("不等于未检查", facts.gaps_note())

    def test_model_score_stays_a_model_output(self):
        facts = build_case_facts(
            {"glaucoma": {"probability": .82, "measurements": {"area_equivalent_cdr": .72}}},
            "", laterality="right",
        )
        model_facts = [f for f in facts.facts if f.source == "imaging_model"]
        self.assertTrue(model_facts)
        self.assertTrue(all(f.kind == "model_output" for f in model_facts))
        self.assertFalse(any("确诊" in f.text for f in model_facts))

    def test_eye_mismatch_is_a_conflict_not_merged(self):
        facts = build_case_facts({}, "右眼眼压 26 mmHg。", laterality="left")
        self.assertTrue(facts.conflicts)
        self.assertIn("右眼", facts.conflicts[0].text)
        self.assertIn("左眼", facts.conflicts[0].text)

    def test_conflicting_values_are_kept(self):
        facts = build_case_facts({}, "右眼眼压 24 mmHg。右眼眼压 18 mmHg。", laterality="right")
        self.assertTrue(any("不同取值" in fact.text for fact in facts.conflicts))

    def test_missing_laterality_is_recorded(self):
        facts = build_case_facts({"glaucoma": {"probability": .7, "measurements": {}}}, "")
        self.assertIn("cf-gap-laterality", {fact.id for fact in facts.missing})

    def test_other_eye_not_provided_is_not_a_conflict(self):
        facts = build_case_facts({}, "右眼眼压 26 mmHg。左眼未提供检查。", laterality="right")
        self.assertFalse([fact for fact in facts.conflicts
                          if fact.location == "conflict:laterality"])

    def test_one_sentence_can_supply_several_exam_facts(self):
        facts = build_case_facts(
            {"glaucoma": {"probability": .8, "measurements": {}}},
            "右眼眼压 26 mmHg，视野检查示鼻侧阶梯。", laterality="right",
        )
        missing = {fact.id for fact in facts.missing}
        self.assertNotIn("cf-gap-glaucoma-visual_field", missing)


# -- 检索规划 -----------------------------------------------------------------

class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.facts = build_case_facts(
            {"glaucoma": {"probability": .8, "measurements": {}}},
            "右眼眼压 26 mmHg，视野检查示鼻侧阶梯。", laterality="right",
        )

    def test_valid_plan_drops_invented_fact_ids(self):
        payload = {
            "need_retrieval": True, "reason": "需要判读依据",
            "questions": [{
                "question": "视野缺损如何判读？", "topic": "interpretation",
                "case_fact_ids": [self.facts.facts[0].id, "cf-made-up"],
                "filters": {"disease": "glaucoma", "material_types": ["guideline"]},
            }],
            "missing_information": ["视野可靠性指标"],
        }
        plan = parse_plan(payload, fact_ids=self.facts.fact_ids,
                          diseases=("glaucoma",), max_questions=6)
        self.assertEqual(plan.questions[0].case_fact_ids, (self.facts.facts[0].id,))
        self.assertEqual(plan.missing_information, ("视野可靠性指标",))

    def test_invalid_fields_are_rejected(self):
        base = {"need_retrieval": True, "reason": "r", "questions": [{"question": "q", "topic": "diagnosis"}]}
        cases = {
            "unknown topic": {**base, "questions": [{"question": "q", "topic": "surgery"}]},
            "disagreement": {**base, "need_retrieval": False},
            "missing disease in multi": {**base, "questions": [{"question": "q", "topic": "diagnosis"}]},
            "bad material type": {**base, "questions": [{
                "question": "q", "topic": "diagnosis",
                "filters": {"disease": "glaucoma", "material_types": ["blog"]},
            }]},
        }
        for name, payload in cases.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                parse_plan(payload, fact_ids=(), diseases=("glaucoma", "diabetic_retinopathy"),
                           max_questions=6)

    def test_format_error_falls_back_to_conservative_plan(self):
        planner = RetrievalPlanner(lambda prompt, **kwargs: "这不是 JSON")
        plan = planner.plan(self.facts, ("glaucoma",))
        self.assertEqual(plan.status, "fallback")
        self.assertTrue(plan.need_retrieval)
        self.assertTrue(plan.questions)
        self.assertEqual(plan.questions[0].filters["disease"], "glaucoma")

    def test_model_output_cannot_skip_retrieval(self):
        reply = json.dumps({
            "need_retrieval": False, "reason": "只复述病例", "questions": [],
            "missing_information": [],
        })
        plan = RetrievalPlanner(lambda prompt, **kwargs: reply).plan(self.facts, ("glaucoma",))
        self.assertEqual(plan.status, "fallback")
        self.assertTrue(plan.need_retrieval)

    def test_no_case_facts_means_no_retrieval(self):
        plan = RetrievalPlanner(lambda prompt, **kwargs: "{}").plan(build_case_facts(), ())
        self.assertFalse(plan.need_retrieval)
        self.assertEqual(plan.status, "ok")

    def test_fallback_never_exceeds_question_budget(self):
        plan = fallback_plan(
            self.facts, ("glaucoma", "diabetic_retinopathy"),
            max_questions=3, reason="测试",
        )
        self.assertEqual(len(plan.questions), 3)
        self.assertTrue(all(item.filters["disease"] in ("glaucoma", "diabetic_retinopathy")
                            for item in plan.questions))


# -- 检索执行 -----------------------------------------------------------------

class PlannedRetrievalTests(unittest.TestCase):
    def test_not_needed_skips_queries(self):
        retriever = FakeRetriever([])
        outcome = retrieve_for_plan(make_plan(need=False), diseases=("glaucoma",), retriever=retriever)
        self.assertEqual(outcome.status, "not_needed")
        self.assertEqual(outcome.queries, 0)
        self.assertFalse(retriever.calls)

    def test_disabled_retrieval_is_not_a_failure(self):
        with patch.object(config, "RAG_ENABLED", False):
            outcome = retrieve_for_plan(make_plan(), diseases=("glaucoma",), retriever=FakeRetriever([]))
        self.assertEqual(outcome.status, "disabled")

    def test_empty_result_is_distinct_from_tool_failure(self):
        empty = retrieve_for_plan(make_plan(), diseases=("glaucoma",), retriever=FakeRetriever([[]]))
        self.assertEqual(empty.status, "empty")
        self.assertEqual(empty.unresolved[0]["reasons"], ["no_result"])
        failed = retrieve_for_plan(
            make_plan(), diseases=("glaucoma",), retriever=FakeRetriever([RuntimeError("down")]),
        )
        self.assertEqual(failed.status, "error")
        self.assertEqual(failed.failures[0]["kind"], "tool_error")
        self.assertNotEqual(failed.status, empty.status)

    def test_supplemental_round_answers_a_gap(self):
        retriever = FakeRetriever([[], [evidence(1)]])
        outcome = retrieve_for_plan(make_plan(), diseases=("glaucoma",), retriever=retriever, budget=BUDGET)
        self.assertEqual(outcome.status, "ok")
        self.assertEqual(outcome.supplemental_rounds, 1)
        self.assertTrue(outcome.questions[0].supplemented)
        self.assertEqual([item["index"] for item in outcome.evidence], [1])
        self.assertEqual(len(retriever.calls), 2)
        self.assertNotEqual(retriever.calls[0][0], retriever.calls[1][0])

    def test_duplicate_query_is_not_executed_twice(self):
        plan = make_plan(questions=(
            RetrievalQuestion("本病例如何随访？", "followup", filters={"disease": "glaucoma"}),
            RetrievalQuestion("本病例如何随访？", "followup", filters={"disease": "glaucoma"}),
        ))
        retriever = FakeRetriever([[evidence(1)]])
        outcome = retrieve_for_plan(plan, diseases=("glaucoma",), retriever=retriever, budget=BUDGET)
        self.assertEqual(len(retriever.calls), 1)
        self.assertEqual(outcome.queries, 1)
        self.assertIn("duplicate_query", outcome.questions[1].gaps)

    def test_budget_exhaustion_stops_without_looping(self):
        plan = make_plan(questions=(
            RetrievalQuestion("问题一", "followup", filters={"disease": "glaucoma"}),
            RetrievalQuestion("问题二", "treatment", filters={"disease": "glaucoma"}),
        ))
        budget = RetrievalBudget(max_queries=1, max_seconds=5, max_evidence=4,
                                 supplemental_rounds=1, top_k=4, min_score=0.0)
        outcome = retrieve_for_plan(
            plan, diseases=("glaucoma",), retriever=FakeRetriever([[evidence(1)]]), budget=budget,
        )
        self.assertTrue(outcome.budget_exhausted)
        self.assertEqual(outcome.queries, 1)
        self.assertIn("budget_exhausted", outcome.questions[1].gaps)
        self.assertEqual(outcome.status, "partial")

    def test_material_type_that_cannot_support_the_topic_is_excluded(self):
        education = evidence(1, source="nei-fixture", material_type="patient_education",
                             text="面向公众的说明")
        plan = make_plan(topic="treatment", question="本病例如何治疗？")
        outcome = retrieve_for_plan(
            plan, diseases=("glaucoma",), retriever=FakeRetriever([[education]]), budget=BUDGET,
        )
        self.assertEqual(outcome.status, "empty")
        self.assertIn("material_type", outcome.unresolved[0]["reasons"])

    def test_applicability_mismatch_is_excluded(self):
        item = evidence(1, applicability={"population": "儿童"})
        plan = make_plan(questions=(
            RetrievalQuestion("本病例如何治疗？", "treatment",
                              filters={"disease": "glaucoma", "population": "成人"}),
        ))
        outcome = retrieve_for_plan(
            plan, diseases=("glaucoma",), retriever=FakeRetriever([[item]]), budget=BUDGET,
        )
        self.assertEqual(outcome.status, "empty")
        self.assertEqual(outcome.questions[0].excluded[0]["reason"], "applicability")

    def test_new_evidence_appends_after_existing_indices(self):
        existing = [evidence(1, id="old")]
        existing[0]["index"] = 5
        outcome = retrieve_for_plan(
            make_plan(), diseases=("glaucoma",), retriever=FakeRetriever([[evidence(2, id="new")]]),
            budget=BUDGET, existing=existing,
        )
        self.assertEqual([item["index"] for item in outcome.evidence], [5, 6])
        self.assertIn("content_hash", outcome.evidence[1]["snapshot"])

    def test_question_disease_scope_is_used_for_filtering(self):
        dr_item = evidence(1, source="cn-dr-2022", id="dr", topic="interpretation")
        plan = make_plan(questions=(
            RetrievalQuestion("糖网如何分期？", "interpretation",
                              filters={"disease": "diabetic_retinopathy"}),
        ))
        outcome = retrieve_for_plan(
            plan, diseases=("glaucoma", "diabetic_retinopathy"),
            retriever=FakeRetriever([[dr_item]]), budget=BUDGET,
        )
        self.assertEqual(outcome.status, "ok")
        self.assertEqual(outcome.questions[0].disease, "diabetic_retinopathy")

    def test_conflicting_sources_are_kept_with_their_versions(self):
        first = evidence(1, id="source-a", version="2020 版", text="随访间隔 3 个月")
        second = evidence(2, id="source-b", version="2024 版", text="随访间隔 6 个月")
        outcome = retrieve_for_plan(
            make_plan(), diseases=("glaucoma",),
            retriever=FakeRetriever([[first, second]]), budget=BUDGET,
        )
        # 冲突来源都保留，版本与适用范围不合并；是否采用由报告与核查保留差异。
        self.assertEqual({item["id"] for item in outcome.evidence}, {"source-a", "source-b"})
        self.assertEqual({item["version"] for item in outcome.evidence}, {"2020 版", "2024 版"})


# -- 确定性的适用性检查 -------------------------------------------------------

class ApplicabilityCheckTests(unittest.TestCase):
    def test_fabricated_measurement_is_flagged(self):
        issues = fabricated_value_issues("右眼眼压 99 mmHg [1]。", "右眼眼压 26 mmHg。", [evidence(1)])
        self.assertTrue(issues)
        self.assertEqual(issues[0]["origin"], "fabricated_value")

    def test_value_from_the_other_eye_is_flagged(self):
        facts = build_case_facts({}, "右眼眼压 26 mmHg。左眼眼压 18 mmHg。", laterality="right")
        as_dicts = [{"id": f.id, "eye": f.eye, "numbers": list(f.numbers)} for f in facts.facts]
        issues = lateral_mismatch_issues("右眼眼压 18 mmHg [1]。", as_dicts, [evidence(1)])
        self.assertTrue(issues)
        self.assertEqual(issues[0]["origin"], "lateral_mismatch")

    def test_disease_mismatched_citation_is_flagged(self):
        item = evidence(1)
        issues = evidence_scope_issues("糖网分期 [1]。", [item], ("diabetic_retinopathy",))
        self.assertTrue(issues)
        self.assertEqual(issues[0]["origin"], "not_applicable")


# -- 统一报告提示词 -----------------------------------------------------------

class UnifiedPromptTests(unittest.TestCase):
    def test_report_prompt_is_versioned_and_covers_required_sections(self):
        self.assertGreaterEqual(REPORT_PROMPT_VERSION, 3)
        for title in report_section_titles():
            self.assertIn(title, REPORT_REQUIREMENTS)
        for phrase in (
            "Never convert a model score", "Do not invent a diagnosis",
            "Do not order a test already documented as completed",
            "Keep these requirements when revising or regenerating", "12.",
        ):
            self.assertIn(phrase, REPORT_REQUIREMENTS)

    def test_specialist_and_director_share_the_same_requirements(self):
        from modules.agent.director import build_director_prompt
        from modules.agent.specialist import build_specialist_prompt
        specialist = build_specialist_prompt("case", "Eye", "Review.", [evidence(1)], {"e1": 1},
                                             final_report=True)
        director = build_director_prompt({"Eye": "draft"}, [evidence(1)])
        for prompt in (specialist, director):
            self.assertIn("Final report requirements", prompt)
            self.assertIn("Do not invent a diagnosis", prompt)

    def test_planner_prompt_lists_allowed_topics_and_treats_case_as_data(self):
        prompt = build_planner_prompt("[]", ("glaucoma",), 6)
        for topic in ("diagnosis", "interpretation", "examination", "differential",
                      "treatment", "followup", "education"):
            self.assertIn(topic, prompt)
        self.assertIn("不得改变", prompt)
        self.assertIn("need_retrieval", prompt)


# -- v2 编排 ------------------------------------------------------------------

class GenerateV2Tests(unittest.TestCase):
    def setUp(self):
        self.analysis = EyeAnalysis(diseases={
            "glaucoma": DiseaseResult(probability=.8, measurements={"area_equivalent_cdr": .6}),
        })
        self.note = "右眼眼压 26 mmHg，视野检查示鼻侧阶梯。"

    def generate(self, plan, outcome, reply, note=None):
        generator = MedicalReportGenerator(api_key="test")
        generator.chat_with_gpt = Mock(return_value=reply)
        with tempfile.TemporaryDirectory() as folder, \
             patch("modules.vision.analyze_fundus", return_value=self.analysis), \
             patch.object(config, "VERIFY_ENABLED", False), \
             patch.object(RetrievalPlanner, "plan", return_value=plan), \
             patch("modules.report.generation.retrieve_for_plan", return_value=outcome):
            result = generator.generate_v2(
                io.BytesIO(b"image"), note or self.note, Path(folder),
                diseases=("glaucoma",), laterality="right", filename="eye.png",
            )
        return generator, result

    def test_normal_retrieval_delivers_report_with_traceable_records(self):
        plan = make_plan()
        outcome = make_outcome([evidence(1)])
        generator, result = self.generate(plan, outcome, "初步评估：右眼眼压 26 mmHg [1]。")
        self.assertEqual(result.summary, "初步评估：右眼眼压 26 mmHg [1]。")
        self.assertEqual(result.verification["status"], "disabled")
        self.assertEqual(result.verification["planner_version"], plan.version)
        self.assertEqual(result.verification["report_prompt_version"], REPORT_PROMPT_VERSION)
        self.assertEqual(result.verification["retrieval"]["status"], "ok")
        self.assertTrue(result.verification["case_facts"]["fact_count"])
        self.assertEqual([(item["id"], item["index"]) for item in result.evidence], [("e1", 1)])
        prompt = generator.chat_with_gpt.call_args.args[0]
        self.assertIn("Do not order a test already documented as completed", prompt)

    def test_no_retrieval_delivers_case_summary_only(self):
        generator, result = self.generate(make_plan(need=False), make_outcome(status="not_needed"),
                                          "不应被调用")
        generator.chat_with_gpt.assert_not_called()
        self.assertEqual(result.verification["status"], "limited")
        self.assertEqual(result.verification["reason"], "no_retrieval_requested")
        self.assertEqual(result.verification["delivery_scope"], "case_input_only")
        self.assertIn(self.note, result.summary)
        self.assertNotIn("不应被调用", result.summary)

    def test_tool_failure_withholds_report_and_keeps_case_input(self):
        question = QuestionResult(question="本病例如何随访？", topic="followup",
                                  disease="glaucoma", failed=True, gaps=["tool_error"])
        outcome = make_outcome(status="error", questions=[question], failures=[{
            "question": question.question, "kind": "tool_error", "detail": "RuntimeError",
        }])
        _, result = self.generate(make_plan(), outcome, "不应被调用")
        self.assertEqual(result.verification["status"], "limited")
        self.assertEqual(result.verification["reason"], "retrieval_failed")
        self.assertEqual(result.verification["retrieval"]["status"], "error")
        self.assertTrue(result.verification["retrieval"]["failures"])
        self.assertIn(self.note, result.summary)

    def test_empty_retrieval_is_reported_as_knowledge_gap(self):
        question = QuestionResult(question="本病例如何随访？", topic="followup",
                                  disease="glaucoma", gaps=["no_result"])
        _, result = self.generate(make_plan(), make_outcome(status="empty", questions=[question]),
                                  "不应被调用")
        self.assertEqual(result.verification["status"], "limited")
        self.assertEqual(result.verification["reason"], "no_evidence")
        self.assertEqual(result.verification["knowledge_gaps"][0]["kind"], "corpus")

    def test_unknown_citation_withholds_the_draft(self):
        _, result = self.generate(make_plan(), make_outcome([evidence(1)]), "结论 [99]。")
        self.assertIsNone(result.summary)
        self.assertEqual(result.verification["status"], "rejected")
        self.assertEqual(result.verification["remaining_issues"][0]["origin"], "citation_control")

    def test_conflicting_facts_reach_the_drafting_prompt(self):
        note = "右眼眼压 24 mmHg。右眼眼压 18 mmHg。"
        generator, _ = self.generate(
            make_plan(), make_outcome([evidence(1)]),
            "初步评估：右眼眼压 24 mmHg [1]。", note=note,
        )
        prompt = generator.chat_with_gpt.call_args.args[0]
        self.assertIn("冲突", prompt)

    def test_multi_disease_keeps_specialist_reports_and_grouped_evidence(self):
        analysis = EyeAnalysis(diseases={
            "glaucoma": DiseaseResult(probability=.8),
            "diabetic_retinopathy": DiseaseResult(prompt_similarity_margin=1.2),
        })
        plan = make_plan(questions=(
            RetrievalQuestion("本病例青光眼如何判读？", "interpretation",
                              filters={"disease": "glaucoma"}),
            RetrievalQuestion("本病例糖网如何分期？", "interpretation",
                              filters={"disease": "diabetic_retinopathy"}),
        ))
        items = [
            evidence(1, source="cn-glaucoma-2020", text="青光眼视野判读依据。"),
            evidence(2, source="cn-dr-2022", id="e2", text="糖尿病视网膜病变分期依据。"),
        ]
        questions = [
            QuestionResult(question=plan.questions[0].question, topic="interpretation",
                           disease="glaucoma", answered=True, evidence_ids=["e1"]),
            QuestionResult(question=plan.questions[1].question, topic="interpretation",
                           disease="diabetic_retinopathy", answered=True, evidence_ids=["e2"]),
        ]
        outcome = make_outcome(items, questions=questions, queries=2)
        generator = MedicalReportGenerator(api_key="test")

        def reply(prompt, **kwargs):
            if "As a Glaucoma Specialist" in prompt:
                return "青光眼判读 [1]。"
            if "As a Diabetic Retinopathy Specialist" in prompt:
                return "糖网分期 [2]。"
            return "综合报告 [1][2]。"

        generator.chat_with_gpt = Mock(side_effect=reply)
        with tempfile.TemporaryDirectory() as folder, \
             patch("modules.vision.analyze_fundus", return_value=analysis), \
             patch.object(config, "VERIFY_ENABLED", False), \
             patch.object(RetrievalPlanner, "plan", return_value=plan), \
             patch("modules.report.generation.retrieve_for_plan", return_value=outcome):
            result = generator.generate_v2(
                io.BytesIO(b"image"), self.note, Path(folder),
                diseases=("glaucoma", "diabetic_retinopathy"), laterality="right",
            )
        self.assertEqual(result.summary, "综合报告 [1][2]。")
        prompts = [call.args[0] for call in generator.chat_with_gpt.call_args_list]
        self.assertTrue(any("Glaucoma Specialist Report:" in prompt for prompt in prompts))
        self.assertTrue(any("Diabetic Retinopathy Specialist Report:" in prompt for prompt in prompts))


class PipelineSwitchTests(unittest.TestCase):
    result = ("summary", {"status": "pass"}, None, "", [], {})

    def test_v2_pipeline_uses_generate_v2(self):
        generator = Mock()
        generator.generate_v2.return_value = self.result
        with patch.object(config, "REPORT_PIPELINE", "v2"):
            outcome = asyncio.run(service._run_report_pipeline(
                generator, b"image", "note", Path("job"), ("glaucoma",),
                laterality="right", filename="eye.png",
            ))
        self.assertEqual(outcome, self.result)
        generator.generate_v2.assert_called_once()
        self.assertEqual(generator.generate_v2.call_args.kwargs["laterality"], "right")
        generator.generate.assert_not_called()

    def test_legacy_pipeline_is_still_available(self):
        generator = Mock()
        generator.generate.return_value = self.result
        with patch.object(config, "REPORT_PIPELINE", "legacy"):
            outcome = asyncio.run(service._run_report_pipeline(
                generator, b"image", "note", Path("job"), ("glaucoma",),
            ))
        self.assertEqual(outcome, self.result)
        generator.generate.assert_called_once()
        generator.generate_v2.assert_not_called()

    def test_unknown_pipeline_value_is_rejected_at_startup(self):
        env = dict(os.environ)
        env["REPORT_PIPELINE"] = "v1"
        result = subprocess.run(
            [sys.executable, "-c", "from core import config"],
            cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("REPORT_PIPELINE", result.stderr)




class AcceptanceRegressionTests(unittest.TestCase):
    def test_fabrication_cannot_be_soft_delivered(self):
        from modules.agent.verifier import CitationVerifier
        text = "右眼眼压99 mmHg。"
        reply = json.dumps({"claims": [{"quote": text, "citations": [], "impact": "core",
                            "verdict": "unsupported", "basis": "medical_knowledge",
                            "reason": "资料未覆盖"}], "grounding": []})
        verifier = CitationVerifier(lambda *args, **kwargs: reply, case_context="右眼眼压26 mmHg。")
        draft, record = verifier.execute(text, [evidence()], max_rounds=0)
        self.assertIsNone(draft)
        self.assertNotIn(record["status"], ("pass", "rewritten"))

    def test_eye_values_remain_attached_to_their_source(self):
        facts = build_case_facts({}, "右眼眼压20 mmHg，左眼眼压30 mmHg。")
        values = [(f.eye, f.numbers) for f in facts.facts if f.source == "clinical_note"]
        self.assertEqual(values, [("right", ("20",)), ("left", ("30",))])
        self.assertTrue(lateral_mismatch_issues("左眼眼压20 mmHg。",
                        [{"eye": "right", "numbers": ["20"]}], []))

    def test_clause_with_stated_preconditions_stays_usable(self):
        """条款写明前提与例外不是排除理由：条款保留，前提进证据、快照与提示词。"""
        clause = evidence(topic="followup", applicability={
            "population": "已确诊开角型青光眼患者",
            "care_stage": "随访",
            "preconditions": "已建立结构与功能基线",
            "exclusions": "急性眼压升高需先行处理",
        })
        outcome = retrieve_for_plan(make_plan(), diseases=("glaucoma",),
                                    retriever=FakeRetriever([[clause]]), budget=BUDGET)
        self.assertEqual(outcome.status, "ok")
        self.assertEqual([item["id"] for item in outcome.evidence], [clause["id"]])
        adopted = outcome.evidence[0]
        # 未核实的适用条件是「必须写明的前提」，不是「不能用」。
        self.assertIn("preconditions", adopted["applicability_unknown"])
        self.assertEqual(adopted["snapshot"]["applicability"]["preconditions"],
                         "已建立结构与功能基线")
        block = format_evidence_block(outcome.evidence)
        self.assertIn("前提条件：已建立结构与功能基线", block)
        self.assertIn("未核实", block)

    def test_newly_adopted_premises_are_reported_as_gaps_not_exclusions(self):
        """需要补检的是「没检索到」，不是「条款写了前提」：不适用理由里不应出现它。"""
        clause = evidence(topic="followup", applicability={"preconditions": "已建立基线"})
        outcome = retrieve_for_plan(make_plan(), diseases=("glaucoma",),
                                    retriever=FakeRetriever([[clause]]), budget=BUDGET)
        reasons = {item["reason"] for item in outcome.questions[0].excluded}
        self.assertNotIn("applicability_unknown", reasons)
        self.assertTrue(outcome.questions[0].answered)

    def test_legacy_clause_keeps_unknown_review_status(self):
        old = evidence(topic="followup")
        del old["review_status"]
        outcome = retrieve_for_plan(make_plan(), diseases=("glaucoma",),
                                    retriever=FakeRetriever([[old]]), budget=BUDGET)
        self.assertEqual(outcome.evidence[0]["snapshot"]["review_status"], "unknown")


if __name__ == "__main__":
    unittest.main()
