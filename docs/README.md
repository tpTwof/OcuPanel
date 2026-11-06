# 文档索引与维护范围

本轮同步日期：2026-11-06。当前行为以代码及对应测试为依据，功能修改时同步所属模块说明。历史方案、示例语料和本地验证记录不能作为已上线能力。

| 文档 | 用途与状态 |
|---|---|
| [项目 README](../README.md) | 当前环境、启动、入口和限制 |
| [ARCHITECTURE](ARCHITECTURE.md) | 当前模块边界与流程 |
| [DATA_MODELS](DATA_MODELS.md) | 数据对象归属、类型与兼容策略 |
| [DEPLOY](DEPLOY.md) | 部署与运维；Linux 环境仍需现场验证 |
| [GLOSSARY](../GLOSSARY.md) | 当前领域术语 |
| [后端](../backend/README.md) / [前端](../frontend/README.md) | API、配置、页面与开发说明 |
| [vision](../backend/vision/README.md) | 算法、输出与真实样本验证 |
| [chat](../backend/chat/README.md) | 形态、提示词与上下文预算 |
| [report](../backend/report/README.md) | 生成、存储、PDF 生命周期 |
| [agents](../backend/agents/README.md) | 专科、综合、引用校验与工具边界 |
| [llm](../backend/llm/README.md) | 模型客户端与调用约定 |
| [旧升级 Spec](SPEC-Ophthalmology-Copilot.md) | 历史规划，顶部附当前状态对照 |
| [ADR-0001](adr/0001-analysis-pipeline-seam.md) | 已被替代的历史决策，顶部给出当前接入点 |
| [研究记录](research/ophthalmology-vlm-graphrag-multiagent-research.md) | 历史外部资料，未在本轮重新验证，未集成为项目能力 |
| `backend/knowledge/corpus/*.md` | 四份检索演示语料，不是项目说明或经验证的指南全文 |
| [英文报告样例](../samples/report_sample_en.md) | 历史输出样式，不是当前推理结果或模型评估基准 |

环境统一以 Python 3.13 为开发基线，本机项目为 3.13.3；前端本机为 Node 24.15.0 / npm 11.12.1。其他解释器版本未完成全量环境验证，不用“Python 3.10+”或“3.13+”承诺支持。系统默认解释器可能不同，应明确使用虚拟环境。

历史文档的外部模型排名、硬件要求、性能和时间表仅代表原记录。本轮不改写医学演示语料，也不以文档整理代替临床或外部模型评估。
