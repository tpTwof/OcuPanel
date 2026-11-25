# 报告生成与 PDF

新增的[逐眼演练模块](../screening/README.md)复用本模块 PDF 渲染器输出标记为合成的人工记录，不宣称临床签发；与这里的研究模型报告、存档和导出门槛相互独立。既有 multipart 字段及正文返回字段兼容，新增采集信息均为选填。

## 病例导入的来源与原图

上传可附加 `laterality=right/left`、带时区的 `captured_at`、`device`、`synthetic`。省略时保留未知，不从文件名、模型输出或报告生成时间推断眼别和采集时间。原图字节在归档时写入 `backend/original_store/{随机ID}.bin`，SHA-256、原文件名、临床记录、所选病种及采集信息保存在 reports.source_metadata。报告及会话事务失败时清理本次原图和叠加图。历史记录自动迁移为空元数据，不伪造旧原图。

`GET /api/reports?limit=100` 返回当前账号最近的存档目录，`GET /api/reports/{id}` 返回结构化详情、来源缺项和当前原图完整性状态，`GET /api/reports/{id}/original` 返回原始字节。三个接口均按账号隔离、no-store；原图以 attachment/octet-stream 交付，读取前校验随机 ID 和哈希，不暴露磁盘路径。叠加图继续使用原有图片接口，不能代替原图。

新归档原图长期保留，备份须增加 original_store；当前无自动原图清理器。真实数据的用途、留存和准入仍由机构另行确认。导入不再次推理、不调用 LLM；研究指标、正文及引用状态作为独立来源快照进入草稿，原报告不改写。[实现与验收](../../docs/病例工作台导入实现与二次验收.md)

在浏览器中使用示例眼底照和临床记录可体验端到端流程。 [示例数据](../../samples/README.md)

正文从“初步评估结论”开始，随后给关键依据、下一步及简短局限。原始模型数值继续在正文上方的“影像模型结果”单独展示，PDF 同样保留结构化指标。正文负责解释这些结果与病例记录的关系，并区分逐眼所见、已完成检查与可考虑补充的信息；不把所有内容写成通用免责声明或重复检查清单。

入口为 generation.MedicalReportGenerator.generate(image, note, job_dir, diseases=...)。支持图片路径或上传的二进制文件流。

- generation.py 保存上传文件、调用 vision，按病种检索并统一分配证据编号，然后从撰稿结果组装 ReportResult。
- drafting.py 在当前请求内按证据和病种数量选择撰稿路径。开启校验且完全缺少证据时直接拒答。单病种由专科成稿，多病种由专科并行分析后交给 Director 综合。两条成稿路径均进入校验节点。Verifier 如需重新生成，单病种由原专科重写，多病种由 Director 复用本轮专科意见重写。
- context.py：把各病种视觉结果和共同备注转成病例上下文，并为页面和 PDF 从结构化结果生成影像指标区。
- pdf.py：PDF 输出；settings.py 存放输出标签和字体配置。
- utils/jobs.py：请求独占目录及清理；utils/messages.py：拒答原因展示。

Agents 位于 ../agents，统一模型请求位于 ../llm，证据检索位于 ../knowledge。api.py 只绑定 HTTP 输入与响应，service.py 负责业务校验、记录存储与任务文件生命周期，generation.py 负责完整分析生成。

逐病种检索会传入 `knowledge/report_focus.py` 的病种侧重点与病种归属，并按报告必须回答的四个方面（诊断、判读、治疗处置、随访）分别检索后按轮次合并，见[知识检索](../knowledge/README.md)。这么做的原因是：只发一条长查询时，病例里反复出现的「眼压、视野、RNFL」会盖过主题词，诊断类条款占满结果，判读与随访条款排到十名之外，撰稿写这些内容时无据可引，校验只能判为不受支持。侧重点与分组只影响召回，不能替代来源适用性核查。

校验开启且所有病种都未取得证据时，返回拒答与已算出的影像指标，跳过专科撰稿和综合。校验响应格式错误或调用失败均不交付正文；VERIFY_ENABLED=False 时不执行 LLM 核查；未知编号仍确定性拒答，其余情况标记 disabled。专科调用失败中止任务，不能将错误字符串当作报告。Director 每次独立调用，不复用其他报告的聊天状态。

`verify_call_failed` / `recheck_call_failed` 表示校验过程出错，不表示缺少引用。新校验记录通过 `failure_kind` 区分 `empty_response`（空响应）、`llm_error`（模型请求失败）、`invalid_json`（非有效 JSON）和 `invalid_claims`（问题条目结构不符）；不把模型原始响应或服务商错误详情写入报告。页面提示检查个人 LLM 配置与后端日志。`no_evidence` 才表示未取得参考资料，`unverified_claims_remain` 表示完成核查后仍有不受支持的表述。

JSON 或 `claims` 结构错误时，保留原文及证据，附字段错误提示重新校验一次；仍不合法则扣留正文，页面显示 `failure_detail` 中的字段路径与要求。`format_retries` 保存累计格式重试次数，不改变正文修订轮数或 PDF 导出门槛。

