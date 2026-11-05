from typing import Literal
from pydantic import BaseModel, Field
ChatMode = Literal["general", "ophthalmic"]

class CreateConversationRequest(BaseModel):
    title: str = "新对话"
    mode: ChatMode = "general"

class SendMessageRequest(BaseModel):
    message: str

class RenameConversationRequest(BaseModel):
    title: str


class ChangeModeRequest(BaseModel):
    mode: ChatMode
