"""沉淀：FAQ 推荐 / 审核发布 / 知识缺口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_permission
from app.agent.tools import resolve_target
from app.models import Faq, KnowledgeGap, KnowledgeUnit, UnitPermission, User
from app.schemas import FaqReviewRequest, GapCreateUnitRequest
from app.services import dashboard as dashboard_service
from app.services import faq as faq_service
from app.services.cache import cache
from app.services.ingest import create_unit_from_text
from app.utils.response import BizError, ok, page_data
from app.utils.serializers import log_dict, unit_dict

router = APIRouter(prefix="/settlement", tags=["沉淀"])


@router.get("/faqs")
def list_faqs(
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("settlement:review")),
):
    query = db.query(Faq)
    if status:
        query = query.filter(Faq.status == status)
    total = query.count()
    rows = (
        query.order_by(Faq.hit_count.desc(), Faq.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    titles = faq_service.unit_title_map(db, [f.related_unit_id or "" for f in rows])
    items = []
    for faq in rows:
        data = faq_service.faq_to_dict(faq)
        data["related_unit_title"] = titles.get(faq.related_unit_id or "", None)
        data["cache_active"] = bool(
            faq.status == "published" and cache.get_json(faq_service.faq_cache_key(faq.question))
        )
        items.append(data)
    return page_data(items, total, page, page_size)


@router.get("/faqs/recommendations")
def faq_recommendations(
    threshold: int | None = Query(default=None, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("settlement:review")),
):
    rows = faq_service.list_recommendations(db, threshold)
    titles = faq_service.unit_title_map(db, [f.related_unit_id or "" for f in rows])
    items = []
    for faq in rows:
        data = faq_service.faq_to_dict(faq)
        data["related_unit_title"] = titles.get(faq.related_unit_id or "", None)
        items.append(data)
    return ok(items)


@router.post("/faqs/{faq_id}/review")
def review_faq(
    faq_id: str,
    payload: FaqReviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("settlement:review")),
):
    faq = db.get(Faq, faq_id)
    if faq is None:
        raise BizError("FAQ 不存在", code=404, status_code=404)
    faq_service.review_faq(db, faq, payload.action, payload.edited_answer, user.id)
    data = faq_service.faq_to_dict(faq)
    return ok(data, "已发布并写入缓存" if payload.action == "approve" else "已驳回")


@router.get("/knowledge-gaps")
def knowledge_gaps(
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("settlement:review")),
):
    gaps = dashboard_service.refresh_knowledge_gaps(db)
    return ok([dashboard_service.gap_to_dict(g) for g in gaps])


@router.post("/knowledge-gaps/{gap_id}/resolve")
def resolve_gap(
    gap_id: str,
    unit_id: str = Query(...),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("settlement:review")),
):
    gap = db.get(KnowledgeGap, gap_id)
    if gap is None:
        raise BizError("知识缺口不存在", code=404, status_code=404)
    if db.get(KnowledgeUnit, unit_id) is None:
        raise BizError("知识单元不存在", code=404, status_code=404)
    gap.status = "resolved"
    gap.resolved_unit_id = unit_id
    db.commit()
    return ok(dashboard_service.gap_to_dict(gap), "已标记为已解决")


@router.post("/knowledge-gaps/{gap_id}/create-unit")
def create_unit_for_gap(
    gap_id: str,
    payload: GapCreateUnitRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("settlement:review")),
):
    """知识缺口一键建档：新建知识单元、配置权限并把缺口标记为已解决。"""
    gap = db.get(KnowledgeGap, gap_id)
    if gap is None:
        raise BizError("知识缺口不存在", code=404, status_code=404)

    result = create_unit_from_text(
        db,
        user.id,
        title=payload.title,
        content=payload.content,
        category=payload.category,
        summary=payload.summary,
        source_file_name="知识缺口补全",
        file_type="md",
    )
    unit = db.get(KnowledgeUnit, result["unit_id"])
    if unit is None:
        raise BizError("知识单元创建失败", code=500, status_code=500)

    if payload.targets:
        resolved: list[tuple[str, str | None]] = []
        seen: set[tuple[str, str | None]] = set()
        for target in payload.targets:
            triple = resolve_target(db, target.target_type, target.target_id)
            if (triple[0], triple[1]) in seen:
                continue
            seen.add((triple[0], triple[1]))
            resolved.append((triple[0], triple[1]))
        db.query(UnitPermission).filter(UnitPermission.unit_id == unit.id).delete()
        for ttype, tid in resolved:
            db.add(UnitPermission(unit_id=unit.id, target_type=ttype, target_id=tid))

    gap.status = "resolved"
    gap.resolved_unit_id = unit.id
    db.commit()
    db.refresh(unit)
    db.refresh(gap)
    return ok(
        {"unit": unit_dict(db, unit), "gap": dashboard_service.gap_to_dict(gap)},
        "知识单元已创建，缺口已标记解决",
    )


@router.get("/logs")
def recent_logs(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("settlement:review")),
):
    from app.models import QaAccessLog

    rows = db.query(QaAccessLog).order_by(QaAccessLog.created_at.desc()).limit(limit).all()
    return ok([log_dict(r) for r in rows])
