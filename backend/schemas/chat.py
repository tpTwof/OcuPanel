from pydantic import BaseModel
from uuid import UUID

class ChatRequest(BaseModel):
    user_id: UUID
    message: str

class ChatResponse(BaseModel):
    response: str
