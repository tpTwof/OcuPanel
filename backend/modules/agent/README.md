# agent

`specialist.py`、`director.py`、`verifier.py` 分别执行专科分析、多病种综合和引用核查；`planner.py` 负责检索规划。`parallel.py` 编排专科，`graphs/verify.py` 是核查的控制流，`roles.py` 定义角色，`models.py` 保存数据契约，`contracts.py` 固定核查返回字段，`prompts/` 与 `tools/` 管理指令和受限工具。通过报告或问答调用，不单独暴露 HTTP 接口。

模型调用统一走 `core/llm/gateway.py`（LangChain ChatOpenAI）；专科一次成稿，不再有证据工具循环——证据全文本来就整块拼在提示词里，循环只会多花调用。核查的"首轮 → 仲裁 → 修订 → 重生成 → 标注/拒答"是 LangGraph 状态机，节点只做一件事，轮数与重生成次数由显式计数器控制，不依赖框架的 recursion_limit。迁移理由与边界见 [ADR-0002](../../../docs/adr/0002-agent-runtime-langgraph.md)。

## 检索规划

`planner.py` 把病例事实转成结构化检索计划：`need_retrieval`、`reason`、`questions`（含 `topic`、`case_fact_ids`、`filters`）与 `missing_information`。Agent 只决定「要不要检索、要回答哪些问题」，执行检索的是 `modules/knowledge/question_retrieval.py`。

代码会校验主题枚举、问题数量、病种、来源类型与事实 ID；以下情况按格式错误处理，退回按病种覆盖诊断、判读、随访的保守计划，并把 `status="fallback"` 与原因记入校验记录：

- 响应不是合法 JSON，或 `need_retrieval` 与 `questions` 不一致；
- 多病种病例未给每个问题指定病种；
- 有影像模型输出却声明「不需要检索」——模型分数不能只靠病例事实解释。

`case_fact_ids` 里自造的 ID 会被丢弃，不当作有效触发依据。病例文本与检索材料都按数据处理，提示词明确禁止其中的文字改变系统规则。

## 统一报告提示词

`prompts/report.py` 的 `REPORT_PROMPT_VERSION` 会写入 `verification.report_prompt_version`。初稿、综合与修订共用同一套要求：五段结构（初步评估、关键依据、诊断评估与待补信息、下一步建议、局限与核验状态）与十二条约束（区分既往诊断/模型提示/初步评估、左右眼分开、每条解释与建议必须有适用证据、不编造数值、不把未提供写成未检查等）。修改要求时递增版本，否则历史报告无法说明依据的是哪一版。

## 确定性检查

`tools/applicability.py` 在模型核查之外做可复核的检查，命中项按核心问题处理：

- `fabricated_value`：正文带计量单位的数值在病例输入与检索资料里都不存在；
- `lateral_mismatch`：句子限定某一眼，数值却只出现在另一眼的病例事实里；
- `not_applicable`：引用编号指向与本次分析病种无关的条款。

未知引用编号始终拦截；核查、修订、拒答与可标注交付状态沿现有流程留痕，返回字段以 `contracts.VerificationRecord` 为准。v2 流程另写 `retrieval`、`case_facts`、`knowledge_gaps`、`applicability` 等可追溯字段。本模块不等于临床验证。

[后端说明](../../README.md) · [离线测试](../../tests/README.md)
