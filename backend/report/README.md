# 报告流程

入口为 generation.MedicalReportGenerator.generate(image, note, roles, job_dir)。支持图片路径或上传的二进制文件流。

- generation.py：保存上传文件、调用 vision、运行专科 Agent、Director 和 Verifier，返回正文、校验状态、CDR、图片路径和证据。后面三个字段保留现有 HTTP/PDF 输出约定。
- context.py：把 EyeAnalysis 和临床记录转成事实上下文；未评估的严重程度明确标注。
- pdf.py：PDF 输出；settings.py 存放输出标签和字体配置。
- utils/jobs.py：请求独占目录及清理；utils/messages.py：拒答原因展示。

Agents 位于 ../agents，统一模型请求位于 ../llm，证据检索位于 ../knowledge。api.py 只绑定 HTTP 输入与响应，service.py 负责业务校验、记录存储与任务文件生命周期，generation.py 负责完整分析生成。

校验开启时，无证据、校验响应格式错误或调用失败均不交付正文；VERIFY_ENABLED=False 时不执行 LLM 核查；未知编号仍确定性拒答，其余情况标记 disabled。专科调用失败中止任务，不能将错误字符串当作报告。Director 每次独立调用，不复用其他报告的聊天状态。

目前 PDF 和 HTTP 结果仍有青光眼 CDR 与单张叠加图的兼容输出。影像分析和 Agent 病例上下文按病种组织，未来更换展示结构时再调整这些输出字段。

## HTTP 与数据对象

路由位于 api.py，业务实现位于 service.py。报告表单由 parse_report_submission 依赖转换为 report.models.ReportSubmission，当前用户由 Bearer 令牌解析。生成流程文件名是 generation.py，其返回对象为 ReportResult；旧 workflow.py 已移除。PDF 展示标签使用 report.models.ReportLabels，角色定义使用 agents.models.SpecialistRole，配置实例分别维护于 settings.py 和 agents/roles.py。

专科工具请求支持 JSON 代码块；损坏的结构化请求返回格式错误，不作为报告。Director 草稿中的未知引用编号进入 Verifier 的修订/复核/拒答路径；编号是否存在由代码检查，语义支撑由 LLM 核查。

正文接口在提供 conversation_id 时，将临床记录与报告回复保存到该用户的同一会话，形态切为 ophthalmic；未提供时不自动建会话。PDF 接口重新生成并保存报告记录，但不追加正文接口的两条聊天消息。界面只在当前页面还持有原上传文件时展示下载入口。

重复提交相同病例也会重新推理并调用 LLM；视觉缓存只复用权重，不缓存报告。默认生成温度和服务商行为可能使文字不同，现有验证未证明报告具有临床可重复性。

环境、启动与配置见[项目 README](../../README.md)和[后端说明](../README.md)，当前以 Python 3.13 为开发基线。
