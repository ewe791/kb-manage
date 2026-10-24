"""用户问答 Agent：固定编排，权限校验硬编码在代码里。

模型只负责「基于授权片段生成回答」，它甚至不知道 check_permissions 的存在：
- 没有把 check_permissions 暴露成 tool
- Prompt 中不包含任何权限字段、user_id
- 未授权单元的内容不会进入 Prompt，也不会以摘要形式出现
"""
from __future__ import annotations

import time
from collections.abc import AsyncIterator

from sqlalchemy.orm import Session

from app.config import settings
from app.models import KnowledgeUnit, User
from app.services import answer_service, faq as faq_service
from app.services.log_service import log_qa_access, resolve_session_id
from app.services.permission_engine import check_permissions
from app.services.retrieval import fetch_unit_context, retrieve_units

PERMISSION_WARNING_TEMPLATE = "\n\n（另有 {count} 条相关知识您暂无访问权限）"


def _hydrate(db: Session, candidates: list[dict]) -> list[dict]:
    """把命中片段补全为完整上下文（仅对已授权单元调用）。"""
    contexts = fetch_unit_context([c["unit_id"] for c in candidates], db)
    hydrated: list[dict] = []
    for cand in candidates:
        unit = contexts.get(cand["unit_id"])
        if unit is None:
            continue
        hydrated.append({**cand, "title": unit["title"], "content": unit["content"]})
    return hydrated


def _log(
    db: Session,
    user_id: str,
    session_id: str,
    question: str,
    answer: str,
    recalled_unit_ids: list[str],
    perm: dict,
    started: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
) -> None:
    log_qa_access(
        db,
        user_id=user_id,
        session_id=session_id,
        question=question,
        answer=answer,
        recalled_unit_ids=recalled_unit_ids,
        authorized_unit_ids=perm["authorized_unit_ids"],
        unauthorized_unit_ids=perm["unauthorized_unit_ids"],
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        response_time_ms=int((time.perf_counter() - started) * 1000),
    )


async def run_user_agent(
    db: Session,
    user: User,
    session_id: str | None,
    question: str,
) -> dict:
    started = time.perf_counter()
    sid = resolve_session_id(session_id)
    user_id = user.id  # 只来自 JWT

    # 第 1 步：FAQ 缓存（命中亦需通过来源单元权限校验）
    cached = faq_service.faq_cache_lookup(question, db, user_id=user_id)
    if cached is None:
        # 精确未命中时尝试语义相似 FAQ（仍需通过来源单元的权限校验）
        cached = faq_service.semantic_faq_lookup(question, db, user_id)
    if cached:
        allowed_unit = [cached["unit_id"]] if cached.get("unit_id") else []
        _log(db, user_id, sid, question, cached["answer"], allowed_unit,
             {"authorized_unit_ids": allowed_unit, "unauthorized_unit_ids": []}, started)
        return {
            "answer": cached["answer"],
            "citations": [],
            "unauthorized_count": 0,
            "cached": True,
            "session_id": sid,
            "response_time_ms": int((time.perf_counter() - started) * 1000),
        }

    # 第 2 步：检索（模型不参与）
    candidates = retrieve_units(question, top_k=settings.RETRIEVE_TOP_K, db=db)

    # 第 3 步：权限校验（模型不参与，硬编码）
    perm = check_permissions(db, user_id, [c["unit_id"] for c in candidates])
    authorized_candidates = [c for c in candidates if c["unit_id"] in perm["authorized_unit_ids"]]
    unauthorized = [c for c in candidates if c["unit_id"] in perm["unauthorized_unit_ids"]]

    # 第 4 步：仅用授权单元生成回答
    authorized_units = _hydrate(db, authorized_candidates)
    result = await answer_service.answer_with_context(question, authorized_units)

    # 第 5 步：拼缺失提示
    if unauthorized:
        result["answer"] += PERMISSION_WARNING_TEMPLATE.format(count=len(unauthorized))

    # 第 6 步：日志
    _log(
        db, user_id, sid, question, result["answer"],
        [c["unit_id"] for c in candidates], perm, started,
        result.get("prompt_tokens", 0), result.get("completion_tokens", 0), result.get("total_tokens", 0),
    )

    return {
        "answer": result["answer"],
        "citations": result["citations"],
        "unauthorized_count": len(unauthorized),
        "cached": False,
        "session_id": sid,
        "response_time_ms": int((time.perf_counter() - started) * 1000),
    }


async def stream_user_agent(
    db: Session,
    user: User,
    session_id: str | None,
    question: str,
) -> AsyncIterator[dict]:
    """SSE 版本，事件顺序：FAQ(可选) -> message_delta* -> permission_warning -> citations -> done。"""
    started = time.perf_counter()
    sid = resolve_session_id(session_id)
    user_id = user.id

    cached = faq_service.faq_cache_lookup(question, db, user_id=user_id)
    if cached is None:
        cached = faq_service.semantic_faq_lookup(question, db, user_id)
    if cached:
        yield {"event": "message_delta", "data": {"delta_text": cached["answer"]}}
        yield {"event": "citations", "data": {"citations": []}}
        yield {"event": "done", "data": {"session_id": sid, "cached": True,
                                        "response_time_ms": int((time.perf_counter() - started) * 1000)}}
        allowed_unit = [cached["unit_id"]] if cached.get("unit_id") else []
        _log(db, user_id, sid, question, cached["answer"], allowed_unit,
             {"authorized_unit_ids": allowed_unit, "unauthorized_unit_ids": []}, started)
        return

    candidates = retrieve_units(question, top_k=settings.RETRIEVE_TOP_K, db=db)
    perm = check_permissions(db, user_id, [c["unit_id"] for c in candidates])
    authorized_candidates = [c for c in candidates if c["unit_id"] in perm["authorized_unit_ids"]]
    unauthorized = [c for c in candidates if c["unit_id"] in perm["unauthorized_unit_ids"]]
    authorized_units = _hydrate(db, authorized_candidates)

    final: dict = {"answer": "", "citations": [], "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    async for item in answer_service.stream_answer_with_context(question, authorized_units):
        if item["type"] == "delta":
            yield {"event": "message_delta", "data": {"delta_text": item["text"]}}
        else:
            final = item

    answer = final["answer"]
    if unauthorized:
        warning = PERMISSION_WARNING_TEMPLATE.format(count=len(unauthorized))
        answer += warning
        yield {"event": "message_delta", "data": {"delta_text": warning}}

    yield {"event": "citations", "data": {"citations": final["citations"]}}
    if unauthorized:
        yield {"event": "permission_warning", "data": {"unauthorized_count": len(unauthorized)}}
    yield {
        "event": "done",
        "data": {
            "session_id": sid,
            "cached": False,
            "response_time_ms": int((time.perf_counter() - started) * 1000),
        },
    }

    _log(
        db, user_id, sid, question, answer,
        [c["unit_id"] for c in candidates], perm, started,
        final.get("prompt_tokens", 0), final.get("completion_tokens", 0), final.get("total_tokens", 0),
    )


def unit_brief(unit: KnowledgeUnit) -> dict:
    return {
        "unit_id": unit.id,
        "title": unit.title,
        "category": unit.category,
        "summary": unit.summary,
        "status": unit.status,
    }
