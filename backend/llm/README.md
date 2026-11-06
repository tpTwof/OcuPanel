# LLM 调用

client.py 负责端点、凭据、模型、超时、重试及错误处理，不存放眼科业务提示词。

chat_with_history(history, user_message, *, system=None) 仅使用调用方传入的可选系统指令，不读写客户端历史。普通聊天传 None，眼科助手由 chat/service.py 传入 chat/prompts.py 的指令。聊天使用 temperature=0.7 与 CHAT_MAX_OUTPUT_TOKENS 上限，失败抛 RuntimeError，由聊天业务映射为 502。

报告生成器为分析流程设置自己的 system_prompt，各分析/校验 Agent 可提供独立指令。chat_with_gpt 保留报告流程的调用接口和可选历史能力。普通聊天不创建报告生成器，不加载 PDF 渲染模块。

chat_with_gpt 调用失败返回 Error: 前缀文本，专科与 Director 必须中止，Verifier 必须不交付正文，不能直接展示为成功报告。报告默认温度为 0.7，引用核查为 0，修订为 0.2，不保证相同输入的报告逐字一致。

从 backend 使用项目虚拟环境运行 `../.venv/Scripts/python.exe -m llm.check` 可进行真实连通自检，需要有效环境配置并可能产生费用。离线单元测试不运行真实调用。环境与依赖见[项目 README](../../README.md)。
