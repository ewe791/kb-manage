"""AI 鉴权检索第 1 步：召回（不含任何权限判断）。"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import KnowledgeChunk, KnowledgeUnit
from app.services.embedder import embed_query
from app.services.vector_store import store


_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")


def _grams(text: str) -> set[str]:
    """字符 unigram + bigram，用于中文关键词重合度计算。"""
    tokens = _TOKEN_RE.findall((text or "").lower())
    grams = set(tokens)
    grams.update(tokens[i] + tokens[i + 1] for i in range(len(tokens) - 1))
    return grams


def keyword_score(question: str, text: str) -> float:
    """问题关键词在片段中的覆盖率（0~1）。"""
    q = _grams(question)
    if not q:
        return 0.0
    doc = _grams(text)
    return len(q & doc) / len(q)


def _snippet(text: str, limit: int = 260) -> str:
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else clean[:limit] + "…"


def retrieve_units(question: str, top_k: int = 5, db: Session | None = None) -> list[dict]:
    """bge 编码 -> FAISS 检索 -> 按 unit_id 去重保留最高分片段。"""
    own_session = db is None
    session = db or SessionLocal()
    try:
        query_vec = embed_query(question)
        hits = store.search(session, query_vec, top_n=max(top_k * 4, 12))
        best: dict[str, dict] = {}
        for unit_id, chunk_id, score in hits:
            if unit_id in best and best[unit_id]["score"] >= score:
                continue
            chunk = session.get(KnowledgeChunk, chunk_id)
            unit = session.get(KnowledgeUnit, unit_id)
            if chunk is None or unit is None or unit.status != "active":
                continue
            # 混合召回：向量相似度 + 关键词覆盖率（向量 0.7 / 关键词 0.3）
            kw = keyword_score(question, chunk.chunk_text)
            hybrid = 0.7 * float(score) + 0.3 * kw
            if unit_id in best and best[unit_id]["score"] >= hybrid:
                continue
            best[unit_id] = {
                "unit_id": unit_id,
                "title": unit.title,
                "snippet": _snippet(chunk.chunk_text),
                "score": round(hybrid, 6),
                "vector_score": round(float(score), 6),
                "keyword_score": round(kw, 6),
                "chunk_id": chunk_id,
            }
        ranked = sorted(best.values(), key=lambda x: x["score"], reverse=True)
        if ranked:
            best_score = ranked[0]["score"]
            ranked = [
                item
                for item in ranked
                if item["score"] >= settings.MIN_RELEVANCE
                and item["score"] >= best_score * settings.MIN_RELATIVE_SCORE
            ]
        return ranked[:top_k]
    finally:
        if own_session:
            session.close()


def fetch_unit_context(unit_ids: list[str], db: Session) -> dict[str, dict]:
    """按 unit_id 取标题与正文（仅限已授权单元，由编排层传入）。"""
    if not unit_ids:
        return {}
    units = db.query(KnowledgeUnit).filter(KnowledgeUnit.id.in_(unit_ids)).all()
    return {
        u.id: {"unit_id": u.id, "title": u.title, "content": u.content, "category": u.category}
        for u in units
    }


def default_top_k() -> int:
    return settings.RETRIEVE_TOP_K
