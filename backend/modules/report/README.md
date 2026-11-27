# report

router.py 绑定 multipart、任务查询和存档导出；service.py 负责业务与资源生命周期，queue.py 消费持久任务，generation.py 编排影像、证据和 Agent。models.py 保存内部提交对象与结果契约，assets.py 管理原图，pdf.py 生成 PDF。

## 流程

`REPORT_PIPELINE` 选择报告流程，两条路径共用影像分析、专科撰稿、Director 综合、Verifier 核查与交付状态：

- **v2（默认）**：`generation.generate_v2` → `case_facts.build_case_facts` 按来源整理病例事实（稳定 ID、眼别、原始位置、缺失与冲突）→ `agent/planner.RetrievalPlanner` 制定结构化检索计划 → `knowledge/question_retrieval.retrieve_for_plan` 按问题检索、检查覆盖并最多补检一次 → 统一提示词撰稿 → 核查。
- **legacy**：`generation.generate` 在影像分析后逐病种固定主题检索，再进入撰稿与核查。保留用于新旧对比和回退。

`case_facts.py` 只整理、不判断：不会把「未提供」改写成「未检查」，不会从单眼影像推断另一眼，模型分数保持为模型输出。缺失与冲突会进入撰稿提示词和校验记录的 `case_facts` 字段。

## 交付语义

- 有效报告：核查通过（`pass`）或修订后通过（`rewritten`），可导出 PDF。
- 可标注交付：仍有「资料未覆盖」的断言时，就地标注后以 `rewritten` 交付，标注进入 `verification.annotations`。
- 受限摘要：检索未请求、无可用证据、检索故障，或核查后仍有「资料未覆盖」的未解决断言时，只保留用户输入，状态 `limited`，`delivery_scope=case_input_only`，不能导出诊断 PDF。
- 拒答与故障：`rejected` / `error` 不交付正文。

检索故障（`retrieval_failed`）与没有相关证据（`no_evidence`）分开记录；工具故障不能被当成成功检索，也不能据此判断资料缺失。`verification` 还会写入 `retrieval`（计划、查询、覆盖缺口、失败）、`knowledge_gaps`、`applicability`（材料类型、审核状态、适用条件缺失）与提示词版本，报告存档可复核。前端校验条展示检索问题、语料缺口与来源审核状态；PDF 的参考列表同样标注材料类型与审核状态——引用校验通过不等于条款已通过临床审核。

保持证据编号、verification、拒答和原图来源可追溯。失败的生成或校验不能作为有效报告交付。数据库和归档目录由 core 管理，路径不随模块深度变化。

[后端说明](../../README.md) · [离线测试](../../tests/README.md)

病例备注中用逗号并列的左右眼测量分别保留原文位置。确定性校验发现的编造数值、眼别错误和病种错配必须修正后才能交付。
