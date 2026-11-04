"""Agent 协议 —— Multi-Agent 框架的最小接口。

套壳阶段只定义 execute() + name + role_description。
plan() 作为可选扩展，collaborative 模式需要时再加入 Protocol。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Agent(Protocol):
    """多智能体框架中的 Agent 最小接口。

    Attributes:
        name: Agent 标识符（如 "Ophthalmologist", "Pharmacist"）
        role_description: 角色描述，用于 Orchestrator 分配任务

    Methods:
        execute: 执行给定任务，返回结果
    """

    name: str
    role_description: str

    def execute(self, task: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """执行任务。

        Args:
            task: 任务描述，至少包含 {"prompt": str}
            context: 共享上下文（证据包、影像分析结果等）

        Returns:
            执行结果，至少包含 {"output": str}
        """
        ...
