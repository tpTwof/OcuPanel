"""Read and validate citation records independently of graph construction."""

import json
from pathlib import Path
from urllib.parse import urlsplit

from modules.knowledge.models import SourcedChunk


def load_guideline(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["schema_version"] != 1:
        raise ValueError(f"Unsupported guideline schema: {path}")
    data.setdefault("concepts", {})
    data.setdefault("relations", [])
    for row in data["evidence"]:
        source = data["sources"][row["source"]]
        for field in ("id", "section", "text", "scope"):
            if not isinstance(row[field], str) or not row[field].strip():
                raise ValueError(f"Invalid evidence field: {field}")
        for field in ("title", "version", "jurisdiction", "url"):
            if not isinstance(source[field], str) or not source[field].strip():
                raise ValueError(f"Invalid source field: {field}")
        url = urlsplit(source["url"])
        if url.scheme != "https" or not url.hostname:
            raise ValueError(f"Invalid source URL: {source['url']}")
    return data


def evidence_chunks(data: dict) -> list[SourcedChunk]:
    chunks = []
    for row in data["evidence"]:
        source = data["sources"][row["source"]]
        chunks.append(SourcedChunk(
            id=row["id"], source=row["source"], title=source["title"],
            section=row["section"], text=row["text"], lang=row.get("lang", "zh"),
            url=source["url"], version=source["version"],
            jurisdiction=source["jurisdiction"], scope=row["scope"],
        ))
    return chunks
