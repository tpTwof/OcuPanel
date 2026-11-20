from typing import Literal
from pydantic import BaseModel, Field
ChatMode = Literal["general", "ophthalmic"]

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
