"""登录态：从请求头取 token，解析出当前用户。

token 方案刻意做得简单：随机串存 SQLite，带过期时间，不用 JWT。
理由是没有必要为单实例小应用引入签名密钥轮换、时钟偏移这一套；
JWT 的好处（无状态、跨服务）在这里一条都用不上，反而多一个"注销不掉"的坑。
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Header, HTTPException

import storage

# token 有效期：7 天。演示/内部使用足够，过期后重新登录即可。
TOKEN_TTL = timedelta(days=7)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_user ON sessions(user_id);
"""


def init_sessions() -> None:
    with storage.connect() as conn:
        conn.executescript(_SCHEMA)


def issue_token(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    ts = storage.now()
    with storage.connect() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, ts, ts + TOKEN_TTL.total_seconds()),
        )
    return token


def revoke_token(token: str) -> None:
    with storage.connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def _user_from_token(token: str) -> dict | None:
    with storage.connect() as conn:
        row = conn.execute(
            "SELECT s.user_id, s.expires_at, u.username, u.display_name"
            " FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        ).fetchone()
        if not row:
            return None
        if row["expires_at"] < storage.now():
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None
    return {
        "id": row["user_id"],
        "username": row["username"],
        "display_name": row["display_name"],
    }


async def current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """依赖注入：`user: dict = Depends(current_user)`。

    用 401 而不是 403 —— 前端据此统一跳登录页，不需要区分"没登录"和"没权限"。
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    user = _user_from_token(authorization[7:].strip())
    if not user:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return user


CurrentUser = Annotated[dict, Depends(current_user)]


async def raw_token(authorization: Annotated[str | None, Header()] = None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    return authorization[7:].strip()
