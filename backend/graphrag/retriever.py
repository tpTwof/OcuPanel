"""Retrieve citations by following bounded paths through clinical concepts."""

from __future__ import annotations

import json
import re
from pathlib import Path

import networkx as nx

from .builder import DEFAULT_CORPUS, build_graph_from_corpus, load_snapshot

REGION_PATTERNS = {
    "CN": re.compile(r"中国|国内|中国大陆|(?<![a-z0-9])(?:china|chinese|nmpa)(?![a-z0-9])", re.I),
    "US": re.compile(r"美国|(?<![a-z0-9])(?:usa?|united states|fda|ada|aao)(?![a-z0-9])", re.I),
    "UK": re.compile(r"英国|(?<![a-z0-9])(?:uk|united kingdom|nice ng\s?\d+)(?![a-z0-9])", re.I),
}


def query_regions(query: str) -> set[str]:
    return {region for region, pattern in REGION_PATTERNS.items() if pattern.search(query)}


class GraphRetriever:
    def __init__(self, graph_store: str = "networkx") -> None:
        self.graph_store = graph_store
        self._graph: nx.DiGraph | None = None
        self._aliases: dict[str, re.Pattern[str]] = {}

    @property
    def is_available(self) -> bool:
        return self._graph is not None

    def load_graph(self, graph_path: Path | None = None) -> None:
        if self.graph_store != "networkx":
            raise ValueError(f"Unsupported GRAPH_STORE: {self.graph_store}")
        graph = (
            build_graph_from_corpus(DEFAULT_CORPUS)
            if graph_path is None else load_snapshot(json.loads(graph_path.read_text(encoding="utf-8")))
        )
        self._aliases = {
            node: re.compile(
                r"(?<![a-z0-9非])(?:" + "|".join(map(re.escape, data["aliases"])) + r")(?![a-z0-9])",
                re.I,
            )
            for node, data in graph.nodes(data=True) if data.get("aliases")
        }
        self._graph = graph

    def evidence(self) -> list[dict]:
        if self._graph is None:
            return []
        return [dict(data["evidence"]) for _, data in self._graph.nodes(data=True) if "evidence" in data]

    def search(self, query: str, k: int = 4, hop: int = 2, min_score: float = 0.0) -> list[dict]:
        graph = self._graph
        if graph is None or k <= 0 or hop <= 0:
            return []
        matches = {node for node, pattern in self._aliases.items() if pattern.search(query)}
        regions = query_regions(query)
        paths: dict[str, list[str]] = {}
        for anchor in sorted(matches):
            for target, path in nx.single_source_shortest_path(graph, anchor, cutoff=hop).items():
                evidence = graph.nodes[target].get("evidence")
                if not evidence or (regions and evidence["jurisdiction"] not in regions | {"INT"}):
                    continue
                previous = paths.get(target)
                if previous is None or len(path) < len(previous):
                    paths[target] = path

        results = []
        for target, path in paths.items():
            # Prefer entries supported by multiple query concepts and reachable in fewer hops.
            direct_matches = len(matches.intersection(graph.predecessors(target)))
            score = (1 + direct_matches) / (len(path) - 1)
            steps = [
                dict(source=graph.nodes[left]["label"], relation=graph.edges[left, right]["relation"],
                     target=graph.nodes[right]["label"])
                for left, right in zip(path, path[1:])
            ]
            results.append({**graph.nodes[target]["evidence"], "graph": score, "graph_path": steps})
        results.sort(key=lambda item: (-item["graph"], item["id"]))
        best = results[0]["graph"] if results else 1.0
        return [
            {**item, "score": round(item["graph"] / best, 3), "sources": "graph"}
            for item in results[:k] if item["graph"] / best >= min_score
        ]

    def close(self) -> None:
        self._graph = None
        self._aliases = {}
