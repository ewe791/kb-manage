"""FAISS 内存向量索引（不可用时退回 numpy 余弦检索）。

索引按 unit_id 映射；每次知识单元增删改后调用 mark_dirty()，检索前惰性重建，
保证与数据库一致。
"""
from __future__ import annotations

import logging
import threading

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, KnowledgeUnit
from app.services.embedder import current_dim, embed_texts, from_bytes, to_bytes

logger = logging.getLogger(__name__)

try:  # pragma: no cover - 取决于运行环境
    import faiss  # type: ignore

    _HAS_FAISS = True
except Exception:  # noqa: BLE001
    faiss = None  # type: ignore
    _HAS_FAISS = False


class VectorStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._dirty = True
        self._chunk_ids: list[str] = []
        self._unit_ids: list[str] = []
        self._matrix: np.ndarray | None = None
        self._faiss_index = None
        self.backend = "faiss" if _HAS_FAISS else "numpy"

    def mark_dirty(self) -> None:
        self._dirty = True

    def _load(self, db: Session) -> None:
        rows = db.execute(
            select(KnowledgeChunk.id, KnowledgeChunk.unit_id, KnowledgeChunk.chunk_text, KnowledgeChunk.embedding)
            .join(KnowledgeUnit, KnowledgeUnit.id == KnowledgeChunk.unit_id)
            .where(KnowledgeUnit.status == "active")
            .order_by(KnowledgeChunk.unit_id, KnowledgeChunk.chunk_index)
        ).all()

        dim = current_dim()
        ids: list[str] = []
        unit_ids: list[str] = []
        vecs: list[np.ndarray] = []
        pending: list[tuple[int, str, str]] = []  # (position, chunk_id, text)

        for chunk_id, unit_id, text, embedding in rows:
            ids.append(chunk_id)
            unit_ids.append(unit_id)
            usable = embedding is not None and len(embedding) == dim * 4
            if usable:
                vecs.append(from_bytes(embedding, dim))
            else:
                vecs.append(np.zeros(dim, dtype=np.float32))
                pending.append((len(vecs) - 1, chunk_id, text))

        if pending:
            encoded = embed_texts([p[2] for p in pending])
            for row_idx, (pos, chunk_id, _text) in enumerate(pending):
                vecs[pos] = encoded[row_idx]
                db.query(KnowledgeChunk).filter(KnowledgeChunk.id == chunk_id).update(
                    {"embedding": to_bytes(encoded[row_idx])}
                )

        self._chunk_ids = ids
        self._unit_ids = unit_ids
        if vecs:
            matrix = np.vstack([v.reshape(1, -1) for v in vecs]).astype(np.float32)
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            matrix = matrix / norms
            self._matrix = matrix
            if _HAS_FAISS:
                index = faiss.IndexFlatIP(matrix.shape[1])
                index.add(matrix)
                self._faiss_index = index
        else:
            self._matrix = None
            self._faiss_index = None

        db.commit()
        self._dirty = False
        logger.info("向量索引已重建：%s 个切片（backend=%s）", len(ids), self.backend)

    def ensure(self, db: Session) -> None:
        if not self._dirty:
            return
        with self._lock:
            if not self._dirty:
                return
            self._load(db)

    def search(self, db: Session, query_vec: np.ndarray, top_n: int) -> list[tuple[str, str, float]]:
        """返回 [(unit_id, chunk_id, score)]，按得分降序。"""
        self.ensure(db)
        if self._matrix is None or not self._chunk_ids:
            return []
        q = np.asarray(query_vec, dtype=np.float32).reshape(1, -1)
        norm = float(np.linalg.norm(q))
        if norm == 0:
            return []
        q = q / norm
        k = min(top_n, len(self._chunk_ids))
        if _HAS_FAISS and self._faiss_index is not None:
            scores, indices = self._faiss_index.search(q, k)
            pairs = list(zip(indices[0].tolist(), scores[0].tolist()))
        else:
            sims = (self._matrix @ q[0]).tolist()
            order = np.argsort(sims)[::-1][:k]
            pairs = [(int(i), float(sims[i])) for i in order]
        result: list[tuple[str, str, float]] = []
        for idx, score in pairs:
            if idx < 0:
                continue
            result.append((self._unit_ids[idx], self._chunk_ids[idx], float(score)))
        return result


store = VectorStore()
