"""Summarize one rehearsal site's operations over an explicit observation window."""
import argparse
from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from utils import storage


def percentile95(values):
    return sorted(values)[math.ceil(len(values) * .95) - 1] if values else None


def summarize(site, start, end, model_version=None, total_cost=None):
    if start >= end or (total_cost is not None and (not math.isfinite(total_cost) or total_cost < 0)):
        raise ValueError("Invalid observation window or cost")
    waits, latencies, reread = [], [], []
    jobs, receipts = Counter(), Counter()
    signed = 0
    patient_statuses = {}
    with storage.connect() as conn:
        if not conn.execute("SELECT 1 FROM screening_sites WHERE organization=?", (site,)).fetchone():
            raise ValueError("Unknown site")
        for row in conn.execute("SELECT j.*,r.visual_findings FROM report_jobs j LEFT JOIN reports r ON j.id=r.id "
                                "WHERE organization=? AND j.created_at>=? AND j.created_at<?", (site, start, end)):
            ended = row["finished_at"] is not None and row["finished_at"] < end
            began = row["started_at"] is not None and row["started_at"] < end
            jobs[row["state"] if ended else "running" if began else "queued"] += 1
            if began:
                waits.append(row["started_at"] - row["created_at"])
            if ended:
                latencies.append(row["finished_at"] - row["created_at"])
            if model_version and ended and row["visual_findings"]:
                findings = json.loads(row["visual_findings"])
                sources = (source for finding in findings.values() for source in finding.get("model_sources", {}).values())
                if any(isinstance(source, str) and model_version in (source, source.rsplit("@", 1)[-1]) for source in sources):
                    reread.append(row["id"])
        for row in conn.execute("SELECT snapshot FROM screening_cases WHERE organization=?", (site,)):
            case = json.loads(row["snapshot"])
            signed += sum(event["action"] == "sign" and start <= event["at"] < end for event in case["events"])
            for ref in case["referrals"]:
                if not start <= ref["created_at"] < end:
                    continue
                state = "waiting"
                for receipt in ref["receipts"]:
                    if receipt["at"] < end:
                        state = receipt["status"]
                receipts[state] += 1
                patient_statuses.setdefault(case["examination"]["patient_group"], set()).add(state)
    return {"site": site, "from": start, "until_exclusive": end, "jobs": dict(jobs),
            "queue_wait_p95_seconds": percentile95(waits), "end_to_end_p95_seconds": percentile95(latencies),
            "referrals_by_status": dict(receipts), "referred_patients": len(patient_statuses),
            "patients_with_arrival": sum("arrived" in states for states in patient_statuses.values()),
            "simulated_signatures": signed, "cost_per_signature": total_cost / signed if signed and total_cost is not None else None,
            "matched_report_ids": reread}


def timestamp(value):
    dt = datetime.fromisoformat(value)
    if dt.utcoffset() is None:
        raise argparse.ArgumentTypeError("Include the UTC offset")
    return dt.timestamp()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site")
    parser.add_argument("--start", type=timestamp, required=True)
    parser.add_argument("--end", type=timestamp, required=True)
    parser.add_argument("--model-version")
    parser.add_argument("--total-cost", type=float)
    args = parser.parse_args()
    print(json.dumps(summarize(args.site, args.start, args.end, args.model_version, args.total_cost), ensure_ascii=False, indent=2))
