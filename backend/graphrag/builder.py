"""知识图谱构建器（stub）。

从 Markdown 指南文档中抽取实体和关系，构建知识图谱。
套壳阶段：函数签名就位，函数体为空。
"""

from __future__ import annotations
from llm.models import LLMCall

import sys
from pathlib import Path


def build_graph_from_corpus(
    corpus_dir: Path,
    output_path: Path | None = None,
    llm_call: LLMCall | None = None,
) -> object:
    """从语料目录构建知识图谱（stub）。

    Args:
        corpus_dir: Markdown 指南文档目录（如 backend/knowledge/corpus/）
        output_path: 图索引持久化路径（可选）
        llm_call: LLM 调用函数，用于实体/关系抽取（可选）

    Returns:
        构建好的图对象（NetworkX DiGraph 或其他）

    TODO: 选定 GraphRAG 方案后实现以下功能：
      - 遍历 corpus_dir 下的 Markdown 文件
      - 用 LLM 辅助抽取实体（Disease, Symptom, Sign, Treatment, Drug, Guideline）
      - 建立关系边（causes, indicates, treats, contraindicated_in, ...）
      - 持久化到 output_path
    """
    print(
        f"[GraphRAG] build_graph_from_corpus() 尚未实现。"
        f"corpus_dir={corpus_dir}",
        file=sys.stderr,
    )
    return None
