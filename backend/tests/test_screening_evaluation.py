from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screening.evaluation import evaluate, metrics, validate_rows


def row(patient, reference="refer", old="no_refer", candidate="refer", **kwargs):
    return {"patient_id": patient, "encounter_id": "e1", "eye": "right", "task": "glaucoma",
            "institution": "test-clinic", "device": "test-device", "split": "test", "reference": reference,
            "old": old, "candidate": candidate, **kwargs}


class EvaluationTests(unittest.TestCase):
    def test_multidisease_verification_sampling_fixture(self):
        import json
        fixture = Path(__file__).resolve().parents[2] / "tools/screening-evaluation.example.json"
        data = json.loads(fixture.read_text(encoding="utf8"))
        results = evaluate(data["rows"], data["manifest"], 100)
        for task in ("diabetic_retinopathy", "dme", "age_related_macular_degeneration"):
            weighted = results["strata"]["task:" + task]["verification_weighted"]
            self.assertAlmostEqual(weighted["old_miss_rate"], 2 / 3)
            self.assertEqual(weighted["candidate_miss_rate"], 0)

    def test_abstention_and_unknown_are_not_negative(self):
        rows = [row("p1", candidate="abstain"), row("p2", reference="unknown"),
                row("p3", old_workflow="no_refer", candidate_workflow="refer")]
        result = metrics(rows, "candidate")
        self.assertEqual(result["reference_unknown"], 1)
        self.assertEqual(result["abstained_reference_positive"], 1)
        self.assertEqual(result["fn"], 0)
        self.assertIsNone(result["workflow_miss_rate"])
        self.assertEqual(result["workflow_miss_rate_bounds"], [0, .5])

    def test_bilateral_and_repeat_visits_stay_with_patient(self):
        rows = [row("p1"), row("p1", eye="left", split="calibration")]
        with self.assertRaisesRegex(ValueError, "leakage"):
            validate_rows(rows)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_rows([row("p1"), row("p1")])

    def test_paired_bootstrap_is_reproducible_and_stratified(self):
        rows = [row("p1"), row("p1", eye="left"), row("p2", reference="no_refer", old="refer", candidate="no_refer")]
        manifest = {field: "synthetic" for field in ("old_version", "candidate_version", "reference_standard", "locked_workpoints", "dataset_version")}
        result = evaluate(rows, manifest, 100)
        self.assertEqual(result, evaluate(rows, manifest, 100))
        group = result["strata"]["task:glaucoma"]
        self.assertEqual(group["patient_count"], 2)
        self.assertEqual(group["candidate"]["sensitivity_on_decided"], 1)
        self.assertEqual(group["old"]["sensitivity_on_decided"], 0)
        self.assertIn("candidate_minus_old", group["patient_bootstrap_95_ci"])
        self.assertIsNone(group["patient_bootstrap_95_ci"]["candidate"]["workflow_miss_rate"]["interval"])

    def test_zero_denominators_are_missing_not_perfect(self):
        result = metrics([row("p1", reference="unknown")], "candidate")
        self.assertIsNone(result["sensitivity_on_decided"])
        self.assertIsNone(result["specificity_on_decided"])
        self.assertIsNone(result["workflow_miss_rate"])


if __name__ == "__main__":
    unittest.main()
