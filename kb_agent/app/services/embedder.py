"""文本向量化。

优先使用 sentence-transformers 的 bge-small-zh-v1.5 语义向量；当该依赖/模型不可用时，
自动退回内置的字符 n-gram 哈希向量（确定性强、无需联网、对中文短语检索有效）。
两条路径输出的向量均做 L2 归一化，供内积（=余弦相似度）检索使用。
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading

import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")


class HashingEmbedder:
    """字符 bigram + 词级 unigram 的哈希向量，用于离线/无模型场景。"""

    name = "hashing-ngram"

    def __init__(self, dim: int):
        self.dim = dim

    @staticmethod
    def _tokens(text: str) -> list[str]:
        base = _TOKEN_RE.findall(text.lower())
        grams = list(base)
        for i in range(len(base) - 1):
            grams.append(base[i] + base[i + 1])
        return grams

    def encode(self, texts: list[str]) -> np.ndarray:
        mat = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for tok in self._tokens(text):
                h = int(hashlib.md5(tok.encode("utf-8")).hexdigest()[:8], 16)
                idx = h % self.dim
                sign = 1.0 if (h >> 8) & 1 else -1.0
                mat[row, idx] += sign
            norm = float(np.linalg.norm(mat[row]))
            if norm > 0:
                mat[row] /= norm
        return mat


class SentenceTransformerEmbedder:
    name = "sentence-transformers"

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # 延迟导入，缺失即回退

        self.model = SentenceTransformer(model_name)
        self.dim = int(self.model.get_sentence_embedding_dimension())

    def encode(self, texts: list[str]) -> np.ndarray:
        vecs = self.model.encode(
            texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        )
        return np.asarray(vecs, dtype=np.float32)


_embedder = None
_lock = threading.Lock()


def get_embedder():
    global _embedder
    if _embedder is not None:
        return _embedder
    with _lock:
        if _embedder is not None:
            return _embedder
        provider = (settings.EMBEDDING_PROVIDER or "auto").lower()
        if provider in ("auto", "sentence-transformers", "st", "bge"):
            try:
                _embedder = SentenceTransformerEmbedder(settings.EMBEDDING_MODEL)
                logger.info("向量模型已加载：%s", settings.EMBEDDING_MODEL)
                return _embedder
            except Exception as exc:  # noqa: BLE001 依赖或模型缺失 -> 回退
                logger.warning("sentence-transformers 不可用（%s），回退哈希向量", exc)
        _embedder = HashingEmbedder(settings.EMBEDDING_DIM)
        logger.info("使用内置哈希向量，维度=%s", settings.EMBEDDING_DIM)
        return _embedder


def embed_texts(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, get_embedder().dim), dtype=np.float32)
    return get_embedder().encode(texts)


def embed_query(text: str) -> np.ndarray:
    return embed_texts([text])[0]


def to_bytes(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_bytes(raw: bytes, dim: int) -> np.ndarray:
    vec = np.frombuffer(raw, dtype=np.float32)
    if vec.shape[0] != dim:
        # 维度变化（切换向量后端）时补零/截断，避免整库检索失败
        fixed = np.zeros(dim, dtype=np.float32)
        n = min(dim, vec.shape[0])
        fixed[:n] = vec[:n]
        vec = fixed
    return vec


def current_dim() -> int:
    return get_embedder().dim
