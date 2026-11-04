# Glossary

OcuPanel 项目的领域术语表。纯领域概念，不含实现细节。

---

## Fundus Analysis（眼底分析）

对一张眼底照相（fundus photograph）进行视觉分析后产出的结构化结果。包含疾病检测结果、病灶描述、自然语言叙述，以及向后兼容的青光眼概率和杯盘比。是所有下游消费者（角色提示词、Director 综合、引用校验、前端展示）的唯一数据来源。

## Disease Finding（疾病发现）

单个疾病的检测结果，包含疾病名称、严重度分级、置信度和检测来源。一个眼底分析可以包含多个疾病发现。

## Lesion Description（病灶描述）

单个病灶的结构化描述，包含类型（如微血管瘤、硬性渗出）、位置（如黄斑区、周边部）和自然语言描述。由 VLM 生成，LegacyPipeline 不产出此项。

## Analysis Pipeline（分析管线）

可替换的视觉分析后端接口。所有实现接收眼底图路径和工作目录，返回 FundusAnalysis。调用方不关心具体使用了什么模型。当前有三种实现：LegacyPipeline、VLMPipeline、EnsemblePipeline。

## Legacy Pipeline（遗留管线）

封装现有 SwinV2 青光眼分类器和 SegFormer 视杯/视盘分割器的 AnalysisPipeline 实现。仅产出青光眼相关结果（概率、杯盘比、分割图），是多病种升级前的默认后端。

## VLM Pipeline（VLM 管线）

使用眼科专用视觉-语言模型（Vision-Language Model）的 AnalysisPipeline 实现。能直接从眼底图中识别多种病变特征并用自然语言描述。待选定具体模型后填入实现。

## Ensemble Pipeline（融合管线）

同时运行 LegacyPipeline 和 VLMPipeline 并合并结果的 AnalysisPipeline 实现。冲突时标记来源供人工判断。依赖 VLMPipeline 接入后才有效。

## Graph Retriever（图检索器）

基于知识图谱的证据检索器。与现有 BM25/向量检索并行工作，作为第三路加入 RRF 融合。返回格式与现有检索器兼容，额外包含遍历路径信息。

## Knowledge Graph（知识图谱）

眼科领域的结构化知识表示。节点类型包括疾病、症状、体征、检查、治疗、药物、指南、解剖结构；关系类型包括因果、指示、治疗、禁忌等。用于支持多跳推理和跨概念关联检索。

## Agent（智能体）

多智能体协作框架中的最小执行单元。具有名称、角色描述和执行能力。套壳阶段仅定义 execute 方法，plan 方法作为 collaborative 模式的可选扩展。

## Orchestrator（编排器）

负责协调多个 Agent 执行的组件。根据 MULTI_AGENT_MODE 配置选择不同的编排策略：ParallelOrchestrator（并发）、CollaborativeOrchestrator（协作，TODO）、AdaptiveOrchestrator（自适应，TODO）。

## Parallel Orchestrator（并行编排器）

将所有角色 Agent 同时执行的编排器。角色间无消息传递，耗时约等于最慢的那一次。行为与改造前的 ThreadPoolExecutor 并发逻辑完全等价。

## Message Bus（消息总线）

Agent 间通信的发布-订阅机制。collaborative/adaptive 模式的核心组件，parallel 模式不需要。套壳阶段仅留占位，待协作模式启动时再设计和实现。

## Citation Verifier（引用校验器）

逐句核查报告中事实性断言是否被标注的参考资料真实支持的第 7 个 Agent。不支持的句子允许删除或打回重写，始终无法通过则拒答。在所有协作模式下都作为最后一个 Agent 运行。

## Director（综合智能体）

合并全部角色子报告、消解轻微冲突、产出唯一一份诊断报告的智能体。不属于 AnalysisPipeline，而是报告生成流程的第二阶段。

## Evidence（证据）

从知识库检索到的带出处的文本片段。每条证据有唯一编号，在提示词中以 [n] 形式引用。所有角色共享同一套编号体系，确保 Director 汇总时不会串号。
