"""连通性探测：用给定配置发一次最小请求。

放在 account 模块里是因为它只服务于「个人设置」页面的「测试连通」按钮，
不属于报告生成链路；避免为此在 llm 层再引入一个业务依赖。
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from core import config


def probe_llm(api_key: str, base_url: str | None, model: str) -> dict:
    """返回连接结果与用量，异常由调用方转换成用户可读的提示。"""
    client = ChatOpenAI(
        api_key=api_key,
        base_url=base_url or None,
        model=model,
        timeout=config.LLM_TIMEOUT,
        max_retries=0,
    )
    result = client.invoke(
        [HumanMessage(content="只回复两个字：收到")],
        temperature=0,
        # 8 个 token 会被推理型模型全部花在思考上，content 返回空串，
        # 看起来像「连通了但没说话」。给 64 留足余量。
        max_tokens=64,
    )
    reply = (getattr(result, "content", "") or "").strip()
    usage = getattr(result, "usage_metadata", None) or {}
    return {
        "ok": True,
        # 空内容也算连通（模型可能把额度花在 reasoning 上），前端据此提示
        "reply": reply[:40] or "（空响应，但连接与鉴权正常）",
        "prompt_tokens": usage.get("input_tokens"),
        "completion_tokens": usage.get("output_tokens"),
    }