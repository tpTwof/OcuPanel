# conversation

管理会话、消息历史、会话模式和图检索偏好。router.py 保留 `/api/chat/conversations` 及详情、模式、图谱接口；service.py 提供账号隔离的管理操作及内部消息访问；repository.py 封装 SQLite。models.py 定义 ChatMode，schemas.py 定义管理请求。新会话默认 general，ophthalmic 启用眼科提示和检索，切换模式保留历史。

[后端说明](../../README.md) · [离线测试](../../tests/README.md)
