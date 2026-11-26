"""Transactional snapshots and durable idempotency receipts in the application DB."""
import json
import sqlite3
from typing import Any

from core import storage
from core.errors import ApplicationError
from modules.screening import access


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS screening_import_previews (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
        payload TEXT NOT NULL, expires_at REAL NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS screening_cases (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
        revision INTEGER NOT NULL, snapshot TEXT NOT NULL, updated_at REAL NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_screening_owner ON screening_cases(user_id, updated_at DESC)")
    if "organization" not in {row["name"] for row in conn.execute("PRAGMA table_info(screening_cases)")}:
        conn.execute("ALTER TABLE screening_cases ADD COLUMN organization TEXT")
    conn.execute("""CREATE TABLE IF NOT EXISTS screening_members (
        user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, organization TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('capture','reader','coordinator')))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS screening_sites (
        organization TEXT PRIMARY KEY, receiving_unit TEXT NOT NULL, emergency_contact TEXT NOT NULL,
        daily_capacity INTEGER NOT NULL CHECK(daily_capacity>0))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS screening_site_policy (
        organization TEXT PRIMARY KEY REFERENCES screening_sites(organization),
        endpoints TEXT NOT NULL, paused INTEGER NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS screening_versions (
        case_id TEXT NOT NULL REFERENCES screening_cases(id), revision INTEGER NOT NULL,
        snapshot TEXT NOT NULL, PRIMARY KEY(case_id, revision))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS screening_requests (
        user_id TEXT NOT NULL REFERENCES users(id), request_key TEXT NOT NULL,
        fingerprint TEXT NOT NULL, result TEXT NOT NULL,
        PRIMARY KEY(user_id, request_key))""")


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def replay(conn: sqlite3.Connection, user_id: str, key: str, fingerprint: str) -> dict | None:
    row = conn.execute("SELECT fingerprint, result FROM screening_requests WHERE user_id=? AND request_key=?",
                       (user_id, key)).fetchone()
    if row is None:
        return None
    if row["fingerprint"] != fingerprint:
        raise ApplicationError(409, "幂等键已用于不同请求，请使用新的幂等键")
    return json.loads(row["result"])


def read(conn: sqlite3.Connection, user_id: str, case_id: str, revision: int | None = None) -> dict:
    owner_id = access.scope(conn, user_id, case_id)
    row = conn.execute("SELECT snapshot FROM screening_cases WHERE id=? AND user_id=?",
                       (case_id, owner_id)).fetchone()
    if row is None:
        raise ApplicationError(404, "病例不存在")
    if revision is not None:
        row = conn.execute("SELECT snapshot FROM screening_versions WHERE case_id=? AND revision=?",
                           (case_id, revision)).fetchone()
        if row is None:
            raise ApplicationError(404, "病例版本不存在")
    return json.loads(row["snapshot"])


def save(conn: sqlite3.Connection, user_id: str, snapshot: dict, key: str, fingerprint: str) -> None:
    raw = encode(snapshot)
    conn.execute("""INSERT INTO screening_cases(id,user_id,revision,snapshot,updated_at) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,
        snapshot=excluded.snapshot, updated_at=excluded.updated_at""",
                 (snapshot["id"], user_id, snapshot["revision"], raw, snapshot["updated_at"]))
    if snapshot["revision"] == 1:
        organization = access.creation_scope(conn, user_id, snapshot["examination"]["institution"])
        conn.execute("UPDATE screening_cases SET organization=? WHERE id=?", (organization, snapshot["id"]))
    conn.execute("INSERT INTO screening_versions VALUES (?, ?, ?)",
                 (snapshot["id"], snapshot["revision"], raw))
    conn.execute("INSERT INTO screening_requests VALUES (?, ?, ?, ?)",
                 (user_id, key, fingerprint, raw))


def remember(conn: sqlite3.Connection, user_id: str, key: str, fingerprint: str, result: dict) -> None:
    conn.execute("INSERT INTO screening_requests VALUES (?, ?, ?, ?)",
                 (user_id, key, fingerprint, encode(result)))


def get_case(user_id: str, case_id: str, revision: int | None = None) -> dict:
    with storage.connect() as conn:
        return read(conn, user_id, case_id, revision)


def list_cases(user_id: str) -> list[dict]:
    with storage.connect() as conn:
        rows = conn.execute("""SELECT snapshot FROM screening_cases
            WHERE (user_id=? AND organization IS NULL) OR organization IN
            (SELECT organization FROM screening_members WHERE user_id=?)
            ORDER BY updated_at DESC LIMIT 200""", (user_id, user_id)).fetchall()
    return [json.loads(row["snapshot"]) for row in rows]
