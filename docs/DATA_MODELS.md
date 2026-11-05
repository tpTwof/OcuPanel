# 数据对象归属规范

统一采用业务模块内 models.py，不使用 backend/models/ 集中存放，也不同时使用 types.py、schemas/ 等同义结构。

| 位置 | 职责 |
|---|---|
| user/models.py | 用户身份、注册和登录请求、保存用户 LLM 配置的请求 |
| chat/models.py | 创建会话、发送消息、重命名请求 |
| report/models.py | 报告提交、生成结果、文件交付、展示标签 |
| vision/models.py | 影像分析与各病种结果 |
| agents/models.py | 专科角色定义 |
| knowledge/models.py | 知识片段与检索函数契约 |
| llm/models.py | LLM 调用接口与运行配置 |

归属依据是“谁定义并维护语义”，不是“谁恰好使用”。例如报告和 Agents 使用 EyeAnalysis，仍从 vision.models 导入；Agents 使用 LLMCall，仍从 llm.models 导入。用户配置请求属于用户模块，实际 LLMConfiguration 属于 LLM 模块。

Pydantic 模型负责 JSON 请求校验，dataclass 保存进程内数据，TypedDict 标注字典结构，NamedTuple 为报告多字段结果提供名称。Agent、检索器和生成器等实现类留在各自功能文件，不迁入 models.py。

配置实例同样就近维护：agents/roles.py、report/settings.py。基础设施 utils/ 不集中收纳业务模型。只有确实存在多个模块共同定义、无法合理归属于单一模块的契约时，才考虑单独共享模块，目前没有引入。

函数声明超过可读长度时，参数逐行书写、保留尾逗号；复杂表达式按步骤展开，避免用紧凑的一行替代清晰实现。
