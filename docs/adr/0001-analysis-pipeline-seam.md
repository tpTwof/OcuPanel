# ADR-0001: AnalysisPipeline 作为唯一视觉分析接缝

> 历史设计/调研记录，不代表当前实现或可用配置。当前结构、能力与约定以 [ARCHITECTURE.md](../ARCHITECTURE.md) 和各模块 README 为准；文中旧路径和视觉管线配置已被后续重构替代。

## 状态

已被当前按业务分层的设计替代；保留用于追溯历史决策。

## 背景

OcuPanel 原有架构中，`report_generator.generate_reports()` 直接调用 `classifier.predict_glaucoma()` 和 `segmenter.segment_optic_disc_cup()`，将视觉分析与报告生成紧耦合。升级目标是引入眼科 VLM 实现多病种检测，同时保持现有青光眼功能不受影响。

需要决定：如何在不破坏现有功能的前提下，为新的视觉模型预留接入点？

## 决策

引入 `AnalysisPipeline` Protocol 作为**唯一主接缝**。所有下游模块（角色提示词构建、Director 综合、引用校验、PDF 生成、前端展示）只消费 `FundusAnalysis` 数据结构，不关心它是怎么产生的。

三种实现通过环境变量 `ANALYSIS_PIPELINE` 切换：
- `legacy`：封装现有 SwinV2 + SegFormer（默认，保持可运行）
- `vlm`：眼科 VLM 后端（stub，待选定模型）
- `ensemble`：Legacy + VLM 融合（stub，依赖 vlm）

## 理由

### 为什么是唯一接缝而非多个

如果让 VLM 直接注入到 `generate_reports()` 内部，每加一个新模型就要改这个 90 行的函数。而 `FundusAnalysis` 作为统一输出契约，使得换模型、加新病种、改 VLM 都不需要碰任何下游模块。

### 为什么用 Protocol 而非继承

Python Protocol 是结构子类型，不需要显式继承。各 Pipeline 实现可以独立演化，只要满足 `analyze(image_path, job_dir) -> FundusAnalysis` 签名即可。这比抽象基类更灵活，也避免了强制继承带来的耦合。

### 为什么 LegacyPipeline 要完整实现而非 stub

它是套壳阶段唯一能产出真实结果的 Pipeline。如果它也做 stub，整个系统在模型选定前完全不可用，无法验证改造是否正确。完整实现仅需约 30 行代码，成本极低。

### 为什么不直接替换 SwinV2/SegFormer

VLM 尚未选定，且 VLM 的幻觉风险可能高于专用 CAD 模型。保留 LegacyPipeline 作为 fallback 和 ensemble 组件，是安全冗余而非技术债。

## 后果

- **正面**：后续接入任何视觉模型只需新增一个类实现 Protocol，不改任何现有代码
- **正面**：`FundusAnalysis` 的 `extra: dict` 兜底字段避免了频繁改数据类签名
- **负面**：多一层间接调用，调试时需要跟踪 Pipeline 选择逻辑
- **负面**：`FundusAnalysis` 的字段设计如果不够通用，后续可能需要扩展（已通过 `extra` 缓解）

## 相关文件

- `backend/pipeline/protocol.py` — AnalysisPipeline Protocol 定义
- `backend/pipeline/types.py` — FundusAnalysis / DiseaseFinding / LesionDescription 数据类
- `backend/pipeline/legacy.py` — LegacyPipeline 完整实现
- `backend/pipeline/vlm_stub.py` — VLMPipeline stub
- `backend/pipeline/ensemble_stub.py` — EnsemblePipeline stub
- `backend/config.py` — ANALYSIS_PIPELINE 配置项
