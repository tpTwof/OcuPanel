"""确定性的适用性与事实一致性检查。

这些判断不依赖模型，覆盖验收里列出的三类硬错误：

- 正文给出了病例输入和检索资料里都不存在的计量数值（编造数据）；
- 句子限定某一眼，但数值只出现在另一眼的病例事实里（左右眼混淆）；
- 引用编号指向与本次分析病种无关的条款（证据不适用）。

只报可以复核的确定性冲突；语义层面的适用性仍由核查提示词与专业复核判断。
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from modules.knowledge.metadata import matches_case_disease

# 带单位的数值才算「测量/处置数值」，避免把章节号、编号误判为临床数据。
_MEASUREMENT = re.compile(
    r"(?<![0-9.])(-?\d+(?:\.\d+)?)\s*"
    r"(mmHg|mm Hg|kPa|µ?m|μm|dB|mg|ml|mL|%|岁|年|个月|月|周|天|小时|分钟|次(?:/年|/日)?)"
)
_CITATION = re.compile(r"\[(\d+)\]")
_RIGHT = re.compile(r"右眼|右側|右侧|OD\b", re.IGNORECASE)
_LEFT = re.compile(r"左眼|左側|左侧|OS\b", re.IGNORECASE)
_BOTH = re.compile(r"双眼|双侧|OU\b", re.IGNORECASE)


def _normalized(text: str) -> set[str]:
    values = set()
    for raw in re.findall(r"-?\d+(?:\.\d+)?", text):
        try:
            values.add(format(float(raw), "g"))
        except ValueError:
            continue
    return values


def _sentence_eye(line: str) -> str:
    if _BOTH.search(line):
        return "both"
    if _RIGHT.search(line) and not _LEFT.search(line):
        return "right"
    if _LEFT.search(line) and not _RIGHT.search(line):
        return "left"
    return "unknown"


def _facts_by_eye(case_facts: Iterable[dict[str, Any]]) -> dict[str, set[str]]:
    groups: dict[str, set[str]] = {"right": set(), "left": set(), "shared": set()}
    for fact in case_facts:
        numbers = {str(value) for value in fact.get("numbers") or ()}
        if not numbers:
            continue
        eye = fact.get("eye") or "unknown"
        if eye in ("right", "left"):
            groups[eye].update(numbers)
        else:
            groups["shared"].update(numbers)
    return groups


def fabricated_value_issues(
    text: str, case_context: str, evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """正文里的计量数值必须能在病例输入或证据正文中找到。"""
    known = _normalized(case_context)
    for item in evidence:
        known.update(_normalized(str(item.get("text", ""))))
    issues = []
    for line in text.splitlines():
        missing = sorted({
            f"{number}{unit}" for number, unit in _MEASUREMENT.findall(line)
            if format(float(number), "g") not in known
        })
        if missing:
            issues.append({
                "quote": line.strip(), "citations": [int(n) for n in _CITATION.findall(line)],
                "verdict": "unsupported", "impact": "core", "basis": "case_inference",
                "reason": "正文数值未出现在病例输入或检索资料中：" + "、".join(missing[:4]),
                "origin": "fabricated_value",
            })
    return issues


def lateral_mismatch_issues(
    text: str, case_facts: Iterable[dict[str, Any]], evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """句子限定某一眼、给出了数值，而该数值只属于另一眼的病例事实。"""
    groups = _facts_by_eye(case_facts)
    if not groups["right"] and not groups["left"]:
        return []
    evidence_numbers: set[str] = set()
    for item in evidence:
        evidence_numbers.update(_normalized(str(item.get("text", ""))))
    issues = []
    for line in text.splitlines():
        eye = _sentence_eye(line)
        if eye not in ("right", "left"):
            continue
        other = "left" if eye == "right" else "right"
        for number, unit in _MEASUREMENT.findall(line):
            value = format(float(number), "g")
            if (value in groups[other] and value not in groups[eye]
                    and value not in groups["shared"] and value not in evidence_numbers):
                label = "右眼" if eye == "right" else "左眼"
                issues.append({
                    "quote": line.strip(),
                    "citations": [int(n) for n in _CITATION.findall(line)],
                    "verdict": "unsupported", "impact": "core", "basis": "case_fact",
                    "reason": f"正文把 {number}{unit} 写为{label}表现，但该数值只见于另一眼的病例记录",
                    "origin": "lateral_mismatch",
                })
                break
    return issues


def evidence_scope_issues(
    text: str, evidence: list[dict[str, Any]], diseases: Iterable[str],
) -> list[dict[str, Any]]:
    """引用编号不得指向与本次分析病种无关的条款。"""
    scopes = tuple(diseases)
    if not scopes:
        return []
    by_index = {int(item.get("index", pos)): item for pos, item in enumerate(evidence, 1)}
    issues = []
    for line in text.splitlines():
        for raw in _CITATION.findall(line):
            item = by_index.get(int(raw))
            if item is None:
                continue
            if any(matches_case_disease(item, disease) for disease in scopes):
                continue
            issues.append({
                "quote": line.strip(), "citations": [int(raw)],
                "verdict": "unsupported", "impact": "core", "basis": "medical_knowledge",
                "reason": f"引用的资料 [{raw}] 不适用于本次分析病种",
                "origin": "not_applicable",
            })
            break
    return issues


def applicability_issues(
    text: str,
    evidence: list[dict[str, Any]],
    *,
    case_context: str,
    case_facts: Iterable[dict[str, Any]] = (),
    diseases: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """合并三类确定性检查，交给核查流程统一去重与处理。

    没有病例上下文时无法判断某个数值是否为编造（可能全部来自用户输入），
    此时跳过数值检查；左右眼与病种检查仍按传入的事实和证据执行。
    """
    issues: list[dict[str, Any]] = []
    if case_context.strip():
        issues.extend(fabricated_value_issues(text, case_context, evidence))
    issues.extend(lateral_mismatch_issues(text, case_facts, evidence))
    issues.extend(evidence_scope_issues(text, evidence, diseases))
    return issues
