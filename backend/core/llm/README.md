# LLM 客户端

client.py 提供模型调用、超时、重试及错误描述，models.py 定义调用契约。配置由 core/config.py 读取。

在 backend 目录执行 `python -m core.llm.check` 可测试真实模型连通性；此操作使用实际配置且可能产生 API 费用。业务请求使用当前账号的模型配置。
