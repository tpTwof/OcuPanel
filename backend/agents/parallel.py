"""执行独立 Agent;每个任务只有请求内上下文。"""
from typing import Any, Sequence
from .specialist import SpecialistAgent
from concurrent.futures import ThreadPoolExecutor

class ParallelOrchestrator:
    def run(
        self,
        agents: Sequence[SpecialistAgent],
        context: str,
        evidence: dict[str, list[dict[str, Any]]],
        numbers: dict[str, int],
    ) -> dict[str, str]:
        if not agents or len({a.name for a in agents}) != len(agents):
            raise ValueError("Agent names must be nonempty and unique")

        def execute(agent: SpecialistAgent) -> tuple[str, str]:
            return agent.name, agent.execute(context, evidence.get(agent.name, []), numbers)
        with ThreadPoolExecutor(max_workers=len(agents)) as pool:
            return dict(pool.map(execute, agents))
