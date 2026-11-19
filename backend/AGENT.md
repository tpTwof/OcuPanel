# 后端约定

后端模块职责和 API 见 [README.md](README.md)，代码边界见 [架构说明](../docs/ARCHITECTURE.md)。

- HTTP 绑定与响应放在各模块 `api.py`，业务与资源生命周期放在 `service.py`，数据契约放在所属模块 `models.py`；跨模块复用拥有方的定义。
- 保持现有认证、账号隔离、multipart 字段和响应字段兼容。预期业务错误使用 `ApplicationError`，由 `main.py` 统一映射。
- 修改报告流程时同时检查证据编号、Verifier 结果和拒答路径；失败的生成或校验不能作为有效报告交付。
- 用相关离线测试验证改动；完整回归命令见 [tests/README.md](tests/README.md)。真实 LLM 或模型下载只在任务需要时运行。
