"""SQLite 持久化层：用户、LLM 配置、会话、消息、报告留痕。

设计取舍：
- **只用标准库 sqlite3**，不引 ORM。表就五张，写 SQL 比引 SQLAlchemy
  （并顺带引入一个 200MB 的依赖树）划算。
- **每个请求开一条连接**（`connect()` 上下文管理器）。SQLite 的连接不能跨线程，
  而 FastAPI 用线程池跑同步代码；用连接池反而要处理线程亲和性，得不偿失。
  开连接本身是微秒级，配合 WAL 后并发读写也够用。
- **隔离靠 user_id 落在每一行上**，所有查询强制带 `user_id = ?`。
  不靠"应用层记得过滤"，而是把 user_id 做成查询函数的第一参数，漏写会立刻报错。

安全：
- 密码用 PBKDF2-HMAC-SHA256 + 每用户随机盐，迭代次数写在哈希串里，
  以后调高迭代不会让老密码失效。
- LLM API Key 用 Fernet 对称加密后入库。密钥来自 `.env` 的 `OCUPANEL_SECRET_KEY`，
  首次启动自动生成并写回；数据库文件被单独拿走也读不出明文 Key。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import config

DB_PATH = Path(__file__).resolve().parent / "ocupanel.db"

# PBKDF2 迭代次数：600k 是 OWASP 2023 对 SHA256 的建议值。
# 登录一次约 0.1–0.2 秒，对交互无感，但把离线爆破成本抬高了几个数量级。
PBKDF2_ITERATIONS = 600_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    display_name  TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL
);

-- 一个用户一条 LLM 配置（当前需求是"个人管理自己的 api"，不需要多套）
CREATE TABLE IF NOT EXISTS llm_configs (
    user_id    TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    api_key_enc TEXT NOT NULL,
    base_url   TEXT NOT NULL DEFAULT '',
    model      TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT NOT NULL DEFAULT '新对话',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id         TEXT NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    meta            TEXT NOT NULL DEFAULT '{}',
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, created_at);

-- 报告留痕：拒答的也存，因为"曾经拒答过"本身就是有价值的信息
CREATE TABLE IF NOT EXISTS reports (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id TEXT,
    img_name        TEXT NOT NULL DEFAULT '',
    cup_to_disc     REAL,
    glaucoma_prob   REAL,
    summary         TEXT NOT NULL DEFAULT '',
    verification    TEXT NOT NULL DEFAULT '{}',
    evidence        TEXT NOT NULL DEFAULT '[]',
    rejected        INTEGER NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_report_user ON reports(user_id, created_at DESC);
"""


