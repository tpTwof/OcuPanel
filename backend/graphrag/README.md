# 图检索

设置 `RAG_ENABLED=1` 和 `GRAPH_RAG_ENABLED=1` 后，报告和眼科问答可使用图检索与基础检索融合。配置 `RAG_MODE=bm25` 可在本地跳过向量模型下载。

`builder.py` 加载并校验眼科图谱，`retriever.py` 根据概念和关系召回带出处的证据。内置数据包含概念、方向关系、来源和条款。命中证据可以包含 `graph_path`。图谱加载失败时使用基础检索。 [图谱数据](../knowledge/corpus/ophthalmology-graph.json) · [配置与示例](../README.md#graphrag)
