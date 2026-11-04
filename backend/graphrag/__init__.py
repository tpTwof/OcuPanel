"""GraphRAG 知识引擎 —— 图检索增强生成。

套壳阶段：空图 + 函数骨架，运行时自动跳过图检索路。
待选定 GraphRAG 方案（LightRAG / Microsoft GraphRAG / nano-graphrag）后填入实现。
"""

from .retriever import GraphRetriever
from .builder import build_graph_from_corpus

__all__ = [
    "GraphRetriever",
    "build_graph_from_corpus",
]
