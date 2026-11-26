# report

router.py 绑定 multipart、任务查询和存档导出；service.py 负责业务与资源生命周期，queue.py 消费持久任务，generation.py 编排影像、证据和 Agent。models.py 保存内部提交对象与结果契约，assets.py 管理原图，pdf.py 生成 PDF。

保持证据编号、verification、拒答和原图来源可追溯。失败的生成或校验不能作为有效报告交付。数据库和归档目录由 core 管理，路径不随模块深度变化。

[后端说明](../../README.md) · [离线测试](../../tests/README.md)
