"""从模型文本中解析 JSON，无法解析时返回 None。"""
import json
import re

def parse_json(raw: str | None):
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
