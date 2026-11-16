# 后端回归测试

安装 [后端依赖](../../README.md#安装指南) 后，从仓库根目录运行。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests
```

测试覆盖 API、会话模式与上下文、报告流程、Agent 工具、引用校验及视觉数值逻辑，使用模拟模型调用。真实模型与产出验证见 [影像分析](../vision/README.md)，运行中实例的账号隔离自检见 [开发工具](../../tools/README.md)。
