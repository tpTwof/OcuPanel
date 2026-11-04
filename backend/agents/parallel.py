"""ParallelOrchestrator —— 封装现有六角色并发逻辑。

行为与改造前完全等价：六个专科角色互不依赖，ThreadPoolExecutor 并发调用，
耗时约等于最慢的那一次。这是 MULTI_AGENT_MODE=parallel 的实现。
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable


class ParallelOrchestrator:
    """并行编排器：所有角色同时执行，无消息传递。

    这是对 report_generator.generate_reports() 中原有并发逻辑的等价抽取。
    """

    def run(
        self,
        roles: list[str],
        prompts: dict[str, str],
        llm_call: Callable[[str], str],
    ) -> dict[str, str]:
        """并发执行所有角色的提示词，返回 {role: response}。

        Args:
            roles: 角色名列表
            prompts: 每个角色的完整提示词
            llm_call: LLM 调用函数，签名 (prompt) -> str
                      对应 MedicalReportGenerator.chat_with_gpt(prompt, reset=True)

        Returns:
            {role_name: llm_response} 字典
        """
        print(f"[AGENT] ParallelOrchestrator: {len(roles)} roles concurrent\n", file=sys.stderr)

        if len(roles) == 1:
            only = roles[0]
            return {only: llm_call(prompts[only])}

        with ThreadPoolExecutor(max_workers=len(roles)) as pool:
            results = pool.map(
                lambda r: (r, llm_call(prompts[r])),
                roles,
            )
            return dict(results)
