from pydantic import BaseModel, Field
class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str = Field("", max_length=32)

class LoginRequest(BaseModel):
    username: str
    password: str

class LLMConfigRequest(BaseModel):
    api_key: str = Field("", max_length=512)
    base_url: str = Field("", max_length=256)
    model: str = Field("", max_length=128)


from typing_extensions import TypedDict

class User(TypedDict):
    id: str
    username: str
    display_name: str
