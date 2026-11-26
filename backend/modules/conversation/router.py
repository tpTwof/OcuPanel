"""会话 HTTP 绑定；保留 /chat/conversations 协议。"""
from typing import Any
from fastapi import APIRouter
from common import deps as auth
from modules.conversation import service
from modules.conversation.schemas import (
    CreateConversationRequest, RenameConversationRequest, ChangeModeRequest, GraphPreference,
)

router = APIRouter()


@router.get('/chat/conversations')
async def list_conversations(user: auth.CurrentUser) -> dict[str, Any]:
    return await service.list_conversations(user)


@router.post('/chat/conversations')
async def create_conversation(
    user: auth.CurrentUser,
    body: CreateConversationRequest,
) -> dict[str, Any]:
    return await service.create_conversation(user, body)


@router.get('/chat/conversations/{conversation_id}')
async def conversation_detail(
    user: auth.CurrentUser,
    conversation_id: str,
) -> dict[str, Any]:
    return await service.conversation_detail(user, conversation_id)


@router.patch('/chat/conversations/{conversation_id}')
async def rename_conversation(
    user: auth.CurrentUser,
    conversation_id: str,
    body: RenameConversationRequest,
) -> dict[str, Any]:
    return await service.rename_conversation(user, conversation_id, body)


@router.delete('/chat/conversations/{conversation_id}')
async def delete_conversation(
    user: auth.CurrentUser,
    conversation_id: str,
) -> dict[str, Any]:
    return await service.delete_conversation(user, conversation_id)


@router.patch('/chat/conversations/{conversation_id}/graph')
async def change_graph(
    user: auth.CurrentUser, conversation_id: str, body: GraphPreference,
) -> dict[str, bool]:
    return await service.change_graph(user, conversation_id, body)


@router.patch('/chat/conversations/{conversation_id}/mode')
async def change_mode(
    user: auth.CurrentUser, conversation_id: str, body: ChangeModeRequest,
) -> dict[str, str]:
    return await service.change_mode(user, conversation_id, body)
