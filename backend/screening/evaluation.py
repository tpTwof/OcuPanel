"""Paired evaluation of locked decisions; never chooses a clinical threshold.

Bootstrap samples patients, keeping their eyes and repeat examinations together.
Abstentions and unknown reference outcomes remain visible in every denominator.
"""
from collections import defaultdict
import math
import random
from typing import Any

DECISIONS = {"refer", "no_refer", "abstain"}


def validate_rows(rows: list[dict[str, Any]]) -> None:
    patients: dict[str, str] = {}
    seen: set[tuple] = set()
    for row in rows:
        if "verification_probability" in row:
            probability = row["verification_probability"]
            if (type(probability) not in (int, float) or not math.isfinite(probability)
                    or not 0 < probability <= 1 or type(row.get("selected_for_verification")) is not bool):
                raise ValueError("Sampling requires a known positive inclusion probability and a selection flag")
            if not row["selected_for_verification"] and (probability == 1 or row["reference"] != "unknown"):
                raise ValueError("Unsampled records must have unknown reference and probability below one")
        for field in ("patient_id", "encounter_id", "eye", "task", "institution", "device", "split", "reference", "old", "candidate"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"Missing field: {field}")
        if row["eye"] not in {"right", "left"} or row["split"] not in {"development", "calibration", "test"}:
            raise ValueError("Invalid eye or split")
        if row["reference"] not in {"refer", "no_refer", "unknown"}:
            raise ValueError("Invalid reference label")
        if row["old"] not in DECISIONS or row["candidate"] not in DECISIONS:
            raise ValueError("Invalid method decision")
        for method in ("old", "candidate"):
            if row.get(f"{method}_workflow", "pending") not in {"refer", "no_refer", "pending"}:
                raise ValueError("Invalid final workflow decision")
        patient = row["patient_id"]
        if patient in patients and patients[patient] != row["split"]:
            raise ValueError(f"Patient split leakage: {patient}")
        patients[patient] = row["split"]
        key = (patient, row["encounter_id"], row["eye"], row["task"])
        if key in seen:
            raise ValueError(f"Duplicate eye/task: {key}")
        seen.add(key)


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def metrics(rows: list[dict], method: str) -> dict:
    known = [row for row in rows if row["reference"] != "unknown"]
    decided = [row for row in known if row[method] != "abstain"]
    tp = sum(row["reference"] == "refer" and row[method] == "refer" for row in decided)
    fn = sum(row["reference"] == "refer" and row[method] == "no_refer" for row in decided)
    tn = sum(row["reference"] == "no_refer" and row[method] == "no_refer" for row in decided)
    fp = sum(row["reference"] == "no_refer" and row[method] == "refer" for row in decided)
    positives = [row for row in known if row["reference"] == "refer"]
    workflow_field = f"{method}_workflow"
    missed = sum(row.get(workflow_field) == "no_refer" for row in positives)
    pending = sum(row.get(workflow_field, "pending") == "pending" for row in positives)
    return {"total": len(rows), "reference_known": len(known), "reference_unknown": len(rows) - len(known),
            "tp": tp, "fn": fn, "tn": tn, "fp": fp,
            "abstained": sum(row[method] == "abstain" for row in rows),
            "abstained_reference_positive": sum(row[method] == "abstain" for row in positives),
            "coverage": _ratio(sum(row[method] != "abstain" for row in rows), len(rows)),
            "sensitivity_on_decided": _ratio(tp, tp + fn), "specificity_on_decided": _ratio(tn, tn + fp),
            "review_load": sum(row[method] in {"refer", "abstain"} for row in rows),
            "reference_positive": len(positives), "workflow_missed": missed,
            "workflow_positive_pending": pending,
            "workflow_miss_rate": _ratio(missed, len(positives)) if not pending else None,
            "workflow_miss_rate_bounds": [_ratio(missed, len(positives)), _ratio(missed + pending, len(positives))]}


