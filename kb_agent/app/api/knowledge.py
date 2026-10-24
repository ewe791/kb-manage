"""知识单元：导入 / 查询 / 更新 / 批量删除 / 权限配置 / 权限校验。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_permission
from app.models import KnowledgeUnit, UnitPermission, User
from app.schemas import (
    CheckPermissionsRequest,
    DeleteUnitsRequest,
    UnitPermissionsRequest,
    UnitUpdateRequest,
)
from app.agent.tools import permission_view, resolve_target
from app.services import ingest
from app.services.permission_engine import check_permissions, get_permission_codes
from app.utils.response import BizError, ok, page_data
from app.utils.serializers import unit_dict

router = APIRouter(prefix="/knowledge", tags=["知识单元"])


@router.post("/import")
async def import_knowledge(
    files: list[UploadFile] = File(...),
    category: str = Form(default="未分类"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("knowledge:import")),
):
    if not files:
        raise BizError("请至少选择一个文件")
    results = []
    for file in files:
        data = await file.read()
        results.append(
            ingest.import_bytes(db, user.id, file.filename or "未命名文件", data, category=category)
        )
    success = sum(1 for r in results if r["status"] == "success")
    return ok({"items": results, "success_count": success, "total": len(results)}, "导入完成")


@router.get("/units")
def list_units(
    keyword: str | None = Query(default=None),
    title: str | None = Query(default=None),
    category: str | None = Query(default=None),
    file_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("knowledge:read")),
):
    query = db.query(KnowledgeUnit)
    kw = keyword or title
    if kw:
        like = f"%{kw}%"
        query = query.filter((KnowledgeUnit.title.like(like)) | (KnowledgeUnit.content.like(like)))
    if category:
        query = query.filter(KnowledgeUnit.category == category)
    if file_type:
        query = query.filter(KnowledgeUnit.file_type == file_type)
    if status:
        query = query.filter(KnowledgeUnit.status == status)
    total = query.count()
    rows = (
        query.order_by(KnowledgeUnit.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return page_data([unit_dict(db, u) for u in rows], total, page, page_size)


@router.get("/units/{unit_id}")
def get_unit(
    unit_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("knowledge:read")),
):
    unit = db.get(KnowledgeUnit, unit_id)
    if unit is None:
        raise BizError("知识单元不存在", code=404, status_code=404)
    return ok(unit_dict(db, unit, with_content=True))


@router.put("/units/{unit_id}")
def update_unit(
    unit_id: str,
    payload: UnitUpdateRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("knowledge:update")),
):
    unit = db.get(KnowledgeUnit, unit_id)
    if unit is None:
        raise BizError("知识单元不存在", code=404, status_code=404)
    for field in ("title", "summary", "category", "status"):
        value = getattr(payload, field)
        if value is not None:
            setattr(unit, field, value)
    db.commit()
    if payload.content is not None:
        # 正文变更后同步重建切片与向量索引
        from app.services.ingest import reindex_unit

        reindex_unit(db, unit, payload.content)
    db.refresh(unit)
    return ok(unit_dict(db, unit, with_content=True), "已保存")


@router.post("/units/{unit_id}/permissions")
def set_unit_permissions(
    unit_id: str,
    payload: UnitPermissionsRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("knowledge:permission")),
):
    unit = db.get(KnowledgeUnit, unit_id)
    if unit is None:
        raise BizError("知识单元不存在", code=404, status_code=404)
    if not payload.targets:
        raise BizError("至少需要一个授权对象")

    resolved: list[tuple[str, str | None, str]] = []
    seen: set[tuple[str, str | None]] = set()
    for target in payload.targets:
        triple = resolve_target(db, target.target_type, target.target_id)
        key = (triple[0], triple[1])
        if key in seen:
            continue
        seen.add(key)
        resolved.append(triple)

    db.query(UnitPermission).filter(UnitPermission.unit_id == unit_id).delete()
    for ttype, tid, _name in resolved:
        db.add(UnitPermission(unit_id=unit_id, target_type=ttype, target_id=tid))
    db.commit()

    return ok(
        {
            "unit_id": unit_id,
            "targets": [
                {"target_type": t, "target_id": i, "target_name": n} for t, i, n in resolved
            ],
            "permissions": permission_view(db, unit_id),
        },
        "权限已更新",
    )


@router.delete("/units")
def delete_units(
    payload: DeleteUnitsRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("knowledge:delete")),
):
    if not payload.unit_ids:
        raise BizError("请选择要删除的知识单元")
    deleted = ingest.delete_units(db, payload.unit_ids)
    return ok({"deleted": deleted}, f"已删除 {deleted} 个知识单元")


@router.post("/check-permissions")
def check_permissions_api(
    payload: CheckPermissionsRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    codes = set(get_permission_codes(db, user.id))
    if not ({"ai:access", "knowledge:read"} & codes):
        raise BizError("缺少权限：ai:access", code=403, status_code=403)
    # user_id 只从 JWT 注入，请求体不接收
    result = check_permissions(db, user.id, payload.unit_ids)
    return ok(result)
