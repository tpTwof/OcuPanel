"""Build the reviewed ophthalmology evidence graph from local source data."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

import networkx as nx

from core.llm.models import LLMCall
from modules.knowledge.corpus import evidence_chunks, load_guideline

SEED_NAME = "ophthalmology-graph.json"
from core.paths import CORPUS_DIR as DEFAULT_CORPUS


def load_snapshot(data: dict) -> nx.DiGraph:
    if data["schema_version"] != 1:
        raise ValueError("Unsupported ophthalmology graph schema")

    graph = nx.DiGraph()
    for concept_id, concept in data["concepts"].items():
        graph.add_node(concept_id, label=concept["label"], aliases=concept["aliases"])
    for source, relation, target in data["relations"]:
        if source not in graph or target not in graph:
            raise ValueError(f"Unknown concept in relation {source} → {target}")
        graph.add_edge(source, target, relation=relation)

    for row, chunk in zip(data["evidence"], evidence_chunks(data)):
        evidence_id = row["id"]
        source_id = row["source"]
        source = data["sources"][source_id]
        url = urlsplit(source["url"])
        if (evidence_id in graph or url.scheme != "https" or not url.hostname
                or not row["section"].strip() or not row["text"].strip()):
            raise ValueError(f"Invalid source or evidence entry: {evidence_id}")
        graph.add_node(
            evidence_id,
            label=f"{chunk.title} · {chunk.section}",
            evidence=asdict(chunk),
        )
        for anchor in row.get("anchors", []):
            if anchor not in data["concepts"]:
                raise ValueError(f"Unknown concept {anchor} for {evidence_id}")
            graph.add_edge(anchor, evidence_id, relation="关联条款")
    if not any("evidence" in attrs for _, attrs in graph.nodes(data=True)):
        raise ValueError("The ophthalmology graph contains no evidence")
    return nx.freeze(graph)


def build_graph_from_corpus(
    corpus_dir: Path,
    output_path: Path | None = None,
    llm_call: LLMCall | None = None,
) -> nx.DiGraph:
    """Validate curated evidence and optionally persist a reloadable JSON snapshot.

    The existing llm_call parameter is retained for callers of the former stub.
    """
    data = dict(schema_version=1, concepts={}, relations=[], sources={}, evidence=[])
    paths = sorted((corpus_dir / "guidelines").glob("*.json"))
    if (corpus_dir / SEED_NAME).exists():
        paths.insert(0, corpus_dir / SEED_NAME)
    for path in paths:
        guide = load_guideline(path)
        if not isinstance(guide["concepts"], dict) or not isinstance(guide["relations"], list):
            raise ValueError(f"Invalid graph concepts or relations in {path.name}")
        for key in ("concepts", "sources"):
            if data[key].keys() & guide[key].keys():
                raise ValueError(f"Duplicate {key} in {path.name}")
            data[key].update(guide[key])
        data["relations"].extend(guide["relations"])
        data["evidence"].extend(guide["evidence"])
    graph = load_snapshot(data)
    if output_path is not None:
        with NamedTemporaryFile(dir=output_path.parent, delete=False, mode="w", encoding="utf-8") as tmp:
            temporary_path = Path(tmp.name)
            try:
                json.dump(data, tmp, ensure_ascii=False, indent=2)
                tmp.close()
                temporary_path.replace(output_path)
            finally:
                temporary_path.unlink(missing_ok=True)
    return graph
