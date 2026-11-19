# OcuPanel 项目说明

OcuPanel 面向多种眼部疾病，提供医疗分析辅助、眼科问答和眼底影像报告。上游 MedChat 聚焦青光眼。新增病种应明确其输入、可解释的输出与验证程度。现有能力、安装和运行方式以 [README.md](README.md) 为准；代码分层见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。历史 ADR 和研究记录不能直接当作当前实现。

- 修改前先确认工作区已有改动，保留与本任务无关的内容。
- 始终保持代码可读：用清楚的命名和直接的控制流表达意图，将不同职责放在各自模块；复杂判断只在需要时加简短说明。
- 按改动范围阅读对应模块的 README；接口或行为变化时同步更新其说明。
- 眼科分析与报告仅供研究和开发参考。改动视觉结果、引用证据或拒答逻辑时，保持结果来源与校验状态可追溯。
- 后端和前端的具体约定分别见 [backend/AGENT.md](backend/AGENT.md) 与 [frontend/AGENT.md](frontend/AGENT.md)。
