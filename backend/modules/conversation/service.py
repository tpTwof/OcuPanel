"""会话管理业务：所有操作按当前用户隔离。"""
from typing import Any
from starlette.concurrency import run_in_threadpool
from core import config
from core.exceptions import ApplicationError
from modules.user.models import User
from modules.conversation import repository as repo
from modules.conversation.schemas import (
    CreateConversationRequest, RenameConversationRequest, ChangeModeRequest, GraphPreference,
)


async def list_conversations(user: User) -> dict[str, Any]:
    items = await run_in_threadpool(repo.list_conversations, user["id"])
    return {"items": items, "rag_enabled": config.RAG_ENABLED, "graph_default": config.GRAPH_RAG_ENABLED}


async def create_conversation(
    user: User,
    body: CreateConversationRequest,
) -> dict[str, Any]:
    return await run_in_threadpool(repo.create_conversation, user["id"], body.title or "新对话", body.mode, body.graph_enabled)


async def conversation_detail(user: User, conversation_id: str) -> dict[str, Any]:
    conv = await run_in_threadpool(repo.get_conversation, user["id"], conversation_id)
    if not conv:
        # 别人的会话与不存在的会话返回同一个 404，不泄露"这条 id 存在"
        raise ApplicationError(status_code=404, detail="会话不存在")
    msgs = await run_in_threadpool(repo.list_messages, user["id"], conversation_id)
    return {"conversation": conv, "messages": msgs}


async def rename_conversation(
    user: User,
    conversation_id: str,
    body: RenameConversationRequest,
) -> dict[str, Any]:
    conv = await run_in_threadpool(repo.get_conversation, user["id"], conversation_id)
    if not conv:
        raise ApplicationError(status_code=404, detail="会话不存在")
    await run_in_threadpool(repo.rename_conversation, user["id"], conversation_id, body.title)
    return {"ok": True}


async def delete_conversation(user: User, conversation_id: str) -> dict[str, Any]:
    deleted = await run_in_threadpool(
        repo.delete_conversation, user["id"], conversation_id
    )
    # 与 GET / PATCH 保持一致：别人的会话和不存在的会话都是同一个 404。
    # 不能因为"删除是幂等的"就一律回 200——那样越权尝试会伪装成成功。
    if not deleted:
        raise ApplicationError(status_code=404, detail="会话不存在")
    return {"ok": True}


async def change_graph(user: User, conversation_id: str, body: GraphPreference) -> dict[str, bool]:
    changed = await run_in_threadpool(repo.set_graph_enabled, user["id"], conversation_id, body.graph_enabled)
    if not changed:
        raise ApplicationError(status_code=404, detail="会话不存在")
    return {"graph_enabled": body.graph_enabled}


async def change_mode(
    user: User, conversation_id: str, body: ChangeModeRequest,
) -> dict[str, str]:
    changed = await run_in_threadpool(
        repo.set_conversation_mode, user["id"], conversation_id, body.mode,
    )
    if not changed:
        raise ApplicationError(status_code=404, detail="会话不存在")
    return {"mode": body.mode}


def get_conversation(user_id: str, conversation_id: str) -> dict[str, Any] | None:
    return repo.get_conversation(user_id, conversation_id)


def list_messages(user_id: str, conversation_id: str) -> list[dict[str, Any]]:
    return repo.list_messages(user_id, conversation_id)


def add_message(user_id: str, conversation_id: str, role: str, content: str,
                meta: dict[str, Any] | None) -> dict[str, Any]:
    return repo.add_message(user_id, conversation_id, role, content, meta)


def rename_title(user_id: str, conversation_id: str, title: str) -> bool:
    return repo.rename_conversation(user_id, conversation_id, title)
