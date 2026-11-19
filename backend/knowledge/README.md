# 知识检索

`retrieval.py` 为 [corpus/](corpus/) 下的语料和启用的图谱条款建立索引。后端通过 `RAG_MODE` 选择 BM25 关键词检索、向量检索或混合检索。默认 `hybrid` 使用 Reciprocal Rank Fusion 合并排名，再应用来源上限与语言配额等筛选规则。

- `service.py` 提供报告与眼科聊天使用的检索入口、图谱融合和证据格式化。
- `models.py` 定义证据相关的数据结构。
- 通过向量通道时，默认使用 `intfloat/multilingual-e5-small`，首次运行可能下载权重。配置 `RAG_MODE=bm25` 可单独调试关键词召回。

语料用于演示证据召回与引用。检索分数表示所用通道的相关性，医学判断需另行验证。更换语料或向量模型后，应重新检查阈值与启动自检。 [后端配置](../README.md#配置) · [报告流程](../report/README.md)

图谱条款的来源和维护规则见 [图检索](../graphrag/README.md)。
