"""严格读取引用核查的问题列表；错误消息只含字段路径与约束。"""
from typing import Any
from modules.agent.tools.grounding import BASES

# 表示「该句没问题」的写法。正常应当在 claims 里省略，这里容忍
# ok/pass 这类明显的肯定写法；supported 之类保留严格校验，
# 因为按 basis 也有 supported 的语义，容易混淆。
PASSING_VERDICTS = {"ok", "pass", "passed"}


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
        normalized = verdict.strip().lower() if isinstance(verdict, str) else ""
        # 模型偶尔把「这句没问题」也列进 claims，用 ok/pass/supported 表示。
        # 提示词要求省略，但这是个无害的表达方式，跳过该条继续处理即可，
        # 不必让整次核查报 invalid_claims 而丢掉整份报告。
        if normalized in PASSING_VERDICTS:
            continue
        if normalized not in {"partial", "unsupported", "uncited"}:
            raise ValueError(f"{path}.verdict must be partial, unsupported or uncited; omit supported claims")
        verdict = normalized
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
