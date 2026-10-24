"""看板：指标 / 常见问题 TOP / 最常访问单元 TOP / Token 趋势。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_permission
from app.models import User
from app.services import dashboard as dashboard_service
from app.utils.response import ok

router = APIRouter(prefix="/dashboard", tags=["看板"])


@router.get("/metrics")
def metrics(
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("dashboard:read")),
):
    return ok(dashboard_service.metrics(db))


@router.get("/rankings/questions")
def ranking_questions(
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("dashboard:read")),
):
    return ok(dashboard_service.top_questions(db, limit))


@router.get("/rankings/units")
def ranking_units(
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("dashboard:read")),
):
    return ok(dashboard_service.top_units(db, limit))


@router.get("/stats/tokens")
def stats_tokens(
    days: int = Query(default=14, ge=1, le=90),
    granularity: str = Query(default="day", pattern="^(day|week)$"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("dashboard:read")),
):
    return ok(dashboard_service.token_stats(db, days, granularity))


@router.get("/stats/response-time")
def stats_response_time(
    days: int = Query(default=14, ge=1, le=90),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("dashboard:read")),
):
    return ok(dashboard_service.response_time_distribution(db, days))
