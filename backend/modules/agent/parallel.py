"""执行独立 Agent；每个任务只有请求内上下文。

用 LangChain 的 `RunnableParallel` 取代手写的 ThreadPoolExecutor：
同一份输入分发到各专科，返回顺序与传入顺序一致，异常直接向上抛（和
`pool.map` 语义相同），省掉一层胶水。
"""
from functools import partial
from typing import Any, Sequence

from langchain_core.runnables import RunnableLambda, RunnableParallel

from modules.agent.specialist import SpecialistAgent


def _run_specialist(payload: dict[str, Any], agent: SpecialistAgent) -> str:
    return agent.execute(
        payload["contexts"][agent.name],
        payload["evidence"][agent.name],
        payload["numbers"],
    )


class ParallelOrchestrator:
    def run(
        self,
        agents: Sequence[SpecialistAgent],
        contexts: dict[str, str],
        evidence_by_role: dict[str, list[dict[str, Any]]],
        numbers: dict[str, int],
    ) -> dict[str, str]:
        if not agents or len({a.name for a in agents}) != len(agents):
            raise ValueError("Agent names must be nonempty and unique")

        chain = RunnableParallel({
            agent.name: RunnableLambda(partial(_run_specialist, agent=agent))
            for agent in agents
        })
        return chain.invoke({
            "contexts": contexts,
            "evidence": evidence_by_role,
            "numbers": numbers,
        })
