"""SQLite cache of passage embeddings, shared by retrieval modes and processes."""

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np


class VectorCache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with closing(sqlite3.connect(path, timeout=30)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS embeddings "
                "(key TEXT PRIMARY KEY, dimensions INTEGER NOT NULL, vector BLOB NOT NULL)"
            )

    @staticmethod
    def key(model: str, revision: str, text: str) -> str:
        payload = "\0".join(("e5-mean-l2-512-v1", model, revision, text))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, key: str) -> np.ndarray | None:
        with closing(sqlite3.connect(self.path, timeout=30)) as connection:
            row = connection.execute("SELECT dimensions, vector FROM embeddings WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        vector = np.frombuffer(row[1], dtype="<f4").copy()
        if vector.size != row[0] or not np.isfinite(vector).all():
            return None
        return vector

    def put(self, rows: list[tuple[str, np.ndarray]]) -> None:
        with closing(sqlite3.connect(self.path, timeout=30)) as connection, connection:
            connection.executemany(
                "INSERT OR REPLACE INTO embeddings VALUES (?, ?, ?)",
                [(key, vector.size, np.asarray(vector, dtype="<f4").tobytes()) for key, vector in rows],
            )
