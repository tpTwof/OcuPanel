"""按病种 × 方面统计语料覆盖，生成缺口矩阵。

只读语料与评估集，不改数据。输出用于阶段一的覆盖盘点与阶段三的补库验收：
覆盖矩阵记录每个格子的条款数、条款示例、审核状态与对应评估病例，空缺的格子
明确标为缺口——不能仅凭文件名或总条数判断覆盖完整。

用法（在 backend 目录）::

    ..\\.venv\\Scripts\\python.exe tools/corpus_coverage.py
    ..\\.venv\\Scripts\\python.exe tools/corpus_coverage.py --write ..\\docs\\语料覆盖矩阵.md
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from modules.knowledge.metadata import (  # noqa: E402
    MATERIAL_TYPE_LABELS,
    REVIEW_STATUS_LABELS,
    TOPICS,
    clause_diseases,
    clause_fit,
    resolve_material_type,
    resolve_review_status,
    resolve_topic,
)
from modules.knowledge.retrieval import Retriever  # noqa: E402

DISEASES = {
    "glaucoma": "青光眼",
    "diabetic_retinopathy": "糖尿病视网膜病变（DR）",
    "age_related_macular_degeneration": "年龄相关性黄斑变性（AMD）",
}
TOPIC_LABELS = {
    "diagnosis": "诊断与分型",
    "interpretation": "检查判读",
    "examination": "检查方法",
    "differential": "鉴别诊断",
    "treatment": "诊断后处置",
    "followup": "随访与监测",
    "education": "患者教育",
    "unclassified": "未分类",
}
EVAL_CASES = BACKEND / "tests" / "fixtures" / "report_eval_cases.json"
DEFAULT_OUTPUT = BACKEND.parent / "docs" / "语料覆盖矩阵.md"


def _eval_index() -> dict[tuple[str, str], list[str]]:
    if not EVAL_CASES.exists():
        return {}
    data = json.loads(EVAL_CASES.read_text(encoding="utf-8"))
    index: dict[tuple[str, str], list[str]] = defaultdict(list)
    for case in data.get("cases", []):
        for question in case.get("expected_questions") or []:
            index[(question["disease"], question["topic"])].append(case["id"])
    return index


def collect() -> dict:
    retriever = Retriever.from_corpus(mode="bm25", graph_enabled=False)
    cells: dict[tuple[str, str], list[dict]] = defaultdict(list)
    generic: dict[str, list[dict]] = defaultdict(list)
    review: Counter[str] = Counter()
    material: Counter[str] = Counter()
    for chunk in retriever.chunks:
        scope = clause_diseases({"source": chunk.source, "disease": chunk.disease})
        if scope is not None and not scope:
            continue  # 明确登记为与三病种无关
        topic = resolve_topic({"section": chunk.section, "topic": chunk.topic}) or "unclassified"
        record = {
            "id": chunk.id, "source": chunk.source, "section": chunk.section, "topic": topic,
            "material_type": resolve_material_type({"source": chunk.source,
                                                    "material_type": chunk.material_type}),
            "review_status": resolve_review_status({"review_status": chunk.review_status}),
            # 适用条件参与「可用」判断：条款写明的前提与例外不是排除理由，
            # 但未核实的条件要在矩阵里如实计数（报告必须写明前提）。
            "applicability": dict(getattr(chunk, "applicability", None) or {}),
        }
        material[record["material_type"]] += 1
        review[record["review_status"]] += 1
        if scope is None:
            generic[topic].append(record)
        else:
            for disease in scope:
                if disease in DISEASES:
                    cells[(disease, topic)].append(record)
    return {
        "cells": cells, "generic": generic, "review": review, "material": material,
        "total": retriever.size,
    }


def render(data: dict, eval_index: dict[tuple[str, str], list[str]]) -> str:
    lines = [
        "# 语料覆盖矩阵（自动生成）",
        "",
        "本文件由 `backend/tools/corpus_coverage.py` 生成，请勿手工修改数字。"
        "覆盖情况以条款级元数据为准；没有登记病种的条款单独列在「通用条款」中，"
        "不会算进某一病种的覆盖。",
        "",
        f"当前索引片段总数：{data['total']}。",
        "",
        "「可用于该方面」按 v2 检索的实际采纳规则统计，而不是只看材料类型：材料类型"
        "要能支撑该主题（诊疗主题只认指南、共识与系统综述，患者教育主题还认患者教育"
        "材料），且条款适用条件不能与检索筛选矛盾。条款写明的前提与例外不是排除理由——"
        "它们随证据进入提示词，报告必须写明；未核实的适用条件按条数另行列在表下。",
        "",
        "## 三病种覆盖",
        "",
        "| 病种 | 方面 | 条款数 | 可用于该方面 | 条款示例 | 审核状态 | 评估病例 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    gaps: list[str] = []
    weak: list[str] = []
    fit_total = 0
    unverified_total = 0
    for disease, label in DISEASES.items():
        for topic in TOPICS:
            records = data["cells"].get((disease, topic), [])
            ids = [record["id"] for record in records]
            fits = [clause_fit(record, topic, {"disease": disease}) for record in records]
            usable = [record for record, fit in zip(records, fits) if fit["ok"]]
            unverified = sum(1 for fit in fits if fit["ok"] and fit["unknown"])
            fit_total += len(usable)
            unverified_total += unverified
            statuses = Counter(record["review_status"] for record in records)
            status_text = "、".join(
                f"{REVIEW_STATUS_LABELS.get(key, key)} {value}" for key, value in statuses.items()
            ) or "—"
            cases = "、".join(sorted(set(eval_index.get((disease, topic), [])))) or "—"
            examples = "、".join(f"`{item}`" for item in ids[:3]) or "**缺口**"
            if len(ids) > 3:
                examples += f" 等 {len(ids)} 条"
            if not ids:
                gaps.append(f"{label} · {TOPIC_LABELS[topic]}")
            elif not usable:
                weak.append(f"{label} · {TOPIC_LABELS[topic]}")
            lines.append(
                f"| {label} | {TOPIC_LABELS[topic]} | {len(ids)} | {len(usable)} | "
                f"{examples} | {status_text} | {cases} |"
            )
    lines += [
        "",
        f"合计可采纳 {fit_total} 条，其中 {unverified_total} 条的适用条件未在筛选里核实——"
        "引用这些条款的结论与建议必须写明前提，不能当作条件已满足。",
        "",
        "## 缺口汇总",
        "",
    ]
    if gaps:
        lines.append("**没有条款：**")
        lines += [f"- {item}" for item in gaps]
        lines.append("")
    if weak:
        lines.append("**以下格子有条款，但材料类型不足以支撑该方面的诊疗结论，或适用条件与病例病种相互矛盾：**")
        lines += [f"- {item}" for item in weak]
        lines.append("")
    if not gaps and not weak:
        lines.append("当前三病种 × 七个方面均已有可被 v2 检索采纳的条款，仍需按评估集核对适用性。")
        lines.append("")
    lines += [
        "缺口不代表可以用通用清单填充：报告应在正文说明「当前无法给出」，并在补库后重新跑检索回归。",
        "",
        "## 通用条款（未登记病种）",
        "",
        "| 方面 | 条款数 | 条款示例 |",
        "| --- | --- | --- |",
    ]
    for topic, records in sorted(data["generic"].items()):
        ids = [record["id"] for record in records]
        examples = "、".join(f"`{item}`" for item in ids[:3]) + (f" 等 {len(ids)} 条" if len(ids) > 3 else "")
        lines.append(f"| {TOPIC_LABELS.get(topic, topic)} | {len(ids)} | {examples} |")
    lines += [
        "",
        "## 来源类型与审核状态",
        "",
        "| 类别 | 取值 | 片段数 |",
        "| --- | --- | --- |",
    ]
    for key, value in sorted(data["material"].items()):
        lines.append(f"| 材料类型 | {MATERIAL_TYPE_LABELS.get(key, key)} | {value} |")
    for key, value in sorted(data["review"].items()):
        lines.append(f"| 审核状态 | {REVIEW_STATUS_LABELS.get(key, key)} | {value} |")
    lines += [
        "",
        "草稿与患者教育材料会计入覆盖数，但不满足需要正式指南条款的主题（见 "
        "`backend/modules/knowledge/metadata.py` 的 `TOPIC_MATERIAL_TYPES`）。"
        "审核状态为「待复核」或「未登记」的条款可以参与检索，但不能写成已核实结论。",
        "",
        "## 维护流程",
        "",
        "覆盖缺口清单 → 获取并核对原文 → 条款化整理 → 来源与适用性审核 → 去重与版本登记 → "
        "入库及索引更新 → 检索回归。新增条款必须登记 `topic`、`material_type`、`review_status` "
        "与 `applicability`，并同步 `report_focus.SOURCE_DISEASES`（未登记来源会被当作通用条款）。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成三病种语料覆盖矩阵")
    parser.add_argument("--write", nargs="?", const=str(DEFAULT_OUTPUT), default=None,
                        help="写入 Markdown 文件（默认 docs/语料覆盖矩阵.md）")
    parser.add_argument("--json", action="store_true", help="输出机器可读统计")
    args = parser.parse_args()

    data = collect()
    eval_index = _eval_index()
    if args.json:
        payload = {
            "total": data["total"],
            "cells": {
                f"{disease}:{topic}": [record["id"] for record in records]
                for (disease, topic), records in sorted(data["cells"].items())
            },
            "review": dict(data["review"]),
            "material": dict(data["material"]),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    markdown = render(data, eval_index)
    if args.write:
        Path(args.write).write_text(markdown, encoding="utf-8")
        print(f"written {args.write}")
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
