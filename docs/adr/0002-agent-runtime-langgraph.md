# ADR-0002: 模型调用收敛到 LangChain、核查控制流改用 LangGraph

## 状态

已实施。现行结构以 [ARCHITECTURE.md](../ARCHITECTURE.md) 与各模块 README 为准。

## 背景

迁移前三个问题叠在一起：

1. **核查链路难读**：`verifier.verify_and_rewrite` 是 220 行的 `for`/`if` 嵌套，
   首轮核查、来源仲裁、有限轮重写、整篇重生成、局部清理、标注交付六个阶段
   靠早退串起来。改动任何一处都要通读全文，分支覆盖只能靠测试兜。
2. **调用参数分散**：`system` / `temperature` / `max_tokens` / 思考开关散落在
   specialist、director、verifier、chat 四处，每个新调用点都要重新记住一遍。
3. **故障语义不清**：模型不可用时 `chat_with_gpt` 返回 `"Error: ..."` 字符串，
   专科收到后抛 `RuntimeError`，最后被报告队列的兜底吞成「报告生成失败，请联系
   管理员核查任务」——用户拿不到可操作的原因。

## 决策

1. **模型调用统一走 `core/llm/gateway.py`**：`build_chat_model` 产出未绑定参数的
   LangChain `ChatOpenAI`，`to_messages` / `normalize_text` 负责消息与响应形态转换。
   全链路只保留 `LLMClient._invoke` 一条调用路径，测试注入点固定为 `_build_client`。
2. **新增 `LLMClient.complete()`**：失败抛 `LLMUnavailable`（消息已经是
   `describe_llm_error` 的可读文案）。`chat_with_gpt` 保留 `"Error: ..."` 兼容壳，
   因为问答链路依赖它降级；报告链路改用 `complete()`，把故障翻成
   `ApplicationError(503, "模型服务不可用：…")`。
3. **核查控制流改用 LangGraph**（`modules/agent/graphs/verify.py`）：节点为
   `start / rewrite / regenerate / cleanup / deliver / annotate`，路由函数只读状态。
   `CitationVerifier.execute` 签名与返回契约不变，`verify` / `rewrite` 仍是普通方法。
4. **删除专科的工具循环**：证据全文本来就整块拼进提示词，模型再 `search`/`read`
   只是在同一批文本里重读一遍。保留 `max_tool_steps` 式的三步循环，等于每个病种
   白花 1–3 次模型调用。
5. **确定性工具不进链**：`grounding` / `annotation` / `text_revision` /
   `verification_audit` 保持纯函数。它们要在失败时给出可复现的判定依据，包进
   Runnable 只会让审计变难。
6. **并行改用 `RunnableParallel`**：取代手写 `ThreadPoolExecutor`，返回顺序与传入
   顺序一致，异常照旧向上抛。

## 理由

**为什么核查用图、其余用链。** 只有核查是有循环、有条件分支、有多个终态的流程，
图的"节点 + 路由"正好对应"改写到哪一步、下一步做什么"。专科成稿、Director 综合、
并行分发都是一条直线，图只会多一层间接。

**为什么提示词仍是字符串。** 这些提示词长、含大量 JSON 示例与中文约束，且现有
测试是按“渲染后文本”断言的。套 `ChatPromptTemplate` 需要转义大括号、再写一层
快照测试，收益只是形式统一。ADR 选择让 prompt 留在 `prompts/*.py` 的纯函数里，
用针对性测试检查关键约束句，而不是引入转义层。

**为什么 `complete()` 不像 `chat_with_gpt` 那样吞异常。** 报告是"要么交付、要么
说清为什么不能交付"的产品。把模型故障转成字符串再抛 `RuntimeError`，等于把用户
可修复的问题伪装成系统故障。

**为什么用显式计数器而不是 `recursion_limit`。** `recursion_limit` 是保险丝，触发
时表现为框架异常，无法表达"轮数用尽仍有余留，应进入标注或拒答"。轮数必须由
`round` 字段控制，图上界只用来兜底死循环。

## 后果

- **正面**：核查六阶段各自可单独测试；`test_verifier.py` 原有用例不改一行即为
  等价性证明；新增 `test_verify_graph.py` 锁定轮数上界与重生成次数。
- **正面**：模型故障在页面上显示为「模型服务不可用：鉴权失败…」，不再要求用户
  “联系管理员”。
- **正面**：专科成稿从最多 4 次调用降到 1 次，报告耗时与失败面同步收窄。
- **负面**：新增 `langgraph` 依赖（`requirements.txt` 已固定版本），调试时要先看
  图节点再读方法。
- **负面**：`chat_with_gpt` 与 `complete()` 两套错误语义并存。这是刻意的过渡：
  问答链路先保持"降级成提示语"，等前端能展示 502 后再统一。
- **负面**：删除工具循环后，模型失去"按需回读证据"的能力。判定依据是证据本已
  全量入提示词；若将来改为按需注入（证据太多时），需要重新引入受控检索，
  而不是恢复自由工具循环。

## 验收

- `backend/tests/test_agent_contract.py`：核查返回键集合固定，迁移不得增删字段。
- `backend/tests/test_verify_graph.py`：轮数 = `max_rounds`、重生成最多一次、
  核查故障必落 `error`。
- `backend/tests/test_llm_gateway.py`：`complete()` 抛可读的 `LLMUnavailable`，
  报告链路把它翻成 503 且不出现兜底文案。
- `backend/tests/test_verifier.py`、`test_report.py`、`test_review_regressions.py`：
  分支语义与迁移前一致。

## 相关文件

- `backend/core/llm/gateway.py` — 模型构造、消息映射、错误翻译
- `backend/core/llm/client.py` — `_invoke` 唯一出口、`complete()`、兼容壳
- `backend/modules/agent/graphs/verify.py` — 核查状态机
- `backend/modules/agent/verifier.py` — 单次核查与定点重写
- `backend/modules/agent/specialist.py` / `director.py` / `parallel.py` — 提示词与并行
- `backend/modules/report/service.py` — 故障到 HTTP 语义的映射
