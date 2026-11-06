# Spec: OcuPanel → 眼科智能诊疗 Copilot（GraphRAG + Multi-Agent + VLM）

> 历史设计/调研记录，不代表当前实现或可用配置。当前结构、能力与约定以 [ARCHITECTURE.md](ARCHITECTURE.md) 和各模块 README 为准；文中旧路径和视觉管线配置已被后续重构替代。

## 当前实现对照（2026-11-06）

下文原方案按历史背景保留，不是当前待执行需求。当前运行环境与启动方式见 [项目 README](../README.md)，文档分类见[文档索引](README.md)。

| 历史规划 | 当前状态 |
|---|---|
| AnalysisPipeline 与 legacy/vlm/ensemble 切换 | 已删除，使用 vision.analyze_fundus → EyeAnalysis；只实现青光眼 |
| FundusAnalysis 与冗余青光眼顶层字段 | 已删除，病种结果属于 vision.models，按 diseases 字典组织 |
| VLM 描述、多病灶与糖网分级 | 未实现；severity 未评估，不能按分类概率分期 |
| GraphRAG、多跳检索 | 只有 graphrag/ 占位；报告实际为 BM25/向量/RRF |
| collaborative/adaptive、消息总线、轨迹表 | 未实现；报告只支持 parallel，其他模式明确报错 |
| 简单角色提示词 | 已改为共享 SpecialistAgent 实现与受限证据工具循环；Director 综合，Verifier 修订复核 |
| report_generator 与中央 api/ | 已按 user/chat/report 业务归属拆分为 api.py、service.py、models.py |
| 对话入口 | 普通聊天与眼科助手两种形态；仅提交分析时调用报告链 |
| 图片权限与 PDF | 图片未做所属用户检查；PDF 仍重新生成，尚无历史报告直接导出 |

以下旧模型建议、配置清单、数据库扩展和时间表均未获当前实现承诺，不得照抄为可用配置或部署步骤。选型与外部性能数据若要重新使用，需要单独重新核验。

## 历史 Problem Statement

当前 OcuPanel 系统存在以下局限：

1. **疾病覆盖窄**：影像分析仅支持青光眼（SwinV2 分类 + SegFormer 视杯/视盘分割），对糖尿病视网膜病变（DR）、年龄相关性黄斑变性（AMD）、高血压视网膜病变等常见眼底疾病只能基于文字问答，无法从图像中提取特征。
2. **检索范式原始**：证据检索使用 BM25 + 多语言向量 + RRF 融合的扁平检索，缺乏医学知识之间的结构化关联（如"DR → 微血管瘤 → 非增殖期 → 随访间隔"的推理链），无法支持多跳推理和跨概念关联。
3. **多智能体协作简单**：六个专科角色并发撰写子报告后由 Director 一次性综合，角色之间没有信息传递、协商或分工优化机制，本质上是"并行生成 + 单次汇总"，不是真正的协作推理。
4. **视觉理解与语言推理割裂**：CAD 模型（SwinV2/SegFormer）只输出概率值和 CDR 数字，所有视觉语义理解完全依赖 LLM 的文字提示词，丢失了眼底图中丰富的形态学信息（出血灶、渗出、新生血管等）。
5. **知识语料单一**：仅有 4 份青光眼相关指南文档，缺乏 DR、AMD、RVO 等疾病的标准指南和分级标准。

用户希望将系统升级为基于 **GraphRAG（图检索增强）** 与 **Multi-Agent（多智能体协作）** 的眼科智能诊疗 Copilot，覆盖多种眼底疾病，并引入眼科专用 VLM 实现端到端的视觉-语言联合推理。

## Solution

将 OcuPanel 从"青光眼单病种多角色报告生成器"升级为"多病种眼科智能诊疗 Copilot"，核心升级三条主线：