# ---------------------------------------------------------------------------
# 连接
# ---------------------------------------------------------------------------
@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """一个请求一条连接。WAL 让读不阻塞写，适合"边写对话边查历史"。"""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """建表。幂等，每次启动都跑一遍。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


def new_id() -> str:
    return secrets.token_hex(16)


def now() -> float:
    return time.time()


def purge_expired_sessions() -> int:
    """清掉过期登录态。启动时跑一次，返回删除条数。

    以后每次 `_user_from_token` 命中过期也会顺手删，所以这里漏几次不影响正确性，
    只是为了不让 sessions 表无限增长。
    """
    with connect() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now(),))
        return cur.rowcount or 0


# ---------------------------------------------------------------------------
# 加解密：API Key 落库前加密
# ---------------------------------------------------------------------------
_fernet = None


def _secret_key() -> bytes:
    """取 Fernet 密钥。优先用环境变量，缺失则生成并写回 .env。

    写回 .env 而不是内存里临时生成 —— 否则重启后旧密钥解不开已存的 API Key，
    用户会看到"配置还在但调用失败"，比直接报错更难查。
    """
    raw = os.getenv("OCUPANEL_SECRET_KEY", "").strip()
    if raw:
        try:
            return raw.encode()
        except Exception:  # noqa: BLE001
            pass

    from cryptography.fernet import Fernet

    generated = Fernet.generate_key().decode()
    env_path = Path(__file__).resolve().parent / ".env"
    try:
        existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        if "OCUPANEL_SECRET_KEY" not in existing:
            with env_path.open("a", encoding="utf-8") as fh:
                if existing and not existing.endswith("\n"):
                    fh.write("\n")
                fh.write(
                    "\n# 自动生成：用于加密用户 API Key。丢失＝已存的 Key 全部失效。\n"
                    f"OCUPANEL_SECRET_KEY={generated}\n"
                )
            print("[STORE] 已生成 OCUPANEL_SECRET_KEY 并写入 backend/.env", flush=True)
    except OSError as exc:
        print(f"[STORE] 无法写入 .env（{exc}），本次使用临时密钥", flush=True)

    os.environ["OCUPANEL_SECRET_KEY"] = generated
    return generated.encode()


def _get_fernet():
    global _fernet
    if _fernet is None:
        from cryptography.fernet import Fernet

        _fernet = Fernet(_secret_key())
    return _fernet


def encrypt_secret(plain: str) -> str:
    return _get_fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    return _get_fernet().decrypt(token.encode("ascii")).decode("utf-8")


# ---------------------------------------------------------------------------
# 密码
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(expected, actual)
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# 用户
# ---------------------------------------------------------------------------
def create_user(username: str, password: str, display_name: str = "") -> dict:
    username = (username or "").strip()
    if len(username) < 3:
        raise ValueError("用户名至少 3 个字符")
    if len(password or "") < 6:
        raise ValueError("密码至少 6 位")

    user_id = new_id()
    with connect() as conn:
        try:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, display_name, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (user_id, username, hash_password(password), display_name or username, now()),
            )
        except sqlite3.IntegrityError:
            raise ValueError("该用户名已被占用") from None
    return {"id": user_id, "username": username, "display_name": display_name or username}


def authenticate(username: str, password: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, username, display_name, password_hash FROM users WHERE username = ?",
            ((username or "").strip(),),
        ).fetchone()
    if not row or not verify_password(password or "", row["password_hash"]):
        return None
    return {"id": row["id"], "username": row["username"], "display_name": row["display_name"]}


def get_user(user_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, username, display_name FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# LLM 配置
# ---------------------------------------------------------------------------
def save_llm_config(user_id: str, api_key: str, base_url: str, model: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO llm_configs (user_id, api_key_enc, base_url, model, updated_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(user_id) DO UPDATE SET"
            " api_key_enc=excluded.api_key_enc, base_url=excluded.base_url,"
            " model=excluded.model, updated_at=excluded.updated_at",
            (user_id, encrypt_secret(api_key.strip()), base_url.strip(), model.strip(), now()),
        )


def load_llm_config(user_id: str) -> dict | None:
    """返回解密后的完整配置（仅后端内部使用，绝不下发给前端）。"""
    with connect() as conn:
        row = conn.execute(
            "SELECT api_key_enc, base_url, model, updated_at FROM llm_configs WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "api_key": decrypt_secret(row["api_key_enc"]),
        "base_url": row["base_url"],
        "model": row["model"],
        "updated_at": row["updated_at"],
    }


def llm_config_public(user_id: str) -> dict | None:
    """给前端看的安全版本：只回显 key 的首尾片段，不回明文。"""
    with connect() as conn:
        row = conn.execute(
            "SELECT api_key_enc, base_url, model, updated_at FROM llm_configs WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    try:
        key = decrypt_secret(row["api_key_enc"])
        masked = f"{key[:6]}...{key[-4:]}" if len(key) > 12 else "已设置"
    except Exception:  # noqa: BLE001 - 密钥轮换后旧数据解不开，按"需重填"处理
        masked = "（无法解密，请重新填写）"
    return {
        "has_key": True,
        "api_key_masked": masked,
        "base_url": row["base_url"],
        "model": row["model"],
        "updated_at": row["updated_at"],
    }


def delete_llm_config(user_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM llm_configs WHERE user_id = ?", (user_id,))


# ---------------------------------------------------------------------------
# 会话与消息
# ---------------------------------------------------------------------------
def create_conversation(user_id: str, title: str = "新对话") -> dict:
    cid = new_id()
    ts = now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO conversations (id, user_id, title, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (cid, user_id, title, ts, ts),
        )
    return {"id": cid, "title": title, "created_at": ts, "updated_at": ts}


def list_conversations(user_id: str, limit: int = 50) -> list[dict]:
    """只返回该用户自己的会话——user_id 是函数必填参数，避免漏加过滤条件。"""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at FROM conversations"
            " WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_conversation(user_id: str, conversation_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, title, created_at, updated_at FROM conversations"
            " WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def rename_conversation(user_id: str, conversation_id: str, title: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (title[:60], now(), conversation_id, user_id),
        )


def delete_conversation(user_id: str, conversation_id: str) -> int:
    """删除会话，返回实际删除的行数。

    调用方靠这个返回值区分"真删了"和"这条根本不属于你/不存在"——
    SQL 里的 user_id 保证了越权删不掉，但如果不看 rowcount，
    接口会对越权请求回 200，让人以为删成功了。
    """
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM conversations WHERE id = ? AND user_id = ?", (conversation_id, user_id)
        )
        return cur.rowcount or 0


def list_messages(user_id: str, conversation_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, role, content, meta, created_at FROM messages"
            " WHERE conversation_id = ? AND user_id = ? ORDER BY created_at ASC",
            (conversation_id, user_id),
        ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        try:
            item["meta"] = json.loads(item["meta"] or "{}")
        except json.JSONDecodeError:
            item["meta"] = {}
        out.append(item)
    return out


def add_message(
    user_id: str, conversation_id: str, role: str, content: str, meta: dict | None = None
) -> dict:
    mid = new_id()
    ts = now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO messages (id, conversation_id, user_id, role, content, meta, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (mid, conversation_id, user_id, role, content, json.dumps(meta or {}, ensure_ascii=False), ts),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ? AND user_id = ?",
            (ts, conversation_id, user_id),
        )
    return {"id": mid, "role": role, "content": content, "meta": meta or {}, "created_at": ts}


def save_report(
    user_id: str,
    conversation_id: str | None,
    img_name: str,
    summary: str,
    verification: dict,
    evidence: list,
    rejected: bool,
    cup_to_disc: float | None = None,
    glaucoma_prob: float | None = None,
) -> str:
    rid = new_id()
    with connect() as conn:
        conn.execute(
            "INSERT INTO reports (id, user_id, conversation_id, img_name, cup_to_disc,"
            " glaucoma_prob, summary, verification, evidence, rejected, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rid,
                user_id,
                conversation_id,
                img_name,
                cup_to_disc,
                glaucoma_prob,
                summary,
                json.dumps(verification or {}, ensure_ascii=False),
                json.dumps(evidence or [], ensure_ascii=False),
                1 if rejected else 0,
                now(),
            ),
        )
    return rid


def list_reports(user_id: str, limit: int = 20) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, img_name, cup_to_disc, glaucoma_prob, rejected, created_at"
            " FROM reports WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]
