"""账户业务：注册、登录、登出、个人 LLM 配置与用量概览。

关键约束：**API Key 只进不出**。任何响应都不包含明文 key，
只回显首尾片段供用户确认「填的是哪一把」。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from starlette.concurrency import run_in_threadpool

from common import auth
from core.errors import ApplicationError
from core.llm.client import describe_llm_error
from modules.account import repository
from modules.account.models import User
from modules.account.schemas import LLMConfigRequest, LoginRequest, RegisterRequest
from core import config_impl as config

# 预设几个常见端点，前端下拉直接选，省得用户手打
PRESETS = [
    {"label": "DeepSeek", "base_url": "https://api.deepseek.com",
     "models": ["deepseek-chat", "deepseek-flash"]},
    {"label": "OpenAI", "base_url": "https://api.openai.com/v1",
     "models": ["gpt-4.1", "gpt-4o-mini"]},
    {"label": "Moonshot", "base_url": "https://api.moonshot.cn/v1",
     "models": ["moonshot-v1-8k"]},
    {"label": "阿里云百炼", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "models": ["qwen-plus"]},
]


def _payload(user: User) -> dict[str, Any]:
    return {"user": user, "token": auth.issue_token(user["id"])}


async def register(body: RegisterRequest) -> dict[str, Any]:
    try:
        user = await run_in_threadpool(
            repository.create_user, body.username, body.password, body.display_name
        )
    except ValueError as exc:
        raise ApplicationError(status_code=400, detail=str(exc)) from exc
    return _payload(user)


async def login(body: LoginRequest) -> dict[str, Any]:
    user = await run_in_threadpool(repository.authenticate, body.username, body.password)
    if not user:
        # 不区分「用户不存在」和「密码错误」，避免用户名枚举
        raise ApplicationError(status_code=401, detail="用户名或密码错误")
    return _payload(user)


async def logout(token: str) -> dict[str, Any]:
    await run_in_threadpool(auth.revoke_token, token)
    return {"ok": True}


async def me(user: User) -> dict[str, Any]:
    cfg = await run_in_threadpool(repository.llm_config_public, user["id"])
    return {"user": user, "llm": cfg}


async def llm_presets() -> dict[str, Any]:
    """预设列表 + 服务器默认值，供前端「用默认配置」一键填充。"""
    return {
        "presets": PRESETS,
        "defaults": {"base_url": config.OPENAI_BASE_URL or "",
                     "model": config.OPENAI_MODEL or ""},
    }


async def _resolve_api_key(user: User, body: LLMConfigRequest) -> str:
    """允许「只改模型/端点不改 key」：此时前端传空 key，沿用库里已存的。"""
    api_key = (body.api_key or "").strip()
    if api_key:
        return api_key
    existing = await run_in_threadpool(repository.load_llm_config, user["id"])
    if not existing:
        raise ApplicationError(status_code=400, detail="请填写 API Key")
    return existing["api_key"]


async def save_llm(user: User, body: LLMConfigRequest) -> dict[str, Any]:
    api_key = await _resolve_api_key(user, body)
    if not (body.base_url or "").strip():
        raise ApplicationError(status_code=400, detail="请填写接口地址（Base URL）")
    if not (body.model or "").strip():
        raise ApplicationError(status_code=400, detail="请填写模型名称")

    await run_in_threadpool(
        repository.save_llm_config, user["id"], api_key, body.base_url, body.model
    )
    return await run_in_threadpool(repository.llm_config_public, user["id"])


async def clear_llm(user: User) -> dict[str, Any]:
    await run_in_threadpool(repository.delete_llm_config, user["id"])
    return {"ok": True}


async def test_llm(user: User, body: LLMConfigRequest) -> dict[str, Any]:
    """用用户填的配置发一次最小请求，验证 key / 端点 / 模型是否都对得上。

    不落库——先测通再保存，避免把错的配置存进去之后每次生成都失败。
    """
    api_key = await _resolve_api_key(user, body)

    def _run() -> dict:
        from modules.account.llm_probe import probe_llm
        from modules.screening.access import check_endpoint
        from core import storage

        with storage.connect() as conn:
            check_endpoint(conn, user["id"], body.base_url)
        return probe_llm(api_key, (body.base_url or "").strip(),
                         (body.model or "").strip())

    try:
        return await run_in_threadpool(_run)
    except Exception as exc:  # noqa: BLE001 - 把厂商错误原文交给用户，便于自查
        raise ApplicationError(
            status_code=400,
            detail=describe_llm_error(exc, (body.base_url or "").strip(),
                                      from_user_config=True),
        ) from exc


async def usage(user: User) -> dict[str, Any]:
    """轻量的用量概览：报告数量与最近一次时间。费用明细请去厂商后台看。"""
    reports = await run_in_threadpool(repository.list_reports, user["id"], 100)
    convs = await run_in_threadpool(repository.list_conversations, user["id"], 100)
    last = max((r["created_at"] for r in reports), default=None)
    return {
        "reports": len(reports),
        "conversations": len(convs),
        "rejected": sum(1 for r in reports if r["rejected"]),
        "last_report_at": (
            datetime.fromtimestamp(last).isoformat(timespec="seconds") if last else None
        ),
    }