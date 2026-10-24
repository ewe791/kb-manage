"""AI 鉴权问答：SSE 流式接口 + 非流式接口。"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agent.user_agent import run_user_agent, stream_user_agent
from app.database import get_db
from app.deps import require_permission
from app.models import KnowledgeUnit, QaAccessLog, User
from app.schemas import ChatRequest
from app.utils.response import BizError, ok

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["AI 问答"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("ai:access")),
):
    async def generator():
        try:
            async for item in stream_user_agent(db, user, payload.session_id, payload.question):
                yield _sse(item["event"], item["data"])
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("流式问答失败")
            yield _sse("error", {"message": f"生成失败：{exc}"})
            yield _sse("done", {"session_id": payload.session_id, "cached": False})

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("ai:access")),
):
    result = await run_user_agent(db, user, payload.session_id, payload.question)
    return ok(result)


@router.get("/sessions")
def list_sessions(
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("ai:access")),
):
    """当前用户的历史会话列表（从问答日志聚合，仅可见自己的记录）。"""
    logs = (
        db.query(QaAccessLog)
        .filter(QaAccessLog.user_id == user.id)
        .order_by(QaAccessLog.created_at.desc())
        .limit(300)
        .all()
    )
    sessions: dict[str, dict] = {}
    for log in reversed(logs):
        key = log.session_id
        item = sessions.get(key)
        if item is None:
            sessions[key] = {
                "session_id": key,
                "title": (log.question or "新会话")[:40],
                "message_count": 1,
                "last_at": log.created_at.isoformat() if log.created_at else None,
                "last_question": log.question,
            }
        else:
            item["message_count"] += 1
            item["last_at"] = log.created_at.isoformat() if log.created_at else item["last_at"]
            item["last_question"] = log.question
    ordered = sorted(sessions.values(), key=lambda x: x.get("last_at") or "", reverse=True)
    return ok(ordered[:limit])


@router.get("/sessions/{session_id}/messages")
def session_messages(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("ai:access")),
):
    logs = (
        db.query(QaAccessLog)
        .filter(QaAccessLog.session_id == session_id, QaAccessLog.user_id == user.id)
        .order_by(QaAccessLog.created_at)
        .all()
    )
    if not logs:
        raise BizError("会话不存在或无权查看", code=404, status_code=404)
    unit_ids = {uid for log in logs for uid in (log.authorized_unit_ids_json or [])}
    titles = {
        u.id: u.title
        for u in db.query(KnowledgeUnit).filter(KnowledgeUnit.id.in_(list(unit_ids))).all()
    } if unit_ids else {}
    return ok(
        {
            "session_id": session_id,
            "messages": [
                {
                    "question": log.question,
                    "answer": log.answer,
                    "created_at": log.created_at.isoformat() if log.created_at else None,
                    "citations": [
                        {"unit_id": uid, "title": titles.get(uid, "（已删除）")}
                        for uid in (log.authorized_unit_ids_json or [])
                    ],
                    "unauthorized_count": len(log.unauthorized_unit_ids_json or []),
                }
                for log in logs
            ],
        }
    )
