"""Read and validate citation records independently of graph construction.

条款元数据保持向后兼容：旧文件没有材料类型、审核状态、适用条件等字段时，
分别落为空串/空表，由 `modules.knowledge.metadata` 解释为「未登记」。
显式写了非法取值会在加载时就报错，避免脏数据静默进入检索。
"""

import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from modules.knowledge.metadata import (
    normalize_disease_scope,
    normalize_material_type,
    normalize_review_status,
    normalize_topic,
    parse_applicability,
)
from modules.knowledge.models import SourcedChunk

_SOURCE_TEXT_FIELDS = ("title", "version", "jurisdiction", "url")
_SOURCE_OPTIONAL_TEXT_FIELDS = ("language", "published_at", "accessed_at")
_EVIDENCE_TEXT_FIELDS = ("id", "section", "text", "scope")
_EVIDENCE_OPTIONAL_TEXT_FIELDS = (
    "lang", "chinese_summary", "context", "supersedes", "superseded_by",
)


def _text(data: dict, field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid field: {field}")
    return value.strip()


def _optional_text(data: dict, field: str) -> str:
    value = data.get(field)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"Invalid field: {field}")
    return value.strip()


def _check_source(name: str, source: dict) -> None:
    for field in _SOURCE_TEXT_FIELDS:
        _text(source, field)
    for field in _SOURCE_OPTIONAL_TEXT_FIELDS:
        _optional_text(source, field)
    normalize_material_type(source.get("material_type"))
    normalize_review_status(source.get("review_status"))
    normalize_disease_scope(source.get("disease"))
    url = urlsplit(source["url"])
    if url.scheme != "https" or not url.hostname:
        raise ValueError(f"Invalid source URL: {source['url']}")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Invalid source id")


def _check_evidence(row: dict) -> None:
    for field in _EVIDENCE_TEXT_FIELDS:
        _text(row, field)
    for field in _EVIDENCE_OPTIONAL_TEXT_FIELDS:
        _optional_text(row, field)
    normalize_topic(row.get("topic"))
    normalize_material_type(row.get("material_type"))
    normalize_review_status(row.get("review_status"))
    normalize_disease_scope(row.get("disease"))
    parse_applicability(row.get("applicability"))


def load_guideline(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["schema_version"] != 1:
        raise ValueError(f"Unsupported guideline schema: {path}")
    data.setdefault("concepts", {})
    data.setdefault("relations", [])
    for name, source in data["sources"].items():
        _check_source(name, source)
    for row in data["evidence"]:
        _check_evidence(row)
        if row["source"] not in data["sources"]:
            raise ValueError(f"Unknown source for evidence {row['id']}: {row['source']}")
    return data


def content_digest(text: str) -> str:
    """条款正文的内容哈希，用于确认报告存档引用的仍是同一份材料。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def evidence_chunks(data: dict) -> list[SourcedChunk]:
    chunks = []
    for row in data["evidence"]:
        source = data["sources"][row["source"]]
        chunks.append(SourcedChunk(
            id=row["id"], source=row["source"], title=source["title"],
            section=row["section"], text=row["text"], lang=row.get("lang", "zh"),
            url=source["url"], version=source["version"],
            jurisdiction=source["jurisdiction"], scope=row["scope"],
            # 条款级取值优先，其次来源级；都没有时留空表示未登记。
            topic=(normalize_topic(row.get("topic"))
                   or normalize_topic(source.get("topic"))),
            material_type=(normalize_material_type(row.get("material_type"))
                           or normalize_material_type(source.get("material_type"))),
            review_status=(normalize_review_status(row.get("review_status"))
                           or normalize_review_status(source.get("review_status"))),
            content_hash=content_digest(row["text"]),
            disease=",".join(normalize_disease_scope(row.get("disease"))
                             or normalize_disease_scope(source.get("disease"))),
            applicability=parse_applicability(row.get("applicability")),
            chinese_summary=row.get("chinese_summary", ""),
            context=row.get("context", ""),
            supersedes=row.get("supersedes", ""),
            superseded_by=row.get("superseded_by", ""),
        ))
    return chunks
