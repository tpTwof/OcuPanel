# 账号与个人配置

- `api.py` 暴露 `/api/account/*`，包括注册、登录、注销、个人配置、连通测试和用量统计。
- `service.py` 处理账号业务和 LLM 配置，`models.py` 定义请求与响应。
- 登录后使用 `Authorization: Bearer <token>` 访问业务接口。配置中的 API Key 在服务端加密，读取接口返回掩码。连通测试会请求实际配置的模型服务。

接口清单与数据库路径见 [后端 README](../README.md)，模型调用行为见 [LLM README](../llm/README.md)。

机构成员保存、读取或测试模型配置时使用机构获准端点名单。未配置获准端点时，机构成员仍可演练手工病例流程。[机构配置](../../tools/README.md)