1. **GraphRAG 知识引擎**：将扁平语料库重构为眼科领域知识图谱（疾病-症状-体征-检查-治疗-药物-指南节点 + 关系边），检索时沿图结构做多跳遍历，让证据包自带推理链路而非孤立片段。
2. **Multi-Agent 协作框架**：将现有的"并发写报告 + Director 汇总"升级为带消息传递、任务分配、共识达成的协作式多智能体系统，支持动态角色编排（根据初步诊断结果决定需要哪些专家介入）。
3. **VLM 视觉-语言联合推理**：引入眼科专用或多模态医学 VLM，替代或补充现有的 SwinV2+SegFormer 管线，使系统能直接从眼底图中识别多种病变特征并用自然语言描述，而不仅限于青光眼概率和 CDR。

三条主线通过统一的 `AnalysisPipeline` 接口串联，保持现有 API 契约不变。

## User Stories

### 多病种诊断
1. As an ophthalmologist, I want to upload a fundus photo and receive a preliminary assessment covering DR, glaucoma, AMD, and other common fundus diseases, so that I can triage patients more efficiently.
2. As a clinician, I want the system to automatically detect which diseases are present in a fundus image and generate disease-specific analysis, so that I don't need to manually specify the suspected diagnosis.
3. As a diabetic patient's primary care physician, I want to upload a fundus photo and get a DR grading (mild/moderate/severe NPDR, PDR) with lesion descriptions, so that I can determine referral urgency.
4. As a retina specialist, I want the system to describe specific lesions (microaneurysms, hard exudates, cotton wool spots, neovascularization) visible in the fundus image, so that I can verify my own findings against an AI second opinion.
5. As a glaucoma specialist, I want the existing CDR and glaucoma probability analysis to continue working alongside new multi-disease capabilities, so that the upgrade doesn't regress current functionality.

### GraphRAG 知识检索
6. As a clinician, I want the system to retrieve evidence through multi-hop reasoning (e.g., "patient has microaneurysms → suggests mild NPDR → AAO recommends annual follow-up"), so that recommendations are grounded in guideline-based reasoning chains rather than isolated text snippets.
7. As a researcher, I want to see the knowledge graph traversal path alongside each evidence citation, so that I can audit how the system connected a visual finding to a clinical recommendation.
8. As a developer, I want to add new disease guidelines by importing structured documents that automatically populate the knowledge graph, so that expanding coverage doesn't require rewriting retrieval logic.
9. As a clinician asking about drug interactions for a diabetic glaucoma patient, I want the system to traverse from "prostaglandin analogs" through "contraindications" to "diabetic macular edema risk", so that I get cross-disease safety information.
10. As a user, I want the hybrid retrieval (BM25 + vector + graph) to gracefully degrade when the graph index is unavailable, so that the system remains functional during graph construction or failures.

### Multi-Agent 协作
11. As a system designer, I want agents to negotiate and share intermediate findings (e.g., the VLM agent shares lesion detections with the DR specialist agent before it writes its sub-report), so that each agent works with complete relevant information.
12. As a clinician, I want the system to dynamically select which specialist agents to invoke based on initial image analysis (e.g., skip the glaucoma specialist if no optic disc abnormalities are detected), so that reports are focused and generation is faster.
13. As a quality reviewer, I want to see the inter-agent communication log showing how consensus was reached on conflicting findings, so that I can understand the reasoning process behind the final report.
14. As a system operator, I want the multi-agent orchestration to be configurable (add/remove roles, change collaboration patterns) without code changes, so that the system can adapt to different clinical settings.
15. As a developer, I want the existing citation verifier to work as a first-class agent within the new multi-agent framework, so that verification remains integral rather than being bolted on.

### VLM 视觉理解
16. As a clinician, I want the VLM to provide free-text descriptions of fundus findings in addition to structured labels, so that I get nuanced observations that fixed-category classifiers miss.
17. As a developer, I want to swap between different VLM backends (local model vs. API-based) through configuration, so that I can test multiple models without changing pipeline code.
18. As a researcher, I want the VLM output to include confidence scores or attention maps for detected lesions, so that I can assess reliability of each visual finding.
19. As a clinician in a resource-limited setting, I want the system to work with lightweight VLMs that run on consumer GPUs, so that deployment doesn't require datacenter infrastructure.
20. As a system integrator, I want the VLM to coexist with the existing SwinV2/SegFormer pipeline (ensemble mode), so that I can compare outputs and gradually transition.

