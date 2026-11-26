"""VERIFY_MAX_ROUNDS 档位实测：3/4/5/6/7。

固定同一病例与同一模型，只改轮数上限，记录核查过程与最终报告。
测试口径见 docs/轮数测试标准.md。

运行（启动前覆盖 NO_PROXY，不改系统设置）：
    $env:NO_PROXY='localhost,127.0.0.1,::1'
    $env:RAG_MODE='bm25'
    python tools/rounds_experiment.py
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# httpx 会把 NO_PROXY 的每一项当成 URL 模式解析，[::1] 这种方括号形式会抛
# InvalidURL，导致所有 LLM 调用在建客户端时就失败。这里只在本进程内修正，
# 不改系统设置。
for _name in ("NO_PROXY", "no_proxy"):
    _value = os.environ.get(_name)
    if _value:
        os.environ[_name] = ",".join(
            part for part in _value.split(",")
            if part.strip() and not part.strip().startswith("[")
        )

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / "backend" / ".env")

from core.config_impl as config  # noqa: E402

# 核查与改写提示词约 6k 字符，deepseek-v4.1-flash 实测单次 40-60s，偶发超过默认
# 120s。这里放宽到 300s，使实验测的是「轮数上限」而不是「超时阈值」。
config.LLM_TIMEOUT = float(os.getenv("EXP_LLM_TIMEOUT", "300"))

from modules.report.generation import MedicalReportGenerator  # noqa: E402
from modules.report.context import format_visual_findings  # noqa: E402
from modules.agent.tools.text_revision import content_len  # noqa: E402

ROUNDS = [2, 3, 4, 5, 6, 7]
IMAGE = ROOT / "samples" / "fundus_right_eye.png"
NOTE = (ROOT / "samples" / "clinical_note.txt").read_text(encoding="utf-8")


class CountingClient(MedicalReportGenerator):
    """统计每次 LLM 调用与单次耗时，便于计算真实成本。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = 0
        self.durations: list[float] = []

    def chat_with_gpt(self, *args, **kwargs):  # type: ignore[override]
        self.calls += 1
        started = time.time()
        try:
            return super().chat_with_gpt(*args, **kwargs)
        finally:
            self.durations.append(time.time() - started)


def cited_numbers(text: str) -> set[int]:
    return {int(n) for n in re.findall(r"\[(\d+)\]", text or "")}


def has_sections(text: str) -> dict[str, bool]:
    """粗略判断三类内容是否在场：评估、依据、下一步。"""
    return {
        "评估": any(k in text for k in ("评估", "结论", "诊断", "考虑", "提示")),
        "依据": any(k in text for k in ("依据", "所见", "检查", "视野", "眼压", "杯盘比")),
        "下一步": any(k in text for k in ("建议", "复查", "随访", "下一步", "转诊")),
    }


def run_one(rounds: int) -> dict:
    config.VERIFY_MAX_ROUNDS = rounds
    client = CountingClient(
        api_key=os.getenv("OPENAI_API_KEY"),
        model=os.getenv("OPENAI_MODEL"),
        base_url=os.getenv("OPENAI_BASE_URL"),
    )
    job_dir = ROOT / "backend" / "output" / "rounds_exp" / f"r{rounds}"
    job_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    try:
        result = client.generate(IMAGE, NOTE, job_dir, diseases=("glaucoma",))
        error = None
    except Exception as exc:  # noqa: BLE001 - 单档失败不应中断整轮实验
        result, error = None, f"{type(exc).__name__}: {exc}"
    elapsed = time.time() - started

    if result is None:
        return {"rounds_limit": rounds, "error": error, "calls": client.calls,
                "seconds": elapsed}

    summary, verification, ratio, seg, evidence, findings = result
    allowed = {int(item.get("index", i)) for i, item in enumerate(evidence, 1)}
    cited = cited_numbers(summary or "")
    sections = has_sections(summary or "")
    limited = verification.get("status") == "limited"
    degraded = bool(summary) and "病例资料摘要" in summary
    deliverable = bool(summary) and not limited and not degraded and verification.get(
        "status") in ("pass", "rewritten")
    return {
        "rounds_limit": rounds,
        "status": verification.get("status"),
        "reason": verification.get("reason"),
        "rounds": verification.get("rounds"),
        "initial_issues": verification.get("initial_issues"),
        "remaining": len(verification.get("remaining_issues") or []),
        "fixed": len(verification.get("fixed") or []),
        "deleted": verification.get("deleted", 0),
        "regenerated": bool(verification.get("regenerated")),
        "calls": client.calls,
        "call_times": [round(d, 1) for d in client.durations],
        "max_call": round(max(client.durations), 1) if client.durations else 0,
        "seconds": elapsed,
        "chars": content_len(summary or ""),
        "cited": sorted(cited),
        "unknown_citations": sorted(cited - allowed),
        "sections": sections,
        "evidence": len(evidence),
        "degraded": degraded,
        "deliverable": deliverable,
        "summary": summary or "",
        "visual_findings": format_visual_findings(findings),
        "ratio": ratio,
        "remaining_issues": verification.get("remaining_issues") or [],
    }


def main() -> None:
    print(f"model={os.getenv('OPENAI_MODEL')}  mode={config.RAG_MODE}  "
          f"evidence_topk={config.RAG_TOP_K}")
    print(f"note={len(NOTE)} chars  image={IMAGE.name}")
    results = []
    for rounds in ROUNDS:
        print(f"\n>>> 开始 VERIFY_MAX_ROUNDS={rounds}")
        record = run_one(rounds)
        results.append(record)
        if record.get("error"):
            print(f"    失败：{record['error']}")
        else:
            print(f"    status={record['status']} rounds={record['rounds']} "
                  f"calls={record['calls']} {record['seconds']:.1f}s "
                  f"chars={record['chars']} 可交付={record['deliverable']}")
    out = ROOT / "backend" / "output" / "rounds_exp" / "results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已写入 {out}")


if __name__ == "__main__":
    main()