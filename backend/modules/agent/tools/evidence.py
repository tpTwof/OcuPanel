"""请求内只读证据工具，不访问其他病例或任意文件。

专科成稿现在一次调用完成（证据全文已在提示词里），这里只剩两类确定性工作：
引用编号的结构校验，以及报告链路里"未知编号"的识别与清理——它们本该由代码
判定，不该交给模型。
"""
from __future__ import annotations
import re
from typing import Any


def citation_state(text: str) -> tuple[set[int], bool]:
    numbers = set()
    nonstandard = False
    for group in re.findall(r"\[([^\]\n]+)\]", text):
        value = group.strip()
        if re.fullmatch(r"-?\d+", value):
            numbers.add(int(value))
        elif re.fullmatch(r"[\d\s,，、\-–—]+", value) and re.search(r"\d", value):
            nonstandard = True
            numbers.update(int(number) for number in re.findall(r"\d+", value))
    return numbers, nonstandard

class EvidenceTools:
    def __init__(self, evidence: list[dict[str, Any]], numbers: dict[str, int]) -> None:
        self.items = {item['id']: item for item in evidence if item['id'] in numbers}
        self.numbers = numbers

    def validate_citations(self, text: str) -> None:
        cited, nonstandard = citation_state(text)
        allowed = {self.numbers[key] for key in self.items}
        if nonstandard:
            raise ValueError('Use separate [n] integer citation markers')
        if cited - allowed:
            raise ValueError(f'Unknown citation numbers: {sorted(cited - allowed)}')


def unknown_citation_issues(
    text: str, evidence: list[dict[str, object]],
) -> list[dict[str, object]]:
    """生成确定性的编号问题，交给 Verifier 的修订循环，不抛业务异常。"""
    allowed = {int(item.get("index", i)) for i, item in enumerate(evidence, 1)}
    issues = []
    for line in text.splitlines():
        cited, nonstandard = citation_state(line)
        unknown = cited - allowed
        if unknown or nonstandard:
            issues.append({
                "quote": line,
                "citations": sorted(unknown or cited),
                "verdict": "unsupported",
                "impact": "core",
                "reason": (f"Unknown citation numbers: {sorted(unknown)}" if unknown else
                           "Non-standard citation markers; use separate [n] integers"),
                "origin": "citation_control",
            })
    return issues


_CITATION = re.compile(r"\[(\d+)\]")


def strip_unknown_citations(text: str, evidence: list[dict[str, object]]) -> tuple[str, list[dict]]:
    """只清理「句子本身另有有效引用」时多余的编号笔误。

    模型偶尔记错编号（仅 2 条证据却写 [3]）。若该句同时带着有效引用，多余编号只是
    笔误，去掉即可，不必占用修订轮数；若该句唯一的引用就是无效编号，去掉后它会变成
    一句没有出处的断言，因此不动它——仍按未知引用处理，交给核查阻断。
    只处理「数字超出编号范围」这一种确定错误；非标准写法（如 [1,2]）也仍交给核查。
    """
    allowed = {int(item.get("index", i)) for i, item in enumerate(evidence, 1)}
    removed: list[dict] = []

    def fix_line(line: str) -> str:
        numbers = [int(n) for n in _CITATION.findall(line)]
        unknown = [n for n in numbers if n not in allowed]
        if not unknown or len(unknown) == len(numbers):
            return line  # 无笔误，或整句只靠无效引用 → 交给核查处理
        removed.extend({"marker": f"[{n}]", "number": n} for n in unknown)
        return _CITATION.sub(lambda m: "" if int(m[1]) not in allowed else m[0], line)

    return "\n".join(fix_line(line) for line in text.splitlines()), removed
