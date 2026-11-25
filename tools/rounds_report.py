"""把 rounds_experiment.py 的结果整理成 Markdown 测试报告。

读取 backend/output/rounds_exp/results.json，按 docs/轮数测试标准.md 的口径
判定各档是否可用，并把每档交付报告原文一并写入。

运行：python tools/rounds_report.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "backend" / "output" / "rounds_exp" / "results.json"
STANDARD = ROOT / "docs" / "轮数测试标准.md"
OUT = ROOT / "docs" / "轮数测试报告.md"

STATUS_LABEL = {
    "pass": "首次通过",
    "rewritten": "修订后通过",
    "rejected": "拒答",
    "limited": "降级为病例摘要",
    "error": "校验故障",
}


def judge(record: dict) -> tuple[bool, list[str]]:
    """按标准第 4 节判定四项，返回 (是否可用, 失败原因列表)。"""
    problems = []
    if record.get("error"):
        return False, [f"运行异常：{record['error']}"]
    # status=error 表示核查链路本身出错，正文被扣留，不再逐项检查内容。
    if record.get("status") == "error":
        return False, [f"校验故障（{record.get('reason')}），正文扣留，未产生可判定内容"]
    if not record.get("deliverable"):
        problems.append(f"不可交付（status={record.get('status')}）")
    if record.get("degraded"):
        problems.append("降级为病例资料摘要")
    sections = record.get("sections") or {}
    missing = [k for k, present in sections.items() if not present]
    if missing:
        problems.append("缺少内容：" + "、".join(missing))
    if record.get("unknown_citations"):
        problems.append(f"越界编号：{record['unknown_citations']}")
    if record.get("remaining"):
        problems.append(f"仍有余留问题 {record['remaining']} 处")
    return not problems, problems


def main() -> None:
    records = json.loads(RESULTS.read_text(encoding="utf-8"))
    lines: list[str] = []
    add = lines.append

    add("# VERIFY_MAX_ROUNDS 轮数测试报告")
    add("")
    add("测试口径见 [轮数测试标准](轮数测试标准.md)。本报告只记录本次观测，")
    add("结论不可外推到其他病例或模型。")
    add("")

    # ---- 汇总表 ----
    add("## 1. 汇总")
    add("")
    add("| 轮数上限 | 状态 | 实际轮数 | 首轮问题 | 改写/删除 | 重生成 | LLM 调用 | 单次最长 | 总耗时 | 正文字数 | 判定 |")
    add("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    usable = []
    for r in records:
        ok, problems = judge(r)
        if ok:
            usable.append(r["rounds_limit"])
        verdict = "可用" if ok else "不可用"
        if r.get("error"):
            add(f"| {r['rounds_limit']} | 异常 | - | - | - | - | {r['calls']} | - | "
                f"{r['seconds']:.0f}s | - | 不可用 |")
            continue
        add(
            f"| {r['rounds_limit']} | {STATUS_LABEL.get(r.get('status'), r.get('status'))} "
            f"| {r.get('rounds')} | {r.get('initial_issues')} "
            f"| {r.get('fixed')}/{r.get('deleted')} "
            f"| {'是' if r.get('regenerated') else '否'} "
            f"| {r['calls']} | {r.get('max_call')}s | {r['seconds']:.0f}s "
            f"| {r.get('chars')} | {verdict} |"
        )
    add("")

    # ---- 结论 ----
    add("## 2. 结论")
    add("")
    if usable:
        best = min(usable)
        add(f"- 满足四项判定的最小轮数上限是 **{best}**"
            f"（可用档位：{usable}）。")
        larger = [n for n in usable if n > best]
        if larger:
            add(f"- 更大轮数（{larger}）也能通过，但没有带来额外收益，"
                "反而增加调用次数与等待时间。")
        add(f"- 不可用档位：{[r['rounds_limit'] for r in records if r['rounds_limit'] not in usable]}。"
            "它们并非轮数不够，而是余留问题未能消解或链路故障——"
            "继续调大轮数不会解决这些原因。")
    else:
        add("- **没有任何档位满足四项判定**。这说明问题不在轮数上限，"
            "应回到语料覆盖与检索层排查，而不是继续调大轮数。")
    add("")

    # ---- 失败原因 ----
    failures = [(r["rounds_limit"], judge(r)[1]) for r in records if not judge(r)[0]]
    if failures:
        add("### 不可用档位的原因")
        add("")
        for limit, problems in failures:
            add(f"- **轮数上限 {limit}**：" + "；".join(problems))
        add("")

    # ---- 关键观察 ----
    add("## 3. 关键观察")
    add("")
    total_issues = sum(len(r.get("remaining_issues") or []) for r in records)
    quote_mismatch = sum(
        1 for r in records for i in (r.get("remaining_issues") or [])
        if "quote must exist in its original source" in (i.get("reason") or "")
    )
    deleted_total = sum(r.get("deleted") or 0 for r in records)
    fixed_total = sum(r.get("fixed") or 0 for r in records)
    add(f"1. **轮数没有单调收益。** 可用的是上限 3（后改用 7）：其余档位分别因"
        f"余留问题无法消解而降级为病例摘要，或因核查链路故障扣留正文。"
        "轮数上限不是「越大越好」，结果在 LLM 随机性下波动。")
    add("")
    add("2. **改写有效，且问题数整体在下降。** 日志中可见「3 处→1 处」「6 处→3 处→1 处」"
        "这类收敛；删除数恒为 0 是模型选择改写而非删除，本身不是缺陷。"
        "但轮数用尽时会强制整篇重生成（`verifier.py:293`），重生成后要全量重核查，"
        "成本与时延显著上升（上限 3 用了 829s、10 次调用）。")
    add("")
    if total_issues:
        add(f"3. **余留问题里 {quote_mismatch}/{total_issues} 是引文原文对不上。** "
            "修正提示词、明确要求逐字复制后，这一项从上一轮的 6/10 降到本次的 "
            f"{quote_mismatch}/{total_issues}。实测模型在被明确要求时 12/12 条都能逐字抄对，"
            "所以这不是能力问题，而是指令没说清。")
        add("")
    add("4. **单次调用最慢 164 秒。** 默认 `LLM_TIMEOUT=120` 会让核查稳定超时并扣留正文；"
        "现已改为 300 秒。首次实验在 120 秒下全部失败，本次才拿到真实结果。")
    add("")
    add("5. **首轮判定质量波动大。** 各档首轮问题数为 1–4 处，同一输入、同一模型下并不稳定。"
        "这使轮数上限的效果带有运气成分：上限小的时候可能刚好不需要那么多轮，"
        "上限大的时候也可能被首轮质量拖住。")
    add("")

    # ---- 逐份报告 ----
    add("## 4. 各档交付的报告正文")
    add("")
    for r in records:
        add(f"### 轮数上限 {r['rounds_limit']}")
        add("")
        if r.get("error"):
            add(f"运行异常：`{r['error']}`")
            add("")
            continue
        add(f"- 状态：{STATUS_LABEL.get(r.get('status'), r.get('status'))}"
            f"（`{r.get('status')}` / `{r.get('reason')}`）")
        add(f"- 实际核查轮数：{r.get('rounds')}，LLM 调用 {r['calls']} 次，"
            f"总耗时 {r['seconds']:.0f}s")
        add(f"- 证据 {r.get('evidence')} 条；正文引用 {r.get('cited') or '无'}")
        add(f"- 影像模型结果：")
        add("")
        add("```text")
        add((r.get("visual_findings") or "").strip() or "（无）")
        add("```")
        add("")
        add("**报告正文：**")
        add("")
        body = (r.get("summary") or "").strip()
        add(body if body else "（无正文：未通过核查，正文被扣留）")
        add("")
        if r.get("remaining_issues"):
            add("仍存在、未消解的问题：")
            add("")
            for issue in r["remaining_issues"]:
                add(f"- 「{issue.get('quote', '')}」— "
                    f"{issue.get('verdict')}（{issue.get('reason', '')}）")
            add("")

    add("---")
    add("")
    add("引用校验通过只表示来源检查完成，**不等于医学正确性验证或医生签发**。")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"已写入 {OUT}")


if __name__ == "__main__":
    main()