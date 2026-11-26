"""聊天生成请求。"""
from pydantic import BaseModel


class SendMessageRequest(BaseModel):
    message: str
