"""会话接口的请求结构。"""

from pydantic import BaseModel

from modules.chat.models import ChatMode


class GraphPreference(BaseModel):
    graph_enabled: bool


class CreateConversationRequest(BaseModel):
    graph_enabled: bool | None = None
    title: str = "新对话"
    mode: ChatMode = "general"


class SendMessageRequest(BaseModel):
    message: str


class RenameConversationRequest(BaseModel):
    title: str


class ChangeModeRequest(BaseModel):
    mode: ChatMode