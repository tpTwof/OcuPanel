"""GraphRetriever —— 图检索接口。

与现有 retrieval.Retriever.search() 返回格式兼容（list[dict]），
增加 graph_path 字段记录遍历路径。

套壳阶段：search() 始终返回空列表，上层 RRF 融合时自然跳过图检索路。
"""

from __future__ import annotations

import sys
from pathlib import Path


class GraphRetriever:
    """基于知识图谱的证据检索器（stub）。

    TODO: 选定 GraphRAG 方案后实现以下功能：
      - 加载/构建知识图谱
      - 查询 → 实体识别 → 图锚点定位 → k-hop 遍历
      - 返回带 graph_path 的证据条目

    当前 search() 返回空列表，不影响现有 BM25/vector 检索。
    """

    def __init__(self, graph_store: str = "networkx"):
        self.graph_store = graph_store
        self._graph = None  # TODO: NetworkX DiGraph or other store
        self._is_built = False

    @property
    def is_available(self) -> bool:
        """图索引是否可用。不可用时上层应跳过图检索路。"""
        return self._is_built and self._graph is not None

    def load_graph(self, graph_path: Path | None = None) -> None:
        """加载预构建的图索引（stub）。"""
        print(
            "[GraphRAG] load_graph() 尚未实现。"
            "请在 graphrag/retriever.py 中填入具体图存储加载逻辑。",
            file=sys.stderr,
        )

    def search(
        self,
        query: str,
        k: int = 4,
        hop: int = 2,
        min_score: float = 0.0,
    ) -> list[dict]:
        """图检索入口。返回与 retrieval.Retriever.search() 兼容的 list[dict]。

        每条结果额外包含 graph_path 字段（遍历路径）。
        当前 stub 返回空列表。
        """
        if not self.is_available:
            return []

        # TODO: 实现图遍历检索
        print(
            f"[GraphRAG] search() 尚未实现，返回空结果。query={query[:50]}",
            file=sys.stderr,
        )
        return []

    def close(self) -> None:
        """释放图存储资源。"""
        self._graph = None
        self._is_built = False
