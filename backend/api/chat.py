from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

import auth
import storage
from report_generator import build_generator_for_user

chat_router = APIRouter()


class NewConversationBody(BaseModel):
    title: str = "新对话"


class SendMessageBody(BaseModel):
    message: str


class RenameBody(BaseModel):
    title: str


@chat_router.get("/chat/conversations")
async def list_conversations(user: auth.CurrentUser):
    items = await run_in_threadpool(storage.list_conversations, user["id"])
    return {"items": items}


@chat_router.post("/chat/conversations")
async def create_conversation(user: auth.CurrentUser, body: NewConversationBody):
    return await run_in_threadpool(storage.create_conversation, user["id"], body.title or "新对话")


@chat_router.get("/chat/conversations/{conversation_id}")
async def conversation_detail(user: auth.CurrentUser, conversation_id: str):
    conv = await run_in_threadpool(storage.get_conversation, user["id"], conversation_id)
    if not conv:
        # 别人的会话与不存在的会话返回同一个 404，不泄露"这条 id 存在"
        raise HTTPException(status_code=404, detail="会话不存在")
    msgs = await run_in_threadpool(storage.list_messages, user["id"], conversation_id)
    return {"conversation": conv, "messages": msgs}


@chat_router.patch("/chat/conversations/{conversation_id}")
async def rename_conversation(user: auth.CurrentUser, conversation_id: str, body: RenameBody):
    conv = await run_in_threadpool(storage.get_conversation, user["id"], conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    await run_in_threadpool(storage.rename_conversation, user["id"], conversation_id, body.title)
    return {"ok": True}


@chat_router.delete("/chat/conversations/{conversation_id}")
async def delete_conversation(user: auth.CurrentUser, conversation_id: str):
    deleted = await run_in_threadpool(
        storage.delete_conversation, user["id"], conversation_id
    )
    # 与 GET / PATCH 保持一致：别人的会话和不存在的会话都是同一个 404。
    # 不能因为"删除是幂等的"就一律回 200——那样越权尝试会伪装成成功。
    if not deleted:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


@chat_router.post("/chat/conversations/{conversation_id}/messages")
async def send_message(user: auth.CurrentUser, conversation_id: str, body: SendMessageBody):
    """发一条消息并拿到回复。对话历史从 SQLite 读，不再依赖进程内列表。

    这样重启服务、换台机器登录，上下文都还在——这是引入数据库最直接的收益。
    """
    conv = await run_in_threadpool(storage.get_conversation, user["id"], conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    text = (body.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="消息不能为空")

    cfg = await run_in_threadpool(storage.load_llm_config, user["id"])
    if not cfg:
        raise HTTPException(status_code=409, detail="尚未配置 LLM API，请先在「个人设置」中填写")

    history = await run_in_threadpool(storage.list_messages, user["id"], conversation_id)
    await run_in_threadpool(storage.add_message, user["id"], conversation_id, "user", text, None)

    generator = build_generator_for_user(cfg)

    def _run() -> str:
        return generator.chat_with_history(
            [{"role": m["role"], "content": m["content"]} for m in history],
            text,
        )

    try:
        reply = await run_in_threadpool(_run)
    except Exception as exc:  # noqa: BLE001
        from report_generator import describe_llm_error

        raise HTTPException(status_code=502, detail=describe_llm_error(exc)) from exc

    saved = await run_in_threadpool(
        storage.add_message, user["id"], conversation_id, "assistant", reply, None
    )

    # 首条消息用来给会话起名，避免侧边栏一水儿的「新对话」
    if conv["title"] in ("新对话", "", None):
        title = text[:20] + ("…" if len(text) > 20 else "")
        await run_in_threadpool(storage.rename_conversation, user["id"], conversation_id, title)

    return {"reply": reply, "message_id": saved["id"]}
