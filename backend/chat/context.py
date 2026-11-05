"""选择聊天输入窗口，不修改数据库记录，不调用 LLM 生成摘要。"""
from typing import Any
from .models import ChatMode


def select_history(
    history: list[dict[str, Any]],
    current_message: str,
    *,
    system: str | None,
    mode: ChatMode,
    max_messages: int,
    max_chars: int,
    report_max_chars: int,
) -> list[dict[str, str]]:
    """预算包含系统提示词、当前问题和历史正文；字符数不是精确 token 数。"""
    if min(max_messages, max_chars, report_max_chars) <= 0:
        raise ValueError("Context limits must be positive")
    remaining = max_chars - len(current_message) - len(system or "")
    if remaining < 0:
        raise ValueError("当前消息过长，请缩短内容或分段发送")
    valid = [
        (index, item) for index, item in enumerate(history)
        if item.get("role") in ("user", "assistant")
        and isinstance(item.get("content"), str) and item["content"]
    ]
    selected: dict[int, dict[str, str]] = {}
    report_index = None
    if mode == "ophthalmic":
        for index, item in reversed(valid):
            meta = item.get("meta")
            if isinstance(meta, dict) and meta.get("kind") == "report":
                report_index = index
                content = item["content"]
                # 至多一半剩余预算用于报告，保证最近对话还有可用空间。
                budget = min(report_max_chars, remaining // 2)
                marker = "\n[报告节选：其余内容未提供，不得推测缺失结论。]"
                if len(content) > budget:
                    if budget <= len(marker):
                        raise ValueError("当前消息过长，无法保留必要的报告上下文，请缩短后重试")
                    content = content[:budget - len(marker)] + marker
                if content:
                    selected[index] = {"role": "assistant", "content": content}
                    remaining -= len(content)
                break
    for index, item in reversed(valid):
        if index == report_index:
            continue
        meta = item.get("meta")
        if mode == "ophthalmic" and isinstance(meta, dict) and meta.get("kind") == "report":
            continue
        if len(selected) >= max_messages:
            break
        content = item["content"]
        if len(content) > remaining:
            # 只选择连续的近期窗口，不截断普通消息，也不跳回更早的短消息。
            break
        selected[index] = {"role": item["role"], "content": content}
        remaining -= len(content)
    result = [selected[index] for index in sorted(selected)]
    # 不以没有问题上下文的孤立回复作为普通窗口起点；固定保留的报告除外。
    while result and result[0]["role"] == "assistant":
        first = min(selected)
        if first == report_index:
            break
        selected.pop(first)
        result = [selected[index] for index in sorted(selected)]
    return result
