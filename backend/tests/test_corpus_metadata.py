"""条款元数据与筛选的离线回归。

只验证数据契约：旧条款缺失字段时不能自动变成「已审核」，材料类型不足以支持
诊疗主题时必须被排除，条款级病种范围优先于来源登记。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.knowledge.corpus import evidence_chunks, load_guideline
from modules.knowledge.metadata import (
    clause_fit,
    filter_evidence,
    matches_case_disease,
    resolve_material_type,
    resolve_review_status,
    resolve_topic,
)


class CorpusMetadataTests(unittest.TestCase):
    def write(self, folder: Path, payload: dict) -> Path:
        path = folder / "fixture.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def payload(self, **evidence_extra) -> dict:
        row = {
            "id": "fixture-clause", "source": "cn-fixture-source",
            "section": "诊断", "scope": "测试用适用范围", "text": "测试条款正文。",
        }
        row.update(evidence_extra)
        return {
            "schema_version": 1,
            "sources": {"cn-fixture-source": {
                "title": "测试来源", "version": "v1", "jurisdiction": "CN",
                "url": "https://example.org/source",
            }},
            "evidence": [row],
        }

    def test_legacy_clause_has_unknown_review_status_not_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write(Path(folder), self.payload())
            chunks = evidence_chunks(load_guideline(path))
        chunk = chunks[0]
        item = {"source": chunk.source, "material_type": chunk.material_type,
                "review_status": chunk.review_status}
        # 缺失状态明确为 unknown；材料类型按已知来源前缀登记，但审核状态不推断。
        self.assertEqual(resolve_review_status(item), "unknown")
        self.assertEqual(resolve_material_type(item), "guideline")
        self.assertTrue(item["review_status"] == "" or item["review_status"] == "unknown")

    def test_source_level_metadata_fills_missing_clause_fields(self):
        payload = self.payload()
        payload["sources"]["cn-fixture-source"].update({
            "material_type": "patient_education", "review_status": "pending",
            "disease": ["glaucoma"],
        })
        with tempfile.TemporaryDirectory() as folder:
            chunk = evidence_chunks(load_guideline(self.write(Path(folder), payload)))[0]
        self.assertEqual(chunk.material_type, "patient_education")
        self.assertEqual(chunk.review_status, "pending")
        self.assertEqual(chunk.disease, "glaucoma")

    def test_invalid_metadata_value_is_rejected_at_load(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write(Path(folder), self.payload(review_status="approved"))
            with self.assertRaises(ValueError):
                load_guideline(path)

    def test_clause_disease_scope_overrides_source_registry(self):
        clause = {"source": "cn-glaucoma-2020", "disease": "diabetic_retinopathy"}
        self.assertTrue(matches_case_disease(clause, "diabetic_retinopathy"))
        self.assertFalse(matches_case_disease(clause, "glaucoma"))
        generic = {"source": "unregistered-source"}
        self.assertTrue(matches_case_disease(generic, "glaucoma"))

    def test_patient_education_cannot_support_treatment_topic(self):
        education = {"id": "edu", "source": "nei-amd", "text": "患者教育内容",
                     "material_type": "patient_education"}
        guideline = {"id": "guide", "source": "cn-amd-2023", "text": "指南内容",
                     "material_type": "guideline"}
        accepted, rejected = filter_evidence([education, guideline], topic="treatment")
        self.assertEqual([item["id"] for item in accepted], ["guide"])
        self.assertEqual(rejected[0]["reason"], "material_type")
        accepted, _ = filter_evidence([education], topic="education")
        self.assertEqual([item["id"] for item in accepted], ["edu"])

    def test_missing_applicability_is_recorded_not_assumed(self):
        item = {"id": "guide", "source": "cn-amd-2023", "material_type": "guideline"}
        accepted, rejected = filter_evidence(
            [item], topic="treatment", filters={"population": "成人"},
        )
        self.assertEqual(accepted[0]["applicability_unknown"], ["population"])
        self.assertFalse(rejected)

    def test_applicability_mismatch_excludes_clause(self):
        item = {
            "id": "pediatric", "source": "cn-amd-2023", "material_type": "guideline",
            "applicability": {"population": "儿童"},
        }
        accepted, rejected = filter_evidence(
            [item], topic="treatment", filters={"population": "成人"},
        )
        self.assertFalse(accepted)
        self.assertEqual(rejected[0]["reason"], "applicability")

    def test_stated_preconditions_do_not_disqualify_a_clause(self):
        """条款登记了前提与例外，是可用性更强的证据，不是不可用。"""
        item = {
            "id": "clause", "source": "cn-glaucoma-2020", "material_type": "guideline",
            "applicability": {"preconditions": "已确诊并完成基线评估", "exclusions": "妊娠期"},
        }
        fit = clause_fit(item, "treatment", {"disease": "glaucoma"})
        self.assertTrue(fit["ok"])
        self.assertEqual(fit["unknown"], ["preconditions", "exclusions"])
        accepted, rejected = filter_evidence([item], topic="treatment", filters={"disease": "glaucoma"})
        self.assertEqual([entry["id"] for entry in accepted], ["clause"])
        self.assertFalse(rejected)
        # 未核实的条件必须随证据带出去，不能被当作已满足。
        self.assertIn("preconditions", accepted[0]["applicability_unknown"])

    def test_clause_fit_excludes_only_contradicted_applicability(self):
        item = {
            "id": "pediatric", "source": "cn-amd-2023", "material_type": "guideline",
            "applicability": {"population": "儿童"},
        }
        fit = clause_fit(item, "treatment", {"population": "成人"})
        self.assertFalse(fit["ok"])
        self.assertEqual(fit["reason"], "applicability")
        self.assertEqual(fit["mismatch"], ["population"])

    def test_topic_is_inferred_from_section_for_reporting(self):
        self.assertEqual(resolve_topic({"section": "随访与监测"}), "followup")
        self.assertEqual(resolve_topic({"section": "Differential diagnosis"}), "differential")
        self.assertEqual(resolve_topic({"section": "任意"}), "")


if __name__ == "__main__":
    unittest.main()
