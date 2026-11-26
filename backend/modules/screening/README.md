# screening

router.py 绑定 `/api/screening/*`；service.py 执行复核、模拟签发、转诊和导出，repository.py 保存当前状态、不可变版本和幂等收据。models.py 保存检查与逐眼领域类型，schemas.py 保存创建、操作和导入请求；imports.py 处理分析归档导入，access.py 检查权限，presentation.py 生成版本释义，evaluation.py 做合成评估。

仅支持合成演练。所有病例和来源按账号隔离，导入保留原图哈希、研究结果和引用校验状态；不把缺失原图或未经验证的研究结果补造成有效临床结论。

[后端说明](../../README.md) · [离线测试](../../tests/README.md)
