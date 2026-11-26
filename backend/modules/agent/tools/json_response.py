"""从模型文本中解析 JSON，无法解析时返回 None。"""
from __future__ import annotations
from typing import Any
import json
import re

def parse_json(raw: str | None) -> Any:
    """容错解析：模型常套 ```json 代码块或前后带一句客套话。"""
    if not raw:
        return None
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start:end + 1])
        except (ValueError, TypeError):
            return None
    return None


def parse_agent_decision(raw: str) -> dict[str, object]:
    """区分最终自然语言与工具 JSON；损坏的工具请求不能作为报告返回。"""
    text = raw.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    structured = fenced is not None or text.startswith(("{", "[", "```"))
    if not structured:
        if re.search(r'"action"\s*:', text):
            raise ValueError("Tool request must be a complete JSON object")
        return {"action": "final", "text": text}
    try:
        decision = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Malformed agent tool response") from exc
    if not isinstance(decision, dict) or not isinstance(decision.get("action"), str):
        raise ValueError("Agent response requires an action object")
    return decision
