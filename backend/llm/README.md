# LLM 调用

client.py 负责端点、凭据、模型、超时、重试及错误处理，不存放眼科业务提示词。

chat_with_history(history, user_message, system=None) 仅使用调用方传入的可选系统指令，不读写客户端历史。普通聊天传 None，眼科助手由 chat/service.py 传入 chat/prompts.py 的指令。

报告生成器为分析流程设置自己的 system_prompt，各分析/校验 Agent 可提供独立指令。chat_with_gpt 保留报告流程的调用接口和可选历史能力。普通聊天不创建报告生成器，不加载 PDF 渲染模块。
