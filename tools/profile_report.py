"""报告生成耗时剖析：定位热点（用完即删）。

按阶段计时：视觉分析、检索、专科撰稿、Director 综合、Verifier 核查/改写。
同时记录每次 LLM 调用的耗时与提示词长度，找出真正的时间去哪了。
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
for _n in ("NO_PROXY", "no_proxy"):
    _v = os.environ.get(_n)
    if _v:
        os.environ[_n] = ",".join(p for p in _v.split(",") if p.strip() and not p.strip().startswith("["))

from dotenv import load_dotenv
load_dotenv(ROOT / "backend" / ".env")

import json
from core import config_impl as config

config.LLM_TIMEOUT = 300.0

calls: list[dict] = []


def instrument():
    """包装 LLMClient 调用，记录耗时与提示词规模。"""
    from core.llm.client import LLMClient

    original = LLMClient.chat_with_gpt

    def wrapper(self, user_message, conversation=False, reset=True, system=None,
                temperature=None):
        prompt_chars = len(user_message or "") + len(system or "")
        t = time.time()
        out = original(self, user_message, conversation=conversation, reset=reset,
                       system=system, temperature=temperature)
        calls.append({
            "seconds": round(time.time() - t, 1),
            "prompt_chars": prompt_chars,
            "temp": temperature,
            "ok": not str(out).startswith("Error:"),
            "out_chars": len(str(out)),
        })
        return out

    LLMClient.chat_with_gpt = wrapper


def main():
    from modules.report.generation import MedicalReportGenerator
    from modules.vision import analyze_fundus

    image = ROOT / "samples" / "fundus_right_eye.png"
    note = (ROOT / "samples" / "clinical_note.txt").read_text(encoding="utf-8")

    print("=" * 68)
    print("阶段计时")
    print("=" * 68)

    t = time.time()
    analysis = analyze_fundus(image, diseases=("glaucoma",))
    vision_s = time.time() - t
    print(f"  ① 视觉分析          {vision_s:6.1f}s")

    # 检索单独计时
    from modules.knowledge.report_focus import disease_focus
    from modules.knowledge.service import retrieve_evidence
    from modules.report.context import build_context

    ctx = build_context({"glaucoma": analysis.diseases["glaucoma"]}, note)
    t = time.time()
    evidence = retrieve_evidence(ctx, boost=disease_focus("glaucoma"), disease="glaucoma")
    retrieval_s = time.time() - t
    print(f"  ② 检索({len(evidence)}条)        {retrieval_s:6.1f}s")

    instrument()
    gen = MedicalReportGenerator(
        api_key=os.getenv("OPENAI_API_KEY"),
        model=os.getenv("OPENAI_MODEL"),
        base_url=os.getenv("OPENAI_BASE_URL"),
    )
    from unittest.mock import patch
    # 复用已算好的分析，避免重复跑视觉模型
    with patch("modules.vision.analyze_fundus", return_value=analysis):
        t = time.time()
        result = gen.generate(image, note, ROOT / "backend" / "output" / "profile",
                              diseases=("glaucoma",))
        total_s = time.time() - t

    summary, verification, ratio, seg, ev, findings = result

    print(f"  ③ 撰稿+核查(含②)   {total_s:6.1f}s")
    print(f"  合计                {vision_s + total_s:6.1f}s")
    print()
    print(f"  状态: {verification.get('status')}  轮数: {verification.get('rounds')}  "
          f"正文字数: {len(summary or '')}")

    print()
    print("=" * 68)
    print(f"LLM 调用明细（共 {len(calls)} 次，合计 {sum(c['seconds'] for c in calls):.1f}s）")
    print("=" * 68)
    print(f"  {'#':>2} {'耗时':>7} {'提示词字符':>10} {'输出字符':>8}  temp")
    for i, c in enumerate(calls, 1):
        print(f"  {i:>2} {c['seconds']:>6.1f}s {c['prompt_chars']:>10} "
              f"{c['out_chars']:>8}  {c['temp']}")
    avg = sum(c["seconds"] for c in calls) / max(len(calls), 1)
    print(f"\n  单次平均 {avg:.1f}s，最长 {max(c['seconds'] for c in calls):.1f}s，"
          f"最短 {min(c['seconds'] for c in calls):.1f}s")
    print(f"  提示词平均 {sum(c['prompt_chars'] for c in calls)//max(len(calls),1)} 字符")

    out = ROOT / "backend" / "output" / "profile" / "timing.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "vision_s": round(vision_s, 1), "retrieval_s": round(retrieval_s, 1),
        "total_s": round(total_s, 1), "calls": calls,
        "status": verification.get("status"), "rounds": verification.get("rounds"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n明细写入 {out}")


if __name__ == "__main__":
    main()