编号笔误与无据断言分开处理。句子另有有效引用、又多带一个不存在的编号（如 `[1][9]` 而只有 2 条证据）时，只去掉多余编号，记入 `stripped_citations`，不占用修订轮数；整句唯一的引用就是无效编号时不去掉，仍按未知引用阻断，避免把无出处的句子放行。

核查外部引文时按「引文真实存在」而非「必须对应当前编号」判定：grounding 引用的片段若逐字存在于另一条证据，代码改记到实际来源（`excerpt_kind=renumbered`，保留 `reported_index`），语义是否支持仍由校验模型判断。编造的引文仍然阻断。这样编号笔误不再被误判为伪造来源。病例与软件声明本来就不要求逐字复述，代码会关联完整快照（`excerpt_kind=source_snapshot`）。

报告不再因可移除的非核心说明反复改写而直接整篇拒答。普通修订后仅剩此类问题时，会尝试一次精确的局部删除，再核查全文；通过后以 `rewritten` 交付清理后的正文，PDF 从同一存档正文生成，页面保留删除原因。涉及诊断或处置的问题、影响分类缺失、未知引用、不能准确定位或清理后复核失败仍阻断诊疗正文及 PDF。结构化影像指标继续独立保存和展示。

v2 语义核查仍有问题且有输入记录时，`source_summary.py` 提供 `limited` 病例资料摘要：只按原文保留用户记录，明确未独立核验、诊疗结论未交付，不混入失败草稿。`diagnostic_status=rejected`、`rejected=true`，两个 PDF 入口继续阻断；这不是“部分通过”的诊断报告。网络/格式故障、无证据及无输入记录不转换为通过状态。病例记录采用独立文本代码块，原始 Markdown 不参与执行或报告格式拼接。

新报告采用 `policy_version=2`：撰稿区分病例事实、审慎解释和建议；校验及修订都收到原始病例上下文，混合句按分句处理。病例复述、普通下一步及明确的资料边界不强行挂指南，具体处置与医学解释保留证据要求。来源归类争议先有界复核；通过内容须提供 `grounding` 支持片段，代码核对实际来源和每个正文引用位置。来源对照不足转为修订问题，而非将整份报告描述为“缺少病例资料”。流程与审计字段见 [Agents](../agents/README.md#来源与分句校验policy_version2)。

`verification.source_manifest` 包含本轮病例上下文快照，按原报告账号权限保存，不作为新的临床事实来源。`review_log`、`grounding` 与最终正文版本一同存档；前端可展开来源片段和校验过程。通过条目可用本轮 `statement_id` 引用原始正文位置，避免模型回抄改词造成误拒。病例和软件声明可通过固定来源标识关联实际完整快照；外部证据摘录仍核对编号与原文。PDF 仍只导出 `pass` / `rewritten`，引用编号与存档参考资料一致。通过表示本轮来源检查完成，不等于医学金标准验证或医生签发。

影像指标和模型来源单独展示并保存到 SQLite。引用校验覆盖正文中的外部知识陈述。某个病种未命中证据时，在该病种下提示。旧报告沿用保存时的正文与 CDR 字段。报告、与会话关联的一问一答及首次标题在同一数据库事务内归档；归档失败会清理本次写出的叠加图。叠加图按当前账号与报告关联读取。

## HTTP 与数据对象

路由位于 api.py，业务实现位于 service.py。报告表单由 parse_report_submission 依赖转换为 report.models.ReportSubmission，当前用户由 Bearer 令牌解析。生成流程文件名是 generation.py，其返回对象为 ReportResult；旧 workflow.py 已移除。PDF 展示标签使用 report.models.ReportLabels，角色定义使用 agents.models.SpecialistRole，配置实例分别维护于 settings.py 和 agents/roles.py。

专科工具请求支持 JSON 代码块；损坏的结构化请求返回格式错误，不作为报告。最终草稿中的未知引用编号进入 Verifier 的修订/复核/拒答路径；编号是否存在由代码检查，语义支撑由 LLM 核查。

正文接口在提供 conversation_id 时，将临床记录与报告回复保存到该用户的同一会话，形态切为 ophthalmic；未提供时不自动建会话。`POST /api/generate-report/` 接收原始表单并生成 PDF。页面使用 `GET /api/reports/{report_id}/pdf` 导出当前账号的历史报告。两个 PDF 接口均从存档渲染，并标出正文引用的校验结果。只有 pass、rewritten 可导出。disabled 或缺少历史校验状态时仍可查看原会话正文。

重复提交相同病例也会重新推理并调用 LLM；视觉缓存只复用权重，不缓存报告。默认生成温度和服务商行为可能使文字不同，现有验证未证明报告具有临床可重复性。

环境、启动与配置见[项目 README](../../README.md)和[后端说明](../README.md)，当前以 Python 3.13 为开发基线。

## 持久报告任务

报告页 POST `/api/report-jobs`，表单带 `request_key`；成功返回 202 和任务号。使用同账号 GET `/api/report-jobs/{id}` 查询 queued、running、completed 或 failed。相同账号和键提交不同内容返回 409。队列为每个数据库配置一个活动消费者，归档后用任务号恢复结果；归档前进程中断可能重做外部调用。旧同步接口可继续独立使用。参阅[留存与备份操作](../../tools/README.md)。
