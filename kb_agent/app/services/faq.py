"""FAQ 沉淀与缓存命中。"""
from __future__ import annotations

import hashlib
import re
import threading
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

import numpy as np

from app.config import settings
from app.models import Faq, KnowledgeUnit, QaAccessLog
from app.services.cache import cache
from app.services.embedder import embed_query, embed_texts

_WS_RE = re.compile(r"[\s，。？！、,.?!;；:：\"'“”‘’()（）\[\]【】]+")


def normalize_question(question: str) -> str:
    return _WS_RE.sub("", (question or "").strip().lower())


def question_hash(question: str) -> str:
    return hashlib.sha1(normalize_question(question).encode("utf-8")).hexdigest()


def faq_cache_key(question: str) -> str:
    return f"faq:{question_hash(question)}"


def _faq_allowed(db: Session, user_id: str, unit_id: str | None) -> bool:
    """FAQ 继承其来源知识单元的权限：无权限用户不得命中缓存（否则等于绕过鉴权）。"""
    if not unit_id:
        return True
    from app.services.permission_engine import check_permissions

    result = check_permissions(db, user_id, [unit_id])
    return unit_id in result["authorized_unit_ids"]


def warm_cache(db: Session) -> int:
    """把已发布 FAQ 全部预热进缓存（服务启动时调用）。"""
    rows = db.query(Faq).filter(Faq.status == "published").all()
    for faq in rows:
        cache.set_json(
            faq_cache_key(faq.question),
            {
                "faq_id": faq.id,
                "question": faq.question,
                "answer": faq.answer,
                "unit_id": faq.related_unit_id,
            },
        )
    return len(rows)


def faq_cache_lookup(question: str, db: Session | None = None, user_id: str | None = None) -> dict | None:
    """命中返回 {faq_id, question, answer, unit_id}；未命中或无权限返回 None。"""
    payload = cache.get_json(faq_cache_key(question))
    if payload:
        if db is not None and user_id is not None and not _faq_allowed(db, user_id, payload.get("unit_id")):
            return None
        if db is not None and payload.get("faq_id"):
            db.query(Faq).filter(Faq.id == payload["faq_id"]).update(
                {"hit_count": Faq.hit_count + 1}
            )
            db.commit()
        return payload
    if db is None:
        return None
    # 缓存丢失时回查数据库（规范化后完全一致即视为同一 FAQ）
    target = normalize_question(question)
    for faq in db.query(Faq).filter(Faq.status == "published").all():
        if normalize_question(faq.question) != target:
            continue
        if user_id is not None and not _faq_allowed(db, user_id, faq.related_unit_id):
            return None
        payload = {
            "faq_id": faq.id,
            "question": faq.question,
            "answer": faq.answer,
            "unit_id": faq.related_unit_id,
        }
        cache.set_json(faq_cache_key(faq.question), payload)
        faq.hit_count += 1
        db.commit()
        return payload
    return None


_vec_cache: dict[str, tuple[str, np.ndarray]] = {}
_vec_lock = threading.Lock()


def semantic_faq_lookup(question: str, db: Session, user_id: str,
                        threshold: float | None = None) -> dict | None:
    """精确未命中时的语义相似匹配（FAQ 同样继承来源单元权限）。"""
    threshold = settings.FAQ_SEMANTIC_THRESHOLD if threshold is None else threshold
    rows = db.query(Faq).filter(Faq.status == "published").all()
    if not rows:
        return None

    with _vec_lock:
        missing = [f for f in rows if f.id not in _vec_cache or _vec_cache[f.id][0] != f.updated_at.isoformat()]
        if missing:
            vectors = embed_texts([f.question for f in missing])
            for faq, vec in zip(missing, vectors):
                _vec_cache[faq.id] = (faq.updated_at.isoformat(), vec)
        qv = embed_query(question)
        best_faq, best_sim = None, 0.0
        for faq in rows:
            vec = _vec_cache[faq.id][1]
            sim = float(np.dot(qv, vec))
            if sim > best_sim:
                best_faq, best_sim = faq, sim

    if best_faq is None or best_sim < threshold:
        return None
    if not _faq_allowed(db, user_id, best_faq.related_unit_id):
        return None

    payload = {
        "faq_id": best_faq.id,
        "question": best_faq.question,
        "answer": best_faq.answer,
        "unit_id": best_faq.related_unit_id,
        "similarity": round(best_sim, 4),
    }
    cache.set_json(faq_cache_key(best_faq.question), payload)
    best_faq.hit_count += 1
    db.commit()
    return payload


