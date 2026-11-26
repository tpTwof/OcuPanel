"""Original images are retrieved only after checking their report owner and hash."""
import hashlib
import json
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

ORIGINAL_STORE_DIR = Path(__file__).resolve().parents[1] / "original_store"


def original_path(metadata: dict[str, Any]) -> Path | None:
    identifier = metadata.get("original_id", "")
    if not isinstance(identifier, str) or len(identifier) != 32 or any(char not in "0123456789abcdef" for char in identifier):
        return None
    return ORIGINAL_STORE_DIR / f"{identifier}.bin"


def read_original(metadata: dict[str, Any]) -> tuple[str, bytes | None]:
    path = original_path(metadata)
    if path is None:
        return "missing", None
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        return "missing", None
    if hashlib.sha256(content).hexdigest() != metadata.get("original_sha256"):
        return "hash_mismatch", None
    return "available", content


def inspect_original(metadata: dict[str, Any]) -> dict[str, Any]:
    status, _ = read_original(metadata)
    return {"status": status, "sha256": metadata.get("original_sha256"), "original_id": metadata.get("original_id")}

def expire_originals(database: Path, directory: Path, days: int, apply: bool) -> int:
    if days < 1:
        raise ValueError("Retention must be at least one day")
    directory = directory.absolute()
    if directory.resolve() != directory:
        raise ValueError("Unexpected original directory")
    database = database.resolve()
    affected = 0
    with closing(sqlite3.connect(database.as_uri() + "?mode=rw", uri=True)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        cutoff = time.time() - days * 86400
        rows = conn.execute("SELECT id,created_at,source_metadata FROM reports")
        originals = {}
        for _, created, raw in rows:
            identifier = json.loads(raw).get("original_id")
            if isinstance(identifier, str) and re.fullmatch(r"[0-9a-f]{32}", identifier):
                originals[identifier] = max(created, originals.get(identifier, created))
        for identifier, last_use in originals.items():
            path = directory / (identifier + ".bin")
            if last_use < cutoff and path.is_file() and not path.is_symlink() and path.resolve().parent == directory.resolve():
                affected += 1
                if apply:
                    path.unlink()
    return affected
