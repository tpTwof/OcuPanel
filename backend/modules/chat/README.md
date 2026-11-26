# chat

router.py 绑定 `/api/chat/conversations/{conversation_id}/messages`；service.py 调用 conversation 服务读取和保存消息，调用 user 服务读取模型配置，执行模型生成及眼科问答引用校验。schemas.py 定义消息请求，context.py 选择上下文窗口，prompts.py 管理眼科提示。

数据库保留完整历史；发送给模型的上下文受 CHAT_HISTORY_MAX_MESSAGES、CHAT_CONTEXT_MAX_CHARS 和 CHAT_REPORT_MAX_CHARS 限制，眼科模式优先保留最近报告。字符预算不是精确 token 数，超出窗口的历史不会发送给模型。

[后端说明](../../README.md) · [离线测试](../../tests/README.md)