def _interval(values: list[float]) -> list[float] | None:
    if not values:
        return None
    values.sort()
    return [values[int((len(values) - 1) * .025)], values[int((len(values) - 1) * .975)]]


def evaluate_group(rows: list[dict], repeats: int) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["patient_id"]].append(row)
    result = {method: metrics(rows, method) for method in ("old", "candidate")}
    if any("verification_probability" in row for row in rows):
        if not all("verification_probability" in row for row in rows):
            raise ValueError("All records in a sampled cohort require the sampling design")
        sampled = [row for row in rows if row["selected_for_verification"]]
        positives = [row for row in sampled if row["reference"] == "refer"]
        missing = sum(row["reference"] == "unknown" for row in sampled)
        weighted = {"selected": len(sampled), "selected_missing_reference": missing}
        for method in ("old", "candidate"):
            field = f"{method}_workflow"
            denominator = sum(1 / row["verification_probability"] for row in positives)
            missed = sum(1 / row["verification_probability"] for row in positives if row.get(field) == "no_refer")
            complete = not missing and all(row.get(field) in {"refer", "no_refer"} for row in positives)
            weighted[method + "_miss_rate"] = missed / denominator if complete and denominator else None
        result["verification_weighted"] = weighted
    fields = ("sensitivity_on_decided", "specificity_on_decided", "coverage", "workflow_miss_rate")
    samples = {method: {field: [] for field in fields} for method in ("old", "candidate", "candidate_minus_old")}
    rng = random.Random(20261124)
    patient_ids = sorted(groups)
    # One patient cannot estimate between-patient uncertainty.
    if len(patient_ids) >= 2:
        for _ in range(repeats):
            drawn = [row for patient in rng.choices(patient_ids, k=len(patient_ids)) for row in groups[patient]]
            pair = {method: metrics(drawn, method) for method in ("old", "candidate")}
            for field in fields:
                for method in ("old", "candidate"):
                    if result[method][field] is not None and pair[method][field] is not None:
                        samples[method][field].append(pair[method][field])
                if all(result[method][field] is not None and pair[method][field] is not None
                       for method in ("old", "candidate")):
                    samples["candidate_minus_old"][field].append(pair["candidate"][field] - pair["old"][field])
    result["patient_count"] = len(patient_ids)
    result["patient_bootstrap_95_ci"] = {method: {field: {"interval": _interval(values), "valid_resamples": len(values)}
                                                        for field, values in metrics_samples.items()}
                                           for method, metrics_samples in samples.items()}
    return result


def evaluate(rows: list[dict], manifest: dict, repeats: int = 1000) -> dict:
    validate_rows(rows)
    if not 100 <= repeats <= 10000:
        raise ValueError("Bootstrap repeats must be between 100 and 10000")
    for field in ("old_version", "candidate_version", "reference_standard", "locked_workpoints", "dataset_version"):
        if not manifest.get(field):
            raise ValueError(f"Evaluation manifest missing: {field}")
    test = [row for row in rows if row["split"] == "test"]
    if not test:
        raise ValueError("No independent test records supplied")
    strata: dict[str, list[dict]] = defaultdict(list)
    for row in test:
        strata[f"task:{row['task']}"].append(row)
        strata[f"task:{row['task']}|institution:{row['institution']}|device:{row['device']}"].append(row)
    return {"schema_version": 1, "manifest": manifest, "bootstrap_repeats": repeats,
            "notes": ["仅计算已锁定工作点的配对结果；不证明临床放行或机构独立性。",
                      "灵敏度和特异度以有参考标准且未弃判的记录计算，须与弃判量及覆盖率一同查看。",
                      "流程漏转率使用参考标准确认应转者为分母；有待决去向时仅给上下界。未知参考结局单列。",
                      "按患者整组重采样；单患者子组不提供区间。小样本或退化区间不代表完成验证。"],
            "strata": {name: evaluate_group(group, repeats) for name, group in sorted(strata.items())}}