### 兼容性与迁移
21. As an existing user, I want all current features (login, per-user LLM config, chat, PDF export, citation verification) to continue working unchanged, so that the upgrade is non-disruptive.
22. As a developer, I want the new components to be individually toggleable via environment variables (GRAPH_RAG_ENABLED, VLM_ENABLED, MULTI_AGENT_MODE), so that I can A/B test each upgrade independently.
23. As a deployer, I want the system to start in "legacy mode" by default and opt into new features incrementally, so that production stability is maintained during migration.
24. As a tester, I want the existing test samples and evaluation flow to work with both old and new pipelines, so that I can benchmark improvements quantitatively.
25. As a frontend developer, I want the API response schema to remain backward-compatible (same fields, new optional fields added), so that the frontend doesn't need simultaneous breaking changes.

## Implementation Decisions

### Decision 1: AnalysisPipeline — 统一视觉分析接口（核心接缝）

这是整个升级的**唯一主接缝**。现有 `report_generator.generate_reports()` 直接调用 `classifier.predict_glaucoma()` 和 `segmenter.segment_optic_disc_cup()`，耦合了具体模型。引入 `AnalysisPipeline` 抽象层：

```python
@dataclass
class FundusAnalysis:
    """统一的视觉分析结果，所有下游消费者只看这个结构。"""
    # 向后兼容字段
    glaucoma_prob: float | None = None
    cup_to_disc_ratio: float | None = None
    segmented_image_path: str | None = None
    
    # 新增多病种字段
    diseases_detected: list[DiseaseFinding] = field(default_factory=list)
    lesion_descriptions: list[LesionDescription] = field(default_factory=list)
    vlm_narrative: str = ""           # VLM 自由文本描述
    raw_model_outputs: dict = field(default_factory=dict)  # 各模型原始输出留痕

@dataclass  
class DiseaseFinding:
    disease: str          # "diabetic_retinopathy", "glaucoma", "amd", ...
    severity: str         # "mild_npdr", "moderate_npdr", "severe_npdr", "pdr", ...
    confidence: float
    source: str           # "vlm", "swinv2", "ensemble"

@dataclass
class LesionDescription:
    type: str             # "microaneurysm", "hard_exudate", "hemorrhage", ...
    location: str         # "macula", "periphery", "optic_disc", ...
    description: str      # VLM 生成的自然语言描述
    confidence: float | None = None

class AnalysisPipeline(Protocol):
    """可替换的视觉分析后端。"""
    def analyze(self, image_path: str, job_dir: Path) -> FundusAnalysis: ...
```

三种实现：
- `LegacyPipeline`：封装现有 SwinV2 + SegFormer，返回 `FundusAnalysis`（仅填充 glaucoma_prob / CDR / segmented_image_path）
- `VLMPipeline`：调用眼科 VLM，填充全部字段
- `EnsemblePipeline`：同时运行 Legacy + VLM，合并结果（冲突时标记来源供人工判断）

`report_generator.generate_reports()` 改为接收 `FundusAnalysis` 而非直接调模型。选择哪个 Pipeline 由环境变量 `ANALYSIS_PIPELINE=legacy|vlm|ensemble` 控制。

**为什么这是唯一主接缝**：所有下游（角色提示词构建、Director 综合、引用校验、PDF 生成、前端展示）都只消费 `FundusAnalysis`，不关心它是怎么产生的。换模型、加新病种、改 VLM 都不需要碰这些模块。

### Decision 2: GraphRAG 知识引擎架构

在现有 `retrieval.py` 的 `Retriever` 接口之上扩展图检索能力，保持 `search()` 签名不变：

