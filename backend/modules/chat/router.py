from fastapi import APIRouter
from typing import Any
from common import deps as auth
from modules.chat.schemas import SendMessageRequest
from modules.chat import service

router = APIRouter()


@router.post('/chat/conversations/{conversation_id}/messages')
async def send_message(
    user: auth.CurrentUser,
    conversation_id: str,
    body: SendMessageRequest,
) -> dict[str, Any]:
    return await service.send_message(user, conversation_id, body)
