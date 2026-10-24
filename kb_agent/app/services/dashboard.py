"""看板统计与知识缺口聚合。"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import KnowledgeGap, KnowledgeUnit, QaAccessLog

_WS_RE = re.compile(r"\s+")


def metrics(db: Session) -> dict:
    total_access = int(db.query(func.count(QaAccessLog.id)).scalar() or 0)
    uv = int(db.query(func.count(func.distinct(QaAccessLog.user_id))).scalar() or 0)
    unit_total = int(
        db.query(func.count(KnowledgeUnit.id)).filter(KnowledgeUnit.status == "active").scalar() or 0
    )
    total_tokens = int(db.query(func.coalesce(func.sum(QaAccessLog.total_tokens), 0)).scalar() or 0)
    avg_response_ms = float(db.query(func.coalesce(func.avg(QaAccessLog.response_time_ms), 0)).scalar() or 0)

    # FAQ 命中率：按“已发布 FAQ 的规范化问题”精确匹配统计
    from app.models import Faq
    from app.services.faq import normalize_question

    published = {
        normalize_question(f.question)
        for f in db.query(Faq).filter(Faq.status == "published").all()
    }
    cache_hit = 0
    if published and total_access:
        questions = db.query(QaAccessLog.question).all()
        cache_hit = sum(1 for (q,) in questions if normalize_question(q or "") in published)
    hit_rate = round(cache_hit / total_access, 4) if total_access else 0.0
    return {
        "total_access": total_access,
        "uv": uv,
        "unit_total": unit_total,
        "total_tokens": total_tokens,
        "avg_response_ms": round(avg_response_ms, 1),
        "faq_hit_rate": hit_rate,
        "faq_hit_count": cache_hit,
    }


def top_questions(db: Session, limit: int = 10) -> list[dict]:
    from app.services.faq import normalize_question

    logs = db.query(QaAccessLog.question, QaAccessLog.created_at).all()
    counter: Counter[str] = Counter()
    latest: dict[str, str] = {}
    for question, _created in logs:
        key = normalize_question(question)[:20]
        if not key:
            continue
        counter[key] += 1
        latest.setdefault(key, question)
    return [
        {"question": latest[key], "count": count}
        for key, count in counter.most_common(limit)
    ]


def top_units(db: Session, limit: int = 10) -> list[dict]:
    rows = db.query(QaAccessLog.authorized_unit_ids_json).all()
    counter: Counter[str] = Counter()
    for (ids,) in rows:
        for uid in ids or []:
            counter[uid] += 1
    if not counter:
        return []
    units = {
        u.id: u.title
        for u in db.query(KnowledgeUnit).filter(KnowledgeUnit.id.in_(list(counter.keys()))).all()
    }
    return [
        {"unit_id": uid, "title": units.get(uid, "（已删除）"), "count": count}
        for uid, count in counter.most_common(limit)
    ]


def token_stats(db: Session, days: int = 14, granularity: str = "day") -> list[dict]:
    """按日或按周聚合 Token 与耗时。granularity: day | week"""
    since = datetime.now(timezone.utc) - timedelta(days=days - 1)
    rows = (
        db.query(
            QaAccessLog.created_at,
            QaAccessLog.prompt_tokens,
            QaAccessLog.completion_tokens,
            QaAccessLog.total_tokens,
            QaAccessLog.response_time_ms,
        )
        .filter(QaAccessLog.created_at >= since)
        .all()
    )
    buckets: dict[str, dict] = defaultdict(
        lambda: {"date": "", "access_count": 0, "prompt_tokens": 0, "completion_tokens": 0,
                 "total_tokens": 0, "avg_response_ms": 0.0, "_ms": 0}
    )
    for created_at, p_tok, c_tok, t_tok, resp_ms in rows:
        moment = created_at or datetime.now(timezone.utc)
        if granularity == "week":
            iso = moment.isocalendar()
            day = f"{iso[0]}-W{iso[1]:02d}"
        else:
            day = moment.strftime("%Y-%m-%d")
        bucket = buckets[day]
        bucket["date"] = day
        bucket["access_count"] += 1
        bucket["prompt_tokens"] += int(p_tok or 0)
        bucket["completion_tokens"] += int(c_tok or 0)
        bucket["total_tokens"] += int(t_tok or 0)
        bucket["_ms"] += int(resp_ms or 0)
    result = []
    for day in sorted(buckets.keys()):
        bucket = buckets[day]
        if bucket["access_count"]:
            bucket["avg_response_ms"] = round(bucket["_ms"] / bucket["access_count"], 1)
        bucket.pop("_ms", None)
        result.append(bucket)
    return result


def refresh_knowledge_gaps(db: Session) -> list[KnowledgeGap]:
    """recalled 或 authorized 为空的记录 -> 按问题前缀聚类 -> 写入 knowledge_gaps。"""
    logs = (
        db.query(QaAccessLog)
        .order_by(QaAccessLog.created_at.desc())
        .all()
    )
    buckets: dict[str, dict] = {}
    for log in logs:
        if log.recalled_unit_ids_json and log.authorized_unit_ids_json:
            continue
        key = _WS_RE.sub("", log.question or "")[:20]
        if not key:
            continue
        item = buckets.setdefault(
            key, {"count": 0, "samples": [], "last": None, "pattern": (log.question or "").strip()[:120]}
        )
        item["count"] += 1
        if len(item["samples"]) < 5 and log.question not in item["samples"]:
            item["samples"].append(log.question)
        if item["last"] is None or (log.created_at and log.created_at > item["last"]):
            item["last"] = log.created_at

    existing = {g.question_pattern: g for g in db.query(KnowledgeGap).all()}
    for key, item in buckets.items():
        gap = existing.get(key)
        if gap is None:
            gap = KnowledgeGap(
                question_pattern=key,
                sample_questions_json=item["samples"],
                ask_count=item["count"],
                last_asked_at=item["last"],
                status="unresolved",
            )
            db.add(gap)
        else:
            gap.sample_questions_json = item["samples"]
            gap.ask_count = item["count"]
            gap.last_asked_at = item["last"]
    db.commit()

    return (
        db.query(KnowledgeGap)
        .filter(KnowledgeGap.status == "unresolved")
        .order_by(KnowledgeGap.ask_count.desc(), KnowledgeGap.last_asked_at.desc())
        .all()
    )


def gap_to_dict(gap: KnowledgeGap) -> dict:
    return {
        "id": gap.id,
        "question_pattern": gap.question_pattern,
        "sample_questions": gap.sample_questions_json or [],
        "ask_count": gap.ask_count,
        "last_asked_at": gap.last_asked_at.isoformat() if gap.last_asked_at else None,
        "status": gap.status,
        "resolved_unit_id": gap.resolved_unit_id,
        "created_at": gap.created_at.isoformat() if gap.created_at else None,
    }


def response_time_distribution(db: Session, days: int = 14) -> dict:
    """响应时间分布 + 分位值，用于看板的性能分布图。"""
    since = datetime.now(timezone.utc) - timedelta(days=days - 1)
    values = [
        int(row[0] or 0)
        for row in db.query(QaAccessLog.response_time_ms)
        .filter(QaAccessLog.created_at >= since)
        .all()
    ]
    buckets_spec = [
        ("<200ms", 0, 200),
        ("200-500ms", 200, 500),
        ("500-1000ms", 500, 1000),
        ("1-2s", 1000, 2000),
        ("2-5s", 2000, 5000),
        ("≥5s", 5000, None),
    ]
    buckets = []
    for label, low, high in buckets_spec:
        count = sum(1 for v in values if v >= low and (high is None or v < high))
        buckets.append({"label": label, "count": count})

    def percentile(data: list[int], ratio: float) -> float:
        if not data:
            return 0.0
        ordered = sorted(data)
        idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * ratio))))
        return float(ordered[idx])

    return {
        "total": len(values),
        "buckets": buckets,
        "avg_ms": round(sum(values) / len(values), 1) if values else 0.0,
        "p50_ms": percentile(values, 0.5),
        "p95_ms": percentile(values, 0.95),
    }