**知识图谱构建**：
- 节点类型：`Disease`, `Symptom`, `Sign`, `Examination`, `Treatment`, `Drug`, `Guideline`, `Anatomy`
- 关系类型：`causes`, `indicates`, `treats`, `contraindicated_in`, `monitors`, `located_in`, `graded_by`
- 构建方式：从 Markdown 指南文档中用 LLM 辅助抽取实体和关系，存入轻量图存储
- 图存储选型：**NetworkX 内存图**（语料规模 <10K 节点时零依赖、毫秒级遍历）；后续可切换到 Neo4j / NebulaGraph

**检索策略**：
- 查询 → 实体识别 → 图锚点定位 → k-hop 邻居遍历 → 路径排序 → 与 BM25/向量结果 RRF 融合
- 保留现有 `_search_bm25` / `_search_vector` / `_rrf` 作为独立检索路，图检索作为第三路加入融合
- 新增配置项：`GRAPH_RAG_ENABLED`, `GRAPH_HOP_K`, `GRAPH_PATH_SCORE_WEIGHT`

**数据结构兼容**：图检索返回的结果仍然是 `list[dict]`（与现有 Chunk 格式一致），增加 `graph_path` 字段记录遍历路径。`format_evidence_block()` 可选择性地展示路径信息。

### Decision 3: Multi-Agent 协作框架

将现有的 `ThreadPoolExecutor` 并发改为结构化的 Agent 协作协议：

**Agent 基类**：
```python
class Agent(Protocol):
    name: str
    role_description: str
    
    def plan(self, context: AgentContext) -> AgentPlan: ...
    def execute(self, task: AgentTask, context: AgentContext) -> AgentResult: ...
```

**协作模式**（由 `MULTI_AGENT_MODE` 环境变量控制）：
- `parallel`（默认，向后兼容）：现有六角色并发 + Director 汇总，行为不变
- `collaborative`：引入 Orchestrator Agent 做任务分配，Agent 间通过 `MessageBus` 共享中间发现
- `adaptive`：Orchestrator 根据 `FundusAnalysis.diseases_detected` 动态选择激活哪些角色

**消息总线**：进程内发布-订阅，Agent 可以声明自己关心的消息类型（如 `lesion_detected`, `drug_interaction_found`），Orchestrator 负责路由。

**关键约束**：
- 所有协作模式下，CitationVerifier 始终作为最后一个 Agent 运行
- 协作日志写入 `agent_trace` 表（新增），供前端 DebugDrawer 展示
- 超时和错误处理沿用现有的 per-role 隔离策略

### Decision 4: 知识语料扩展方案

当前仅有 4 份青光眼指南。扩展计划：

| 疾病 | 优先语料来源 | 格式 |
|------|-------------|------|
| 糖尿病视网膜病变 | AAO PPP Diabetic Retinopathy, ICO Guidelines | Markdown |
| AMD | AAO PPP Age-Related Macular Degeneration | Markdown |
| RVO | AAO PPP Retinal Vein Occlusion | Markdown |
| 高血压视网膜病变 | Keith-Wagener-Barker 分级标准 | Markdown |
| 药物 | 眼科常用药物说明书 + 相互作用数据库 | 结构化 JSON |

每份语料入库时同步触发图索引增量构建。语料目录结构不变（`backend/knowledge/corpus/*.md`），新增 `backend/knowledge/graph/` 存放图索引缓存。

### Decision 5: 前端兼容性

API 响应 schema 向后兼容扩展：
- `generate-report-content` 响应新增可选字段：`diseases_detected`, `lesion_descriptions`, `vlm_narrative`, `agent_trace`
- 现有字段（`summary`, `cup_to_disc_ratio`, `img_name`, `evidence`, `verification`, `rejected`）保持不变
- 前端按需渲染新字段：有则展示多病种分析卡片和 VLM 描述，无则退化为现有青光眼报告视图
- DebugDrawer 扩展显示 Agent 协作轨迹和图检索路径

### Decision 6: 配置与开关体系