def publish_cache(faq: Faq) -> None:
    cache.set_json(
        faq_cache_key(faq.question),
        {
            "faq_id": faq.id,
            "question": faq.question,
            "answer": faq.answer,
            "unit_id": faq.related_unit_id,
        },
    )


def invalidate_cache(faq: Faq) -> None:
    cache.delete(faq_cache_key(faq.question))


def mine_faq_recommendations(db: Session, threshold: int | None = None) -> list[Faq]:
    """从问答日志聚合高频相似问题（前 20 字符 + 规范化去重），落地为待审核 FAQ。

    只沉淀「有授权依据且确实答出来」的问答，避免把拒答 / 无权限提示固化成 FAQ。
    """
    from app.services.answer_service import NO_PERMISSION_TEXT, REFUSAL_TEXT

    threshold = settings.FAQ_HIT_THRESHOLD if threshold is None else threshold
    logs = (
        db.query(QaAccessLog)
        .filter(QaAccessLog.answer != "")
        .order_by(QaAccessLog.created_at.desc())
        .all()
    )
    buckets: dict[str, list[QaAccessLog]] = {}
    for log in logs:
        if not log.authorized_unit_ids_json or log.unauthorized_unit_ids_json:
            continue
        answer = (log.answer or "").strip()
        if answer.startswith(NO_PERMISSION_TEXT) or answer.startswith(REFUSAL_TEXT):
            continue
        key = normalize_question(log.question)[:20]
        if not key:
            continue
        buckets.setdefault(key, []).append(log)

    published_keys = {
        normalize_question(f.question)[:20]
        for f in db.query(Faq).filter(Faq.status.in_(["published", "pending_review"])).all()
    }
    result: list[Faq] = []
    for key, rows in buckets.items():
        if len(rows) < threshold:
            continue
        if key in published_keys:
            continue
        latest = rows[0]
        unit_id = (latest.authorized_unit_ids_json or [None])[0]
        unit = db.get(KnowledgeUnit, unit_id) if unit_id else None
        faq = Faq(
            question=latest.question.strip(),
            answer=latest.answer.strip(),
            category=unit.category if unit else "自动沉淀",
            related_unit_id=unit_id,
            source_type="auto_mined",
            status="pending_review",
            hit_count=len(rows),
        )
        db.add(faq)
        result.append(faq)
    db.commit()
    for faq in result:
        db.refresh(faq)
    return result


def review_faq(db: Session, faq: Faq, action: str, edited_answer: str | None, reviewer_id: str) -> Faq:
    if action == "approve":
        faq.status = "published"
        if edited_answer:
            faq.answer = edited_answer
        faq.reviewer_id = reviewer_id
        faq.reviewed_at = datetime.now(timezone.utc)
        db.commit()
        publish_cache(faq)
    elif action == "reject":
        faq.status = "rejected"
        if edited_answer:
            faq.answer = edited_answer
        faq.reviewer_id = reviewer_id
        faq.reviewed_at = datetime.now(timezone.utc)
        db.commit()
        invalidate_cache(faq)
    return faq


def list_recommendations(db: Session, threshold: int | None = None) -> list[Faq]:
    mine_faq_recommendations(db, threshold)
    return (
        db.query(Faq)
        .filter(Faq.status == "pending_review")
        .order_by(Faq.hit_count.desc(), Faq.created_at.desc())
        .all()
    )


def faq_to_dict(faq: Faq) -> dict:
    return {
        "id": faq.id,
        "question": faq.question,
        "answer": faq.answer,
        "category": faq.category,
        "related_unit_id": faq.related_unit_id,
        "source_type": faq.source_type,
        "status": faq.status,
        "hit_count": faq.hit_count,
        "reviewer_id": faq.reviewer_id,
        "reviewed_at": faq.reviewed_at.isoformat() if faq.reviewed_at else None,
        "created_at": faq.created_at.isoformat() if faq.created_at else None,
    }


def unit_title_map(db: Session, unit_ids: list[str]) -> dict[str, str]:
    ids = [u for u in unit_ids if u]
    if not ids:
        return {}
    return {
        u.id: u.title for u in db.query(KnowledgeUnit.id, KnowledgeUnit.title).filter(KnowledgeUnit.id.in_(ids)).all()
    }


def count_published(db: Session) -> int:
    return int(db.query(func.count(Faq.id)).filter(Faq.status == "published").scalar() or 0)
