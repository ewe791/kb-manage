"""问答日志落库（字段齐全，供看板 / FAQ / 缺口复用）。"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import QaAccessLog


def log_qa_access(
    db: Session,
    *,
    user_id: str,
    session_id: str | None,
    question: str,
    answer: str,
    recalled_unit_ids: list[str] | None = None,
    authorized_unit_ids: list[str] | None = None,
    unauthorized_unit_ids: list[str] | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    response_time_ms: int = 0,
) -> QaAccessLog:
    log = QaAccessLog(
        id=str(uuid4()),
        session_id=session_id or f"sess-{uuid4().hex[:12]}",
        user_id=user_id,
        question=question.strip(),
        answer=answer,
        recalled_unit_ids_json=list(recalled_unit_ids or []),
        authorized_unit_ids_json=list(authorized_unit_ids or []),
        unauthorized_unit_ids_json=list(unauthorized_unit_ids or []),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        response_time_ms=response_time_ms,
        created_at=datetime.now(timezone.utc),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def resolve_session_id(session_id: str | None) -> str:
    return session_id or f"sess-{uuid4().hex[:12]}"