所有新功能通过环境变量独立控制，支持渐进式启用：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ANALYSIS_PIPELINE` | `legacy` | `legacy` / `vlm` / `ensemble` |
| `VLM_MODEL` | (空) | VLM 模型标识符或 API 端点 |
| `VLM_BACKEND` | `local` | `local` / `api` |
| `GRAPH_RAG_ENABLED` | `0` | 是否启用图检索 |
| `GRAPH_STORE` | `networkx` | `networkx` / `neo4j` |
| `MULTI_AGENT_MODE` | `parallel` | `parallel` / `collaborative` / `adaptive` |
| `AGENT_TRACE_ENABLED` | `0` | 是否记录 Agent 协作日志 |

默认值全部指向现有行为，确保升级后零配置即可正常运行。

### Decision 7: 数据库 Schema 扩展

新增两张表，不影响现有五张表：

```sql
-- Agent 协作轨迹
CREATE TABLE IF NOT EXISTS agent_traces (
    id              TEXT PRIMARY KEY,
    report_id       TEXT REFERENCES reports(id) ON DELETE CASCADE,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_name      TEXT NOT NULL,
    phase           TEXT NOT NULL,     -- 'plan', 'execute', 'message', 'verify'
    input_summary   TEXT,
    output_summary  TEXT,
    duration_ms     INTEGER,
    created_at      REAL NOT NULL
);

