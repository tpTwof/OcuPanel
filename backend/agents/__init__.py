"""Multi-Agent 协作框架。

套壳阶段：
- Agent Protocol（最小接口：execute + name + role_description）
- ParallelOrchestrator（封装现有六角色并发逻辑）
- MessageBus 注释占位（collaborative 模式需要时再实现）

MULTI_AGENT_MODE 控制协作模式：
- parallel（默认）：现有行为，六角色并发 + Director 综合
- collaborative：Agent 间消息传递（TODO）
- adaptive：根据初步诊断动态选择角色（TODO）
"""

from .protocol import Agent
from .parallel import ParallelOrchestrator

# MessageBus: collaborative/adaptive 模式的核心组件。
# parallel 模式不需要它，等真正做协作模式时再设计和实现。
# 届时需要确定：同步/异步、消息格式、路由规则、订阅机制。
# MessageBus = Any  # type: ignore[misc]

__all__ = [
    "Agent",
    "ParallelOrchestrator",
]
