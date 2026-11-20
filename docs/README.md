# 文档索引

| 文档 | 内容 |
| --- | --- |
| [项目 README](../README.md) | 安装、启动、演示和贡献 |
| [架构说明](ARCHITECTURE.md) | 模块边界、请求流程和设计取舍 |
| [数据对象](DATA_MODELS.md) | 数据结构、字段归属与兼容约定 |
| [部署指南](DEPLOY.md) | Linux 部署、反向代理、运维与备份 |
| [领域术语](../GLOSSARY.md) | 项目使用的眼科与工程术语 |
| [后端 README](../backend/README.md) | API、配置、检索与后端模块索引 |
| [前端 README](../frontend/README.md) | React 页面、开发模式和调试 |
| [示例数据](../samples/README.md) | 眼底照片、临床记录、叠加图和报告样式 |
| [开发工具](../tools/README.md) | 账号隔离自检与截图 |

`diagrams/` 保存历次设计的 SVG 和 Draw.io 源文件。其中的固定六角色流程属于上游设计；当前报告流程见[架构说明](ARCHITECTURE.md)。

## 历史方案与研究

- 11 月 19 日的[业务模块盘点](research/业务模块说明.md)与[项目改进建议](research/项目改进建议.md)保留审阅时的现状，已落地的修改见[更新记录](../update/README.md)。

- [眼科 Copilot 方案](SPEC-Ophthalmology-Copilot.md)记录早期计划，顶部列有当前实现对照。
- [ADR-0001](adr/0001-analysis-pipeline-seam.md)记录旧视觉管线接口及其后续调整。
- [眼科 VLM、GraphRAG 和多 Agent 研究](research/ophthalmology-vlm-graphrag-multiagent-research.md)记录调研时的外部方案和评估设想。

- [彩色眼底照多病种模型选型](research/retinal-disease-model-selection.md)比较 FLAIR、RETFound 和 VisionFM 等眼底模型，记录现有 FLAIR 验证缺口。
- [眼科 Copilot 文献、数据与测试准备](research/ophthalmology-copilot-evidence-and-evaluation.md)记录模型、诊疗资料、公开数据与评估草案。

功能变更时同步维护对应模块的 README。历史方案中的外部模型能力、性能估计与时间表以其原始记录为准。

## 引用

```bibtex
@inproceedings{liu2025medchat,
  title     = {{MedChat}: A Multi-Agent Framework for Multimodal Diagnosis with Large Language Models},
  author    = {Liu, Philip R. and Bansal, Sparsh and Dinh, Jimmy and Pawar, Aditya and Satishkumar, Ramani and Desai, Shail and Gupta, Neeraj and Wang, Xin and Hu, Shu},
  booktitle = {2025 IEEE 8th International Conference on Multimedia Information Processing and Retrieval (MIPR)},
  year      = {2025},
  pages     = {456--462},
  doi       = {10.1109/MIPR67560.2025.00078}
}
```
