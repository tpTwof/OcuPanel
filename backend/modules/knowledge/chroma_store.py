"""基于 Chroma 的向量存储。

Chroma 负责候选检索与元数据过滤；向量与原文快照落在一个本地文件中，
避免 chromadb 1.5.9 的 Rust 后端在 Windows 上无法打开持久化路径的问题
（``PersistentClient`` 会报 ``unable to open database file``）。

记录同时保存：id、向量、原文、出处元数据，因此检索后可直接取回原文，
不必再回到内存 chunks 按下标回查。
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Callable

import numpy as np

EmbedFn = Callable[[list[str]], np.ndarray]
SNAPSHOT_NAME = "passages.json"
VECTORS_NAME = "vectors.npy"


def _safe_name(text: str) -> str:
    """Chroma 的 collection 名要求 3-512 位且以字母数字开头结尾。"""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    base = "".join(ch if ch.isalnum() else "_" for ch in text)
    return f"passages_{base[:40]}_{digest}"


class ChromaVectorStore:
    """Chroma 内存索引 + 本地快照，进程启动时装载。

    快照只存必要字段（id、原文、向量、元数据），改语料后按 id 增量重建。
    """

    def __init__(self, path: Path, embed_fn: EmbedFn, model: str) -> None:
        import chromadb

        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self._embed = embed_fn
        self.model = model
        self.name = _safe_name(model)
        self._lock = threading.Lock()
        self._client = chromadb.EphemeralClient()
        self._collection = self._client.get_or_create_collection(
            name=self.name, metadata={"hnsw:space": "cosine"},
        )
        self._ids: list[str] = []
        self._matrix = np.empty((0, 0), dtype=np.float32)

    # -- 快照 ---------------------------------------------------------------
    @property
    def _snapshot_path(self) -> Path:
        return self.path / SNAPSHOT_NAME

    def _read_snapshot(self) -> tuple[dict[str, str], dict[str, Any], np.ndarray]:
        """返回 (id -> 原文, id -> 元数据, 向量矩阵)。快照缺失时返回空。"""
        snap = self._snapshot_path
        vec = self.path / VECTORS_NAME
        if not snap.exists() or not vec.exists():
            return {}, {}, np.empty((0, 0), dtype=np.float32)
        try:
            data = json.loads(snap.read_text(encoding="utf-8"))
            if data.get("model") != self.model:
                return {}, {}, np.empty((0, 0), dtype=np.float32)
            docs = {row["id"]: row["text"] for row in data["passages"]}
            metas = {row["id"]: row.get("metadata", {}) for row in data["passages"]}
            matrix = np.load(vec)
            if matrix.shape[0] != len(data["passages"]):
                return {}, {}, np.empty((0, 0), dtype=np.float32)
            return docs, metas, matrix
        except (OSError, ValueError, KeyError):
            return {}, {}, np.empty((0, 0), dtype=np.float32)

    def _write_snapshot(self, ids: list[str], texts: list[str],
                        metas: list[dict[str, Any]], matrix: np.ndarray) -> None:
        payload = {
            "model": self.model,
            "passages": [
                {"id": key, "text": texts[i], "metadata": metas[i]}
                for i, key in enumerate(ids)
            ],
        }
        self._snapshot_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        np.save(self.path / VECTORS_NAME, matrix)

    # -- 同步 ---------------------------------------------------------------
    def sync(self, ids: list[str], texts: list[str],
             metas: list[dict[str, Any]]) -> int:
        """让库内内容与给定语料一致，返回本次新编码的条数。"""
        with self._lock:
            known_docs, known_metas, known_matrix = self._read_snapshot()
            position = {key: i for i, key in enumerate(known_docs)}
            current = dict(zip(ids, texts))

            # 复用未变化的向量，其余重新编码
            vectors: list[np.ndarray | None] = [None] * len(ids)
            pending: list[int] = []
            for i, key in enumerate(ids):
                if known_docs.get(key) == texts[i] and key in position:
                    vectors[i] = known_matrix[position[key]]
                else:
                    pending.append(i)
            if pending:
                encoded = self._embed([texts[i] for i in pending])
                for i, vec in zip(pending, encoded):
                    vectors[i] = vec

            matrix = (np.stack(vectors).astype(np.float32)
                      if vectors else np.empty((0, 0), dtype=np.float32))
            # 内容有变化时重建 collection，保证索引与快照一致
            if pending or set(known_docs) != set(current):
                self._rebuild(ids, texts, metas, matrix)
                self._write_snapshot(ids, texts, metas, matrix)
            else:
                self._prime(ids, texts, metas, matrix)
            self._ids = list(ids)
            self._matrix = matrix
            return len(pending)

    def _rebuild(self, ids: list[str], texts: list[str],
                 metas: list[dict[str, Any]], matrix: np.ndarray) -> None:
        try:
            self._client.delete_collection(self.name)
        except Exception:  # noqa: BLE001 - 集合不存在时忽略
            pass
        self._collection = self._client.get_or_create_collection(
            name=self.name, metadata={"hnsw:space": "cosine"},
        )
        self._prime(ids, texts, metas, matrix)

    def _prime(self, ids: list[str], texts: list[str],
               metas: list[dict[str, Any]], matrix: np.ndarray) -> None:
        if not ids or matrix.size == 0:
            return
        self._collection.upsert(
            ids=list(ids),
            embeddings=[vec.tolist() for vec in matrix],
            documents=list(texts),
            metadatas=[_flatten(meta) for meta in metas],
        )

    # -- 读取 ---------------------------------------------------------------
    def matrix(self, ids: list[str]) -> np.ndarray:
        """按给定 id 顺序返回向量矩阵，供相似度计算使用。"""
        lookup = {key: i for i, key in enumerate(self._ids)}
        if any(key not in lookup for key in ids):
            raise KeyError("passages missing from vector store")
        return self._matrix[[lookup[key] for key in ids]]

    def count(self) -> int:
        return len(self._ids)

    def query(self, vector: np.ndarray, n_results: int) -> list[str]:
        """用 Chroma 的 ANN 索引取候选 id（按距离从近到远）。"""
        if not self._ids or n_results <= 0:
            return []
        found = self._collection.query(
            query_embeddings=[np.asarray(vector, dtype=np.float32).tolist()],
            n_results=min(n_results, len(self._ids)),
            include=[],
        )
        return list((found.get("ids") or [[]])[0])


def _flatten(meta: dict[str, Any]) -> dict[str, Any]:
    """Chroma 的元数据只接受标量，缺失值用空串占位。"""
    out: dict[str, Any] = {}
    for key, value in meta.items():
        if isinstance(value, str):
            out[key] = value
        elif isinstance(value, (int, float, bool)):
            out[key] = value
        elif value is None:
            out[key] = ""
    return out