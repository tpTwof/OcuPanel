# 报告生成与 PDF

在浏览器中使用示例眼底照和临床记录可体验端到端流程。 [示例数据](../../samples/README.md)

入口为 generation.MedicalReportGenerator.generate(image, note, job_dir, diseases=...)。支持图片路径或上传的二进制文件流。

- generation.py：保存上传文件、调用 vision、按病种检索和运行专科，单病种草稿直接进入 Verifier，多病种先经过 Director。返回正文、校验状态、CDR、图片路径、证据和结构化视觉结果。
- context.py：把各病种视觉结果和共同备注转成病例上下文，并为页面和 PDF 从结构化结果生成影像指标区。
- pdf.py：PDF 输出；settings.py 存放输出标签和字体配置。
- utils/jobs.py：请求独占目录及清理；utils/messages.py：拒答原因展示。

Agents 位于 ../agents，统一模型请求位于 ../llm，证据检索位于 ../knowledge。api.py 只绑定 HTTP 输入与响应，service.py 负责业务校验、记录存储与任务文件生命周期，generation.py 负责完整分析生成。

校验开启且所有病种都未取得证据时，返回拒答与已算出的影像指标，跳过专科撰稿和综合。校验响应格式错误或调用失败均不交付正文；VERIFY_ENABLED=False 时不执行 LLM 核查；未知编号仍确定性拒答，其余情况标记 disabled。专科调用失败中止任务，不能将错误字符串当作报告。Director 每次独立调用，不复用其他报告的聊天状态。

影像指标和模型来源单独展示并保存到 SQLite。引用校验覆盖正文中的外部知识陈述。某个病种未命中证据时，在该病种下提示。旧报告沿用保存时的正文与 CDR 字段。报告、与会话关联的一问一答及首次标题在同一数据库事务内归档；归档失败会清理本次写出的叠加图。叠加图按当前账号与报告关联读取。

## HTTP 与数据对象

路由位于 api.py，业务实现位于 service.py。报告表单由 parse_report_submission 依赖转换为 report.models.ReportSubmission，当前用户由 Bearer 令牌解析。生成流程文件名是 generation.py，其返回对象为 ReportResult；旧 workflow.py 已移除。PDF 展示标签使用 report.models.ReportLabels，角色定义使用 agents.models.SpecialistRole，配置实例分别维护于 settings.py 和 agents/roles.py。

专科工具请求支持 JSON 代码块；损坏的结构化请求返回格式错误，不作为报告。最终草稿中的未知引用编号进入 Verifier 的修订/复核/拒答路径；编号是否存在由代码检查，语义支撑由 LLM 核查。

正文接口在提供 conversation_id 时，将临床记录与报告回复保存到该用户的同一会话，形态切为 ophthalmic；未提供时不自动建会话。`POST /api/generate-report/` 接收原始表单并生成 PDF。页面使用 `GET /api/reports/{report_id}/pdf` 导出当前账号的历史报告。两个 PDF 接口均从存档渲染，并标出正文引用的校验结果。只有 pass、rewritten 可导出。disabled 或缺少历史校验状态时仍可查看原会话正文。

重复提交相同病例也会重新推理并调用 LLM；视觉缓存只复用权重，不缓存报告。默认生成温度和服务商行为可能使文字不同，现有验证未证明报告具有临床可重复性。

环境、启动与配置见[项目 README](../../README.md)和[后端说明](../README.md)，当前以 Python 3.13 为开发基线。
