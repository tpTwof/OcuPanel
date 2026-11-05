"""请求内只读证据工具，不访问其他病例或任意文件。"""
from __future__ import annotations
from typing import Any
import re

class EvidenceTools:
    def __init__(self, evidence: list[dict[str, Any]], numbers: dict[str, int]) -> None:
        self.items = {item['id']: item for item in evidence if item['id'] in numbers}
        self.numbers = numbers

    def search(self, query: str) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip() or len(query) > 1000:
            raise ValueError('query must contain 1–1000 characters')
        terms = set(re.findall(r'\w+', query.lower()))
        def relevance(item: dict) -> int:
            text = (item.get("title", "") + " " + item.get("text", "")).lower()
            return sum(term in text for term in terms)

        ranked = sorted(self.items.values(), key=relevance, reverse=True)
        return [
            {
                "id": item["id"],
                "citation": self.numbers[item["id"]],
                "title": item.get("title", ""),
            }
            for item in ranked[:5]
        ]

    def read(self, evidence_id: str) -> dict[str, Any]:
        if evidence_id not in self.items:
            raise ValueError('Unknown evidence id')
        item = self.items[evidence_id]
        return {'id':evidence_id,'citation':self.numbers[evidence_id], 'text':item.get('text','')}

    def validate_citations(self, text: str) -> None:
        cited = {int(n) for n in re.findall(r'\[(\d+)\]',text)}
        allowed = {self.numbers[key] for key in self.items}
        if cited - allowed:
            raise ValueError(f'Unknown citation numbers: {sorted(cited - allowed)}')


def unknown_citation_issues(
    text: str, evidence: list[dict[str, object]],
) -> list[dict[str, object]]:
    """生成确定性的编号问题，交给 Verifier 的修订循环，不抛业务异常。"""
    allowed = {int(item.get("index", i)) for i, item in enumerate(evidence, 1)}
    issues = []
    for line in text.splitlines():
        cited = {int(number) for number in re.findall(r"\[(\d+)\]", line)}
        unknown = cited - allowed
        if unknown:
            issues.append({
                "quote": line,
                "citations": sorted(unknown),
                "verdict": "unsupported",
                "reason": f"Unknown citation numbers: {sorted(unknown)}",
            })
    return issues