-- 知识图谱元数据
CREATE TABLE IF NOT EXISTS graph_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
```

### Decision 8: VLM 集成策略

VLM 作为 `AnalysisPipeline` 的一个实现注入，不替代现有 CAD 模型：

- **本地部署**：通过 transformers / vLLM 加载开源眼科 VLM，GPU 推理
- **API 调用**：通过 OpenAI 兼容接口调用云端多模态模型（GPT-4o, Qwen-VL-Max 等）
- **混合模式**：本地 VLM 做初筛 + 云端 VLM 做精细描述（可配置）

VLM 提示词模板按疾病类型参数化，不同疾病的关注点不同（DR 关注出血/渗出，青光眼关注视盘/RNFL，AMD 关注玻璃膜疣/CNV）。

## Testing Decisions

### 测试原则
- 只测外部行为（API 响应、PDF 内容、前端渲染），不测内部实现细节
- 每个新功能都有对应的 feature flag，测试覆盖 flag on/off 两种状态
- 回归测试确保 `ANALYSIS_PIPELINE=legacy` + `GRAPH_RAG_ENABLED=0` + `MULTI_AGENT_MODE=parallel` 时行为与升级前完全一致

### 测试模块

| 模块 | 测试重点 | 先例 |
|------|---------|------|
| `AnalysisPipeline` | LegacyPipeline 输出与现有 `predict_glaucoma` + `calculate_cup_to_disc_ratio` 数值一致 | 现有 `samples/` 测试样本 |
| `GraphRetriever` | 图检索返回的证据包含 `graph_path`；图不可用时退回 BM25/vector | 现有 `retrieval.selfcheck_gate()` 自检模式 |
| `MultiAgentOrchestrator` | parallel 模式行为不变；collaborative 模式下 Agent 间消息正确路由 | 现有 `ThreadPoolExecutor` 并发测试 |
| `CitationVerifier` | 在新 pipeline 下仍然正确校验、拒答逻辑不变 | 现有 verifier 测试用例 |
| API `/generate-report-content` | 响应 schema 向后兼容；新字段在有/无 VLM 时正确填充 | 现有 report API 测试 |
| 前端 ReportView | 多病种卡片在有数据时渲染、无数据时隐藏 | 现有组件条件渲染模式 |

### 评估指标
- 多病种检测准确率（与各疾病金标准对比）
- GraphRAG vs 扁平检索的证据相关性（人工标注 + 自动指标）
- Multi-Agent 协作 vs 并发的报告质量（引用校验通过率、临床专家评审）
- 端到端延迟（目标：collaborative 模式 ≤ 2× parallel 模式）

## Out of Scope

1. **OCT 影像分析**：本阶段仅处理彩色眼底照相（fundus photography），OCT/OCT-A 分析作为后续迭代
2. **实时视频流分析**：不支持眼底镜实时视频输入
3. **电子病历（EMR）集成**：不与医院 HIS/PACS 系统对接，数据仍通过手动上传
4. **训练/微调流程**：不包含 VLM 或 CAD 模型的训练代码，仅使用预训练权重
5. **多语言报告**：维持现有的中英双语切换，不新增语种
6. **移动端适配**：前端仍以桌面浏览器为主，不做响应式重构
7. **HIPAA/GDPR 合规认证**：系统定位为研究/辅助工具，不做医疗级合规认证
8. **知识图谱自动更新**：图谱构建为离线批处理，不做实时增量更新

## Further Notes

### 推荐的眼科 VLM 模型（可测试）

以下模型基于 2025 年最新研究整理，按实用性和可获取性排序，均可在当前工程架构中通过 `VLMPipeline` 集成测试。详细研究报告见 [`docs/research/ophthalmology-vlm-graphrag-multiagent-research.md`](research/ophthalmology-vlm-graphrag-multiagent-research.md)。

#### 第一梯队：眼科专用 VLM（强烈推荐优先测试）

| 模型 | 特点 | 获取方式 | GPU 需求 |
|------|------|---------|---------|
| **RetiZero** ⭐首选 | 覆盖 400+ 眼底疾病，零样本 Top-5 准确率 0.843（15 病种），超越 19 位眼科医生平均水平；Nature Communications 2025 | [GitHub: LooKing9218/RetiZero](https://github.com/LooKing9218/RetiZero) | 1× RTX 3090+ |
| **VisionUnite** ⭐对话首选 | 1.24M 图文对 + 889K 模拟医患对话训练，超越 GPT-4V 和 Gemini Pro；IEEE TPAMI 2025 | [GitHub: HUANGLIZI/VisionUnite](https://github.com/HUANGLIZI/VisionUnite) | 1× A100 |
| **RETFound** | 1.6M 视网膜图像 MAE 预训练，ViT-Large；Nature 2023 金标准特征提取器（非 VLM，需搭配 LLM） | [GitHub](https://github.com/rmaphoh/RETFound_MAE) / [HuggingFace: YukunZhou](https://huggingface.co/YukunZhou) | 1× RTX 3090 |
| **MedDr** | 基于 InternVL-Chat 的通用医学 VLM，支持眼底照相 + 多科室影像；MIT 许可 | [HuggingFace: Sunanhe/MedDr_0401](https://huggingface.co/Sunanhe/MedDr_0401) / [GitHub](https://github.com/sunanhe/meddr) | 1× A100 |

#### 第二梯队：眼科文本 LLM + 通用医学多模态

| 模型 | 特点 | 获取方式 | GPU 需求 |
|------|------|---------|---------|
| **Ophtha-LLaMA2** | 眼科报告微调的 LLaMA2，纯文本但眼科理解最强；可作为 VLM 的语言骨干 | arXiv:2312.04906 | 1× A100 |
| **FLAIR** | 将眼科专家知识编码进 CLIP 文本监督，零样本分类优于通用 CLIP；Medical Image Analysis 2025 | 代码可用性待确认 | 1× RTX 3090 |
| **Qwen2.5-VL / Qwen-VL-Max** | 中文多模态能力强，API 即用，适合快速验证 | DashScope API / HuggingFace | API 或 1× A100 |
| **InternVL2.5** | 上海 AI Lab 多模态，医学 benchmark 优秀 | HuggingFace `OpenGVLab/InternVL2` | 1× A100 |
| **BiomedCLIP** | 微软生物医学 CLIP，LoRA 微调可做 DR 筛查 | [HuggingFace: microsoft/BiomedCLIP](https://huggingface.co/microsoft/BiomedCLIP) | 1× RTX 3090 |

#### 第三梯队：轻量级 / API-only（快速验证和资源受限场景）

| 模型 | 特点 | 获取方式 |
|------|------|---------|
| **GPT-4o** | 通用多模态，眼底图理解能力不错，API 即用 | OpenAI API |
| **LLaVA-Med** | 医学指令微调 LLaVA，眼底数据偏少需微调 | [GitHub: microsoft/LLaVA-Med](https://github.com/microsoft/LLaVA-Med) |
| **MiniCPM-V** | 2B 轻量多模态，消费级 GPU 可跑 | HuggingFace |
| **Gemini 2.0 Flash** | Google 多模态，免费额度可用于测试 | Google AI API |

#### 测试优先级与建议

1. **Day 1-2（快速验证）**：用 GPT-4o / Qwen-VL-Max API 接入 `VLMPipeline`，验证端到端流程
2. **Week 1-2（核心 VLM）**：部署 **RetiZero**（多病种零样本）+ **VisionUnite**（对话交互），在 MESSIDOR-2/APTOS/REFUGE 上评估
3. **Week 2-3（特征提取）**：部署 **RETFound** 作为特征提取器，搭配 Ophtha-LLaMA2 构建自定义 VLM 管线
4. **Week 3-4（Ensemble）**：RetiZero + RETFound + API VLM 三路 ensemble，与现有 SwinV2/SegFormer 对比
5. **持续迭代**：用公开数据集做定量评估，逐步替换 Legacy Pipeline

### GraphRAG 实现选型建议

| 方案 | 优点 | 缺点 | 推荐场景 |
|------|------|------|---------|
| **LightRAG** ⭐首选 | 已在医学 QA 领域发表论文验证；索引快（分钟级）；原生增量更新；双层检索（实体+概念） | 生态较新 | 眼科知识库首选 |
| **Microsoft GraphRAG** | 社区摘要 + 全局搜索最强；生产就绪度高 | 索引慢（小时级）；LLM 调用成本高 | 语料 >100 篇、需全局查询时 |
| **nano-graphrag** | 极简实现、可插拔后端、易嵌入现有代码 | 功能有限、规模化未验证 | 原型验证 |
| **自建 NetworkX** | 零依赖、完全可控 | 需手写遍历逻辑 | 语料 <50 篇、定制需求高 |

**推荐路径**：直接用 **LightRAG** 起步（已有医学 QA 论文背书），语料规模扩大后按需迁移到 Microsoft GraphRAG。详细对比见 [`docs/research/ophthalmology-vlm-graphrag-multiagent-research.md`](research/ophthalmology-vlm-graphrag-multiagent-research.md) §2。

### Multi-Agent 框架选型建议

| 框架 | 优点 | 缺点 | 推荐场景 |
|------|------|------|---------|
| **LangGraph** ⭐首选 | 状态图编排、条件分支、持久化状态；最适合自适应诊断流程 | 学习曲线较陡 | 根据 VLM 发现动态选择专家 |
| **AutoGen** | 成熟框架、文档丰富、支持复杂对话模式 | 简单流程过于冗余 | 多专科会诊模拟 |
| **CrewAI** | 角色/任务抽象直观、顺序管线易定义 | 动态协作灵活性不足 | 固定流程的诊断管线 |

**推荐**：用 **LangGraph** 实现 Orchestrator，根据 `FundusAnalysis.diseases_detected` 条件路由到不同专家 Agent。详见研究报告 §3-4。

### 迁移路线图建议

```
Phase 1 (2-4周): AnalysisPipeline + VLM 集成
  → 最小可用：VLM 做辅助描述，现有管线不变
  
Phase 2 (4-6周): GraphRAG 知识引擎
  → 知识图谱构建 + 图检索接入
  
Phase 3 (6-8周): Multi-Agent 协作升级
  → collaborative/adaptive 模式
  
Phase 4 (持续): 语料扩展 + 模型迭代
  → 新疾病覆盖 + VLM 微调
```

### 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| VLM 幻觉比 CAD 模型更严重 | 误报病变 | Ensemble 模式 + CitationVerifier 兜底 |
| 图索引构建质量差 | 检索退化 | 保留 BM25/vector 作为 fallback |
| Multi-Agent 协作增加延迟 | 用户体验下降 | parallel 模式作为默认 + 超时降级 |
| 新语料版权/许可问题 | 法律风险 | 仅使用公开发布的指南原文 |
| VLM GPU 资源不足 | 无法本地部署 | API 模式 + 量化模型 |
