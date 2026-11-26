"""会话数据访问：本模块只做存储读写，不含业务判断。"""

from __future__ import annotations

from typing import Any

from core import storage


def list_conversations(user_id: str, limit: int = 100) -> list[dict[str, Any]]:
    return storage.list_conversations(user_id, limit)


def get_conversation(user_id: str, conversation_id: str) -> dict[str, Any] | None:
    return storage.get_conversation(user_id, conversation_id)


def create_conversation(user_id: str, title: str, mode: str,
                        graph_enabled: bool | None) -> dict[str, Any]:
    return storage.create_conversation(user_id, title, mode, graph_enabled)


def rename_conversation(user_id: str, conversation_id: str, title: str) -> bool:
    return storage.rename_conversation(user_id, conversation_id, title)


def delete_conversation(user_id: str, conversation_id: str) -> bool:
    return storage.delete_conversation(user_id, conversation_id)


def set_graph_enabled(user_id: str, conversation_id: str, enabled: bool) -> bool:
    return storage.set_graph_enabled(user_id, conversation_id, enabled)


def set_conversation_mode(user_id: str, conversation_id: str, mode: str) -> bool:
    return storage.set_conversation_mode(user_id, conversation_id, mode)


def list_messages(user_id: str, conversation_id: str) -> list[dict[str, Any]]:
    return storage.list_messages(user_id, conversation_id)


def add_message(user_id: str, conversation_id: str, role: str, content: str,
                meta: dict[str, Any] | None) -> dict[str, Any]:
    return storage.add_message(user_id, conversation_id, role, content, meta)


def load_llm_config(user_id: str) -> dict[str, Any] | None:
    return storage.load_llm_config(user_id)