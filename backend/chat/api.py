from fastapi import APIRouter, Depends
from typing import Any
from utils import auth
from chat.models import (
    CreateConversationRequest,
    SendMessageRequest,
    RenameConversationRequest,
)
from . import service

chat_router = APIRouter()

@chat_router.get('/chat/conversations')
async def list_conversations(user: auth.CurrentUser) -> dict[str, Any]:
    return await service.list_conversations(user)

@chat_router.post('/chat/conversations')
async def create_conversation(
    user: auth.CurrentUser,
    body: CreateConversationRequest,
) -> dict[str, Any]:
    return await service.create_conversation(user, body)

@chat_router.get('/chat/conversations/{conversation_id}')
async def conversation_detail(
    user: auth.CurrentUser,
    conversation_id: str,
) -> dict[str, Any]:
    return await service.conversation_detail(user, conversation_id)

@chat_router.patch('/chat/conversations/{conversation_id}')
async def rename_conversation(
    user: auth.CurrentUser,
    conversation_id: str,
    body: RenameConversationRequest,
) -> dict[str, Any]:
    return await service.rename_conversation(user, conversation_id, body)

@chat_router.delete('/chat/conversations/{conversation_id}')
async def delete_conversation(
    user: auth.CurrentUser,
    conversation_id: str,
) -> dict[str, Any]:
    return await service.delete_conversation(user, conversation_id)

@chat_router.post('/chat/conversations/{conversation_id}/messages')
async def send_message(
    user: auth.CurrentUser,
    conversation_id: str,
    body: SendMessageRequest,
) -> dict[str, Any]:
    return await service.send_message(user, conversation_id, body)
