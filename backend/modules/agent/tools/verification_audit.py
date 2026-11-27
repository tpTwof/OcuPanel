"""引用校验的来源清单、病例原文匹配和最终编号关联，不判定医学正确性。"""
import hashlib
import re
from typing import Any
from modules.agent.tools.text_revision import visible_text
from modules.agent.tools.grounding import SOFTWARE_BOUNDARY
from modules.knowledge.metadata import evidence_metadata


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_manifest(case_context: str, evidence: list[dict]) -> dict[str, Any]:
    """本次核查所用来源的清单：正文快照哈希、证据编号、版本与审核状态。

    保存内容哈希与来源版本，报告存档才能复核「当时引用的是哪一版条款」。
    审核状态与引用校验结果分开记录——引用有效不等于条款已通过临床审核。
    """
    return {
        "case_sha256": text_digest(case_context), "case_available": bool(case_context.strip()),
        "case_context": case_context,
        "software_boundary": SOFTWARE_BOUNDARY, "policy_sha256": text_digest(SOFTWARE_BOUNDARY),
        "evidence": [{
            "index": item.get("index", index), "id": item.get("id"),
            "source": item.get("source"), "section": item.get("section"),
            "text_sha256": text_digest(item.get("text", "")),
            **evidence_metadata(item),
        } for index, item in enumerate(evidence, 1)],
    }


def _plain(text: str) -> str:
    return visible_text(text)


def case_fragments(case_context: str) -> list[str]:
    context = re.sub(r"(?m)^Clinician note:\s*", "", case_context)
    return [part.strip() for part in re.split(r"[。！？\n；;，,]", context) if len(_plain(part)) >= 8]


def contains_case_fragment(quote: str, fragments: list[str]) -> bool:
    return any(_plain(fragment) in _plain(quote) for fragment in fragments)


def match_case_facts(issues: list[dict], case_context: str) -> tuple[list[dict], list[dict]]:
    """仅将原始输入中可直接匹配且未挂外部引用的病例事实归回病例来源。"""
    remaining, matched = [], []
    context = _plain(case_context)
    for item in issues:
        quote = item["quote"]
        if (item.get("basis") == "case_fact" and context and _plain(quote) in context
                and not item.get("citations") and not re.search(r"\[\d+\]", quote)):
            matched.append({"quote": quote, "source": "case_input", "case_sha256": text_digest(case_context)})
        else:
            remaining.append(item)
    return remaining, matched


def reference_links(text: str) -> list[dict[str, Any]]:
    """记录交付正文的编号分布；这是来源关联，不是独立的语义验证。"""
    return [{"quote": line.strip(), "citations": sorted({int(n) for n in re.findall(r"\[(\d+)\]", line)})}
            for line in text.splitlines() if re.search(r"\[\d+\]", line)]
