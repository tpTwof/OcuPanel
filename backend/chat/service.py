from __future__ import annotations
from typing import Any
from user.models import User
from chat.models import (
    CreateConversationRequest,
    SendMessageRequest,
    RenameConversationRequest,
    ChangeModeRequest,
)

from utils.errors import ApplicationError
from starlette.concurrency import run_in_threadpool

from utils import storage, config
from llm.client import LLMClient
from .prompts import CHAT_SYSTEM_PROMPT
from .context import select_history


async def list_conversations(user: User) -> dict[str, Any]:
    items = await run_in_threadpool(storage.list_conversations, user["id"])
    return {"items": items}


async def create_conversation(
    user: User,
    body: CreateConversationRequest,
) -> dict[str, Any]:
    return await run_in_threadpool(storage.create_conversation, user["id"], body.title or "新对话", body.mode)


async def conversation_detail(user: User, conversation_id: str) -> dict[str, Any]:
    conv = await run_in_threadpool(storage.get_conversation, user["id"], conversation_id)
    if not conv:
        # 别人的会话与不存在的会话返回同一个 404，不泄露"这条 id 存在"
        raise ApplicationError(status_code=404, detail="会话不存在")
    msgs = await run_in_threadpool(storage.list_messages, user["id"], conversation_id)
    return {"conversation": conv, "messages": msgs}


async def rename_conversation(
    user: User,
    conversation_id: str,
    body: RenameConversationRequest,
) -> dict[str, Any]:
    conv = await run_in_threadpool(storage.get_conversation, user["id"], conversation_id)
    if not conv:
        raise ApplicationError(status_code=404, detail="会话不存在")
    await run_in_threadpool(storage.rename_conversation, user["id"], conversation_id, body.title)
    return {"ok": True}


async def delete_conversation(user: User, conversation_id: str) -> dict[str, Any]:
    deleted = await run_in_threadpool(
        storage.delete_conversation, user["id"], conversation_id
    )
    # 与 GET / PATCH 保持一致：别人的会话和不存在的会话都是同一个 404。
    # 不能因为"删除是幂等的"就一律回 200——那样越权尝试会伪装成成功。
    if not deleted:
        raise ApplicationError(status_code=404, detail="会话不存在")
    return {"ok": True}


async def send_message(
    user: User,
    conversation_id: str,
    body: SendMessageRequest,
) -> dict[str, Any]:
    """发一条消息并拿到回复。对话历史从 SQLite 读，不再依赖进程内列表。

    这样重启服务、换台机器登录，上下文都还在——这是引入数据库最直接的收益。
    """
    conv = await run_in_threadpool(storage.get_conversation, user["id"], conversation_id)
    if not conv:
        raise ApplicationError(status_code=404, detail="会话不存在")

    text = (body.message or "").strip()
    if not text:
        raise ApplicationError(status_code=400, detail="消息不能为空")

    cfg = await run_in_threadpool(storage.load_llm_config, user["id"])
    if not cfg:
        raise ApplicationError(status_code=409, detail="尚未配置 LLM API，请先在「个人设置」中填写")

    history = await run_in_threadpool(storage.list_messages, user["id"], conversation_id)
    client = LLMClient(
        api_key=cfg["api_key"], model=cfg["model"], base_url=cfg["base_url"] or None,
    )
    system = CHAT_SYSTEM_PROMPT["content"] if conv.get("mode") == "ophthalmic" else None

    try:
        context = select_history(
            history, text, system=system, mode=conv.get("mode", "general"),
            max_messages=config.CHAT_HISTORY_MAX_MESSAGES,
            max_chars=config.CHAT_CONTEXT_MAX_CHARS,
            report_max_chars=config.CHAT_REPORT_MAX_CHARS,
        )
    except ValueError as exc:
        raise ApplicationError(status_code=413, detail=str(exc)) from exc
    await run_in_threadpool(storage.add_message, user["id"], conversation_id, "user", text, None)

    def _run() -> str:
        return client.chat_with_history(
            context,
            text,
            system=system,
        )

    try:
        reply = await run_in_threadpool(_run)
    except Exception as exc:  # noqa: BLE001
        from llm.client import describe_llm_error

        raise ApplicationError(status_code=502, detail=describe_llm_error(exc)) from exc

    saved = await run_in_threadpool(
        storage.add_message, user["id"], conversation_id, "assistant", reply, None
    )

    # 首条消息用来给会话起名，避免侧边栏一水儿的「新对话」
    if conv["title"] in ("新对话", "", None):
        title = text[:20] + ("…" if len(text) > 20 else "")
        await run_in_threadpool(storage.rename_conversation, user["id"], conversation_id, title)

    return {"reply": reply, "message_id": saved["id"]}


async def change_mode(
    user: User, conversation_id: str, body: ChangeModeRequest,
) -> dict[str, str]:
    changed = await run_in_threadpool(
        storage.set_conversation_mode, user["id"], conversation_id, body.mode,
    )
    if not changed:
        raise ApplicationError(status_code=404, detail="会话不存在")
    return {"mode": body.mode}
