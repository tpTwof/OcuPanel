# agent

specialist.py、director.py、verifier.py 分别执行专科分析、多病种综合和引用核查；parallel.py 编排专科，roles.py 定义角色，models.py 保存数据契约，prompts/ 与 tools/ 管理指令和受限工具。通过报告或问答调用，不单独暴露 HTTP 接口。

未知证据编号始终拦截；核查、修订、拒答与可标注交付状态沿现有流程留痕。本模块不等于临床验证。

[后端说明](../../README.md) · [离线测试](../../tests/README.md)
