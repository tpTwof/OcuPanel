"""账户接口：注册、登录、登出、个人 LLM 配置与用量。

只做 HTTP 参数绑定与响应构造，业务在 service.py。
"""

from typing import Any

from fastapi import APIRouter, Depends

from common import deps as auth
from modules.user import service
from modules.user.schemas import LLMConfigRequest, LoginRequest, RegisterRequest

router = APIRouter()


@router.post('/account/register')
async def register(body: RegisterRequest) -> dict[str, Any]:
    return await service.register(body)


@router.post('/account/login')
async def login(body: LoginRequest) -> dict[str, Any]:
    return await service.login(body)


@router.post('/account/logout')
async def logout(token: str = Depends(auth.raw_token)) -> dict[str, Any]:
    return await service.logout(token)


@router.get('/account/me')
async def me(user: auth.CurrentUser) -> dict[str, Any]:
    return await service.me(user)


@router.get('/account/llm-presets')
async def llm_presets() -> dict[str, Any]:
    return await service.llm_presets()


@router.put('/account/llm')
async def save_llm(user: auth.CurrentUser, body: LLMConfigRequest) -> dict[str, Any]:
    return await service.save_llm(user, body)


@router.delete('/account/llm')
async def clear_llm(user: auth.CurrentUser) -> dict[str, Any]:
    return await service.clear_llm(user)


@router.post('/account/llm/test')
async def test_llm(user: auth.CurrentUser, body: LLMConfigRequest) -> dict[str, Any]:
    return await service.test_llm(user, body)


@router.get('/account/usage')
async def usage(user: auth.CurrentUser) -> dict[str, Any]:
    return await service.usage(user)