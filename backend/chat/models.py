from pydantic import BaseModel, Field
class CreateConversationRequest(BaseModel):
    title: str = "新对话"

class SendMessageRequest(BaseModel):
    message: str

class RenameConversationRequest(BaseModel):
    title: str
