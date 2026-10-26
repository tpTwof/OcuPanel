"""账号与个人设置接口：注册、登录、登出、查询/保存/清除本人的 LLM 配置。

关键约束：**API Key 只进不出**。任何响应都不包含明文 key，
只回显首尾片段供用户确认"填的是哪一把"。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import auth
import config
import storage

account_router = APIRouter()

# 预设几个常见端点，前端下拉直接选，省得用户手打
PRESETS = [
    {"label": "DeepSeek", "base_url": "https://api.deepseek.com", "models": ["deepseek-chat", "deepseek-flash"]},
    {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "models": ["gpt-4.1", "gpt-4o-mini"]},
    {"label": "Moonshot", "base_url": "https://api.moonshot.cn/v1", "models": ["moonshot-v1-8k"]},
    {"label": "阿里云百炼", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "models": ["qwen-plus"]},
]


class RegisterBody(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str = Field("", max_length=32)


class LoginBody(BaseModel):
    username: str
    password: str


class LLMConfigBody(BaseModel):
    api_key: str = Field("", max_length=512)
    base_url: str = Field("", max_length=256)
    model: str = Field("", max_length=128)


def _payload(user: dict) -> dict:
    return {"user": user, "token": auth.issue_token(user["id"])}


@account_router.post("/account/register")
async def register(body: RegisterBody):
    try:
        user = await run_in_threadpool(
            storage.create_user, body.username, body.password, body.display_name
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _payload(user)


@account_router.post("/account/login")
async def login(body: LoginBody):
    user = await run_in_threadpool(storage.authenticate, body.username, body.password)
    if not user:
        # 不区分"用户不存在"和"密码错误"，避免用户名枚举
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return _payload(user)


@account_router.post("/account/logout")
async def logout(token: str = Depends(auth.raw_token)):
    await run_in_threadpool(auth.revoke_token, token)
    return {"ok": True}


@account_router.get("/account/me")
async def me(user: auth.CurrentUser):
    cfg = await run_in_threadpool(storage.llm_config_public, user["id"])
    return {"user": user, "llm": cfg}


@account_router.get("/account/llm-presets")
async def llm_presets():
    """预设列表 + 服务器默认值，供前端"用默认配置"一键填充。"""
    return {
        "presets": PRESETS,
        "defaults": {"base_url": config.OPENAI_BASE_URL or "", "model": config.OPENAI_MODEL or ""},
    }


@account_router.put("/account/llm")
async def save_llm(user: auth.CurrentUser, body: LLMConfigBody):
    api_key = (body.api_key or "").strip()
    if not api_key:
        # 允许"只改模型/端点不改 key"：此时前端传空 key，沿用库里已存的
        existing = await run_in_threadpool(storage.load_llm_config, user["id"])
        if not existing:
            raise HTTPException(status_code=400, detail="请填写 API Key")
        api_key = existing["api_key"]

    if not (body.base_url or "").strip():
        raise HTTPException(status_code=400, detail="请填写接口地址（Base URL）")
    if not (body.model or "").strip():
        raise HTTPException(status_code=400, detail="请填写模型名称")

    await run_in_threadpool(
        storage.save_llm_config, user["id"], api_key, body.base_url, body.model
    )
    return await run_in_threadpool(storage.llm_config_public, user["id"])


@account_router.delete("/account/llm")
async def clear_llm(user: auth.CurrentUser):
    await run_in_threadpool(storage.delete_llm_config, user["id"])
    return {"ok": True}


@account_router.post("/account/llm/test")
async def test_llm(user: auth.CurrentUser, body: LLMConfigBody):
    """用用户填的配置发一次最小请求，验证 key / 端点 / 模型是否都对得上。

    不落库——先测通再保存，避免把错的配置存进去之后每次生成都失败。
    """
    api_key = (body.api_key or "").strip()
    if not api_key:
        existing = await run_in_threadpool(storage.load_llm_config, user["id"])
        if not existing:
            raise HTTPException(status_code=400, detail="请填写 API Key")
        api_key = existing["api_key"]

    def _run() -> dict:
        import openai

        client = openai.OpenAI(
            api_key=api_key,
            base_url=(body.base_url or "").strip() or None,
            timeout=config.LLM_TIMEOUT,
            max_retries=0,
        )
        resp = client.chat.completions.create(
            model=(body.model or "").strip(),
            messages=[{"role": "user", "content": "只回复两个字：收到"}],
            temperature=0,
            # 8 个 token 会被推理型模型全部花在思考上，content 返回空串，
            # 看起来像"连通了但没说话"。给 64 留足余量。
            max_tokens=64,
        )
        usage = getattr(resp, "usage", None)
        reply = (resp.choices[0].message.content or "").strip()
        return {
            "ok": True,
            # 空内容也算连通（模型可能把额度花在 reasoning 上），前端据此提示
            "reply": reply[:40] or "（空响应，但连接与鉴权正常）",
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
        }

    try:
        return await run_in_threadpool(_run)
    except Exception as exc:  # noqa: BLE001 - 把厂商错误原文交给用户，便于自查
        from report_generator import describe_llm_error

        raise HTTPException(
            status_code=400,
            detail=describe_llm_error(
                exc, (body.base_url or "").strip(), from_user_config=True
            ),
        ) from exc


@account_router.get("/account/usage")
async def usage(user: auth.CurrentUser):
    """轻量的用量概览：报告数量与最近一次时间。费用明细请去厂商后台看。"""
    reports = await run_in_threadpool(storage.list_reports, user["id"], 100)
    convs = await run_in_threadpool(storage.list_conversations, user["id"], 100)
    last = max((r["created_at"] for r in reports), default=None)
    return {
        "reports": len(reports),
        "conversations": len(convs),
        "rejected": sum(1 for r in reports if r["rejected"]),
        "last_report_at": datetime.fromtimestamp(last).isoformat(timespec="seconds") if last else None,
    }
