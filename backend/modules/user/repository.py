"""账户数据访问：本模块只做 SQL，不含业务判断。

底层的连接、建表与迁移集中在 utils.storage，这里按模块需要包一层语义化接口，
让 service 层不必直接拼 SQL。
"""

from __future__ import annotations

from typing import Any

from core import storage


# -- 用户 -------------------------------------------------------------------
def create_user(username: str, password: str, display_name: str) -> dict[str, Any]:
    return storage.create_user(username, password, display_name)


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    return storage.authenticate(username, password)


# -- LLM 配置 ---------------------------------------------------------------
def load_llm_config(user_id: str) -> dict[str, Any] | None:
    return storage.load_llm_config(user_id)


def llm_config_public(user_id: str) -> dict[str, Any] | None:
    return storage.llm_config_public(user_id)


def save_llm_config(user_id: str, api_key: str, base_url: str, model: str) -> None:
    storage.save_llm_config(user_id, api_key, base_url, model)


def delete_llm_config(user_id: str) -> None:
    storage.delete_llm_config(user_id)


# -- 用量概览 ---------------------------------------------------------------
def list_reports(user_id: str, limit: int) -> list[dict[str, Any]]:
    return storage.list_reports(user_id, limit)


def list_conversations(user_id: str, limit: int) -> list[dict[str, Any]]:
    return storage.list_conversations(user_id, limit)