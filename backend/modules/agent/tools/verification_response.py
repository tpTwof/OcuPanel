"""严格读取引用核查的问题列表；错误消息只含字段路径与约束。"""
from typing import Any
from modules.agent.tools.grounding import BASES


def parse_claims(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict) or not isinstance(data.get("claims"), list):
        raise ValueError("claims must be an array in a JSON object")
    issues = []
    for index, item in enumerate(data["claims"]):
        path = f"claims[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{path} must be an object")
        quote = item.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            raise ValueError(f"{path}.quote must be a non-empty string")
        verdict = item.get("verdict")
        if not isinstance(verdict, str) or verdict.strip().lower() not in {"partial", "unsupported", "uncited"}:
            raise ValueError(f"{path}.verdict must be partial, unsupported or uncited; omit supported claims")
        citations = item.get("citations", [])
        if not isinstance(citations, list) or any(type(number) is not int for number in citations):
            raise ValueError(f"{path}.citations must be an array of integers")
        impact = item.get("impact", "core")
        if impact not in ("core", "local"):
            raise ValueError(f"{path}.impact must be core or local")
        basis = item.get("basis", "medical_knowledge")
        if not isinstance(basis, str) or basis not in BASES:
            raise ValueError(f"{path}.basis must classify the claim source")
        issues.append({
            "quote": quote.strip(),
            "verdict": verdict.strip().lower(),
            "citations": citations,
            "impact": impact,
            "basis": basis,
            "reason": str(item.get("reason") or "")[:120],
        })
    return issues
