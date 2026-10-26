# 架构与设计

OcuPanel 的整体设计与关键取舍。使用说明见 [根目录 README](../README.md)，
后端实现细节见 [`backend/README.md`](../backend/README.md)，
前端见 [`frontend/README.md`](../frontend/README.md)，部署见 [`DEPLOY.md`](DEPLOY.md)。

---

## 方法流程

核心思想：让每个智能体只聚焦一个窄领域的临床角色，模拟真实的多学科会诊；
再用一个独立的校验智能体，把「看起来合理但没有依据」的句子挡在成品之外。

<p align="center">
  <img src="diagrams/pipeline.svg" alt="OcuPanel 主链路：眼底图上传 → 影像分析 → 证据检索 → 六专科并发 → Director 综合" width="720">
</p>

1. **视觉预处理** — SwinV2 分类器输出青光眼概率 *p*，分箱为「无青光眼 / 可能 / 较可能 / 检测到青光眼」；
   SegFormer 分割器输出视杯与视盘掩码，据此算杯盘比（CDR）。这两个数字是后面所有文字的地基。
2. **核心提示词** — 用自然语言概括 *p* 与 CDR，可附加临床医生备注。
3. **证据检索** — 本地检索知识语料，得到带出处的证据包（编号 + 出处）。
4. **角色生成** — 元提示词让模型列出相关临床角色（眼科医生、验光师、药师等）；
   每个角色拿到核心提示词 + 本专业的窄指令，各自撰写聚焦的子报告。
5. **Director 综合** — 另一个模型实例合并全部子报告，消解轻微冲突，产出唯一一份诊断报告。
6. **引用校验（第 7 个智能体）** — 逐句核对 `[n]` 是否真的支撑该句，不支撑的打回重写，再复核一轮。
7. **输出** — 报告正文、概率、CDR、子报告、证据包、校验结果返回客户端，支持追问与 PDF 导出。

第六步既可能让流程回头（重生成），也可能让流程关门（拒答），所以没画进主链路。
六个专科互不依赖，用 `ThreadPoolExecutor` 并发——串行时整条链路要 8 分钟以上，
并发后约等于最慢的那一次。

## 核心贡献

| # | 贡献 | 意义 |
|---|---|---|
| 1 | **多智能体推理**：眼科医生、验光师、药师等角色 + Director 智能体 | 降低幻觉，反映真实临床协作 |
| 2 | **CAD ⇄ LLM 紧耦合**：SwinV2 分类器（青光眼概率）+ SegFormer 分割器（视杯 / 视盘掩码） | 让语言输出锚定在可验证的图像特征（如 CDR）上 |
| 3 | **浏览器客户端** | 支持交互式问答与 PDF 报告下载，由 FastAPI 直接托管 |
| 4 | **引用校验智能体**：第 7 个 Agent 逐句核对引用，不支撑的句子打回重写 | 把「看起来合理」的话挡在报告之外，幻觉可被定位、可被修正 |

## 与本项目的关系

本项目基于 Philip Liu 等人的 *Multi-Agent Diagnosis using Multimodal Large Language Models*
（MIPR 2025，引用见根 README）改造而来，在原仓库基础上完成了以下本地化改造：

1. 前端从原生 HTML/JS 重写为 **React + Vite**（旧版原生文件已随重构删除，仓库只保留 React 版本）；
2. 后端（FastAPI）**直接托管前端构建产物**，一条命令即可同时启动 API 和页面；
3. **多用户账号体系**：SQLite 存账户、会话与报告，所有数据按 `user_id` 隔离；
   每人在「个人设置」里填自己的 LLM API Key（服务端 Fernet 加密），代码中不再硬编码任何密钥；
4. 新增**证据检索**与**引用校验**两条链路，让结论可追溯、无据即拒答。

## 目录结构

```
OcuPanel/
├── backend/                    # FastAPI 后端（同时托管前端页面）
│   ├── api/                    #   REST 路由：account.py / chat.py / report.py
│   ├── schemas/                #   Pydantic 请求/响应模型
│   ├── classifier/             #   SwinV2 青光眼分类器
│   ├── segmenter/              #   SegFormer 视杯/视盘分割 + CDR 计算
│   ├── knowledge/corpus/       #   知识语料（示例，正式使用需换权威指南）
│   ├── main.py                 #   应用入口（路由 / CORS / 静态托管 / 启动）
│   ├── storage.py              #   SQLite 数据层 + Key 加密
│   ├── auth.py                 #   登录态（令牌签发、校验、注销）
│   ├── config.py               #   环境变量集中管理
│   ├── paths.py                #   output/ 与 img_store/ 路径解析
│   ├── report_generator.py     #   报告生成 / Director 合成 / PDF 导出
│   ├── retrieval.py            #   证据检索（BM25 + 多语言向量 + RRF 融合）
│   ├── verifier.py             #   引用校验智能体
│   ├── check_llm.py            #   LLM 连通性自检
│   └── README.md               #   后端实现细节
├── frontend/                   # React + Vite 前端
│   ├── src/                    #   App.jsx / api.js / components/ / styles.css
│   └── README.md               #   前端与交互说明
├── tools/
│   ├── shot.py                 #   无头 Chrome 截图（CDP，仅标准库）
│   └── check_isolation.py      #   多用户隔离自检（24 项）
├── samples/                    # 测试样本（眼底图、临床记录、样例报告）
├── docs/
│   ├── ARCHITECTURE.md         #   本文档
│   ├── DEPLOY.md               #   云服务器部署指南
│   └── diagrams/               #   流程图（纯 SVG，无外部依赖）
└── README.md                   # 使用说明
```

## 关键取舍

**为什么用 SQLite 而不是 Postgres / MySQL。** 单机、单进程、用户量小，一个文件就够，
零额外服务、零运维。所有查询以 `user_id` 为第一过滤条件，越权统一 404。
真要横向扩容时，`storage.py` 是唯一需要重写的地方。

**为什么用令牌而不是 JWT。** 注销要能真正失效。随机令牌存 `sessions` 表，
删一行就下线；JWT 在过期前无法撤销，只能再维护一张黑名单，反而更麻烦。

**为什么单进程。** 每个 Uvicorn worker 都会独立加载一遍 torch 与三个模型，
内存线性叠加。数据层本身支持多进程，瓶颈在模型。

**为什么校验不合格就拒答。** 医学场景里"看起来对的报告"比"没有报告"更危险。
所以删到不成篇就整篇重生成，仍不合格就直接告诉用户拿不到有依据的结论，
并列出未通过的断言——不交未校验的成品。

**为什么模型各自成模块而不是一个大文件。** 分类器、分割器、检索、校验、生成各有独立的
输入输出契约，可以单独替换或关闭（`RAG_ENABLED` / `VERIFY_ENABLED`），也便于做 A/B 对比。
