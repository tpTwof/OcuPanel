# 数据对象归属规范

统一采用业务模块内 models.py，不使用 backend/models/ 集中存放，也不同时使用 types.py、schemas/ 等同义结构。

| 位置 | 职责 |
|---|---|
| user/models.py | 用户身份、注册和登录请求、保存用户 LLM 配置的请求 |
| chat/models.py | ChatMode、创建会话、发送消息、重命名及切换形态请求 |
| report/models.py | 报告提交、生成结果、文件交付、展示标签 |
| vision/models.py | 影像分析与各病种结果 |
| agents/models.py | 专科角色定义 |
| knowledge/models.py | 知识片段与检索函数契约 |
| llm/models.py | LLM 调用接口与运行配置 |

归属依据是“谁定义并维护语义”，不是“谁恰好使用”。例如报告和 Agents 使用 EyeAnalysis，仍从 vision.models 导入；Agents 使用 LLMCall，仍从 llm.models 导入。用户配置请求属于用户模块，实际 LLMConfiguration 属于 LLM 模块。

Pydantic 模型负责 JSON 请求校验，dataclass 保存进程内数据，TypedDict 标注字典结构，NamedTuple 为报告多字段结果提供名称。Agent、检索器和生成器等实现类留在各自功能文件，不迁入 models.py。

配置实例同样就近维护：agents/roles.py、report/settings.py。基础设施 utils/ 不集中收纳业务模型。只有确实存在多个模块共同定义、无法合理归属于单一模块的契约时，才考虑单独共享模块，目前没有引入。

函数声明超过可读长度时，参数逐行书写、保留尾逗号；复杂表达式按步骤展开，避免用紧凑的一行替代清晰实现。

## Python / Pydantic 兼容

本项目当前以 Python 3.13 为开发与验证基线，本机 `.venv` 为 3.13.3。其他 Python 版本未完成全部固定依赖与服务运行验证，不再沿用“Python 3.10+”的宽泛支持声明。环境统一见[项目 README](../README.md#前置要求)。

可能进入 Pydantic/FastAPI schema 生成的数据对象统一从 typing_extensions 导入 TypedDict；Pydantic 2.11 在 Python 3.10/3.11 上会拒绝 typing.TypedDict。typing_extensions 已在 requirements.txt 固定版本；这项兼容措施不代表旧解释器已全面受支持。

回归测试通过触发已安装 Pydantic 的旧解释器检查分支覆盖该问题；这不等于在 Python 3.10/3.11 原生环境完成全部依赖和服务验证。
