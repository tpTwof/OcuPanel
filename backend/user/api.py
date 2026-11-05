from fastapi import APIRouter, Depends
from typing import Any
from utils import auth
from user.models import RegisterRequest, LoginRequest, LLMConfigRequest
from . import service

account_router = APIRouter()

@account_router.post('/account/register')
async def register(body: RegisterRequest) -> dict[str, Any]:
    return await service.register(body)

@account_router.post('/account/login')
async def login(body: LoginRequest) -> dict[str, Any]:
    return await service.login(body)

@account_router.post('/account/logout')
async def logout(token: str=Depends(auth.raw_token)) -> dict[str, Any]:
    return await service.logout(token)

@account_router.get('/account/me')
async def me(user: auth.CurrentUser) -> dict[str, Any]:
    return await service.me(user)

@account_router.get('/account/llm-presets')
async def llm_presets() -> dict[str, Any]:
    return await service.llm_presets()

@account_router.put('/account/llm')
async def save_llm(user: auth.CurrentUser, body: LLMConfigRequest) -> dict[str, Any]:
    return await service.save_llm(user, body)

@account_router.delete('/account/llm')
async def clear_llm(user: auth.CurrentUser) -> dict[str, Any]:
    return await service.clear_llm(user)

@account_router.post('/account/llm/test')
async def test_llm(user: auth.CurrentUser, body: LLMConfigRequest) -> dict[str, Any]:
    return await service.test_llm(user, body)

@account_router.get('/account/usage')
async def usage(user: auth.CurrentUser) -> dict[str, Any]:
    return await service.usage(user)
