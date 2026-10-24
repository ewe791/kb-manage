"""双角色 Agent REST 接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agent.admin_agent import run_admin_agent
from app.agent.user_agent import run_user_agent
from app.database import get_db
from app.deps import require_permission
from app.models import User
from app.schemas import AdminChatRequest, ChatRequest
from app.utils.response import ok

router = APIRouter(prefix="/agent", tags=["Agent"])


@router.post("/admin/chat")
async def admin_chat(
    payload: AdminChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("knowledge:permission")),
):
    result = await run_admin_agent(
        db, user, payload.message, history=payload.history, session_id=payload.session_id
    )
    return ok(result)


@router.post("/user/chat")
async def user_chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("ai:access")),
):
    result = await run_user_agent(db, user, payload.session_id, payload.question)
    return ok(result)
