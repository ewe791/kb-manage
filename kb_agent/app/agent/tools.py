"""管理员 Agent 的工具实现（真实业务调用，无假接口）。

注意：工具参数中不包含 user_id / 操作人身份，一切身份均来自 JWT 注入的 User 对象。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import BASE_DIR
from app.models import Department, Faq, KnowledgeGap, KnowledgeUnit, Role, UnitPermission, User
from app.services import dashboard as dashboard_service
from app.services import faq as faq_service
from app.services import ingest
from app.services.permission_engine import TARGET_TYPES, get_permission_codes, user_has_permission
from app.services.vector_store import store
from app.utils.response import BizError

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "import_knowledge",
            "description": "导入一个或多个本地文档（PDF/Markdown/Word/TXT）为知识单元，支持批量。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "文件路径列表，支持项目内相对路径，例如 seed/docs/财务报销制度.md",
                    },
                    "category": {"type": "string", "description": "知识分类，缺省为“未分类”"},
                },
                "required": ["file_paths"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_units",
            "description": "分页查询知识单元，可按关键词、分类、状态筛选。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "category": {"type": "string"},
                    "status": {"type": "string", "enum": ["active", "archived"]},
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 10},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_unit",
            "description": "查看知识单元详情，包含摘要、正文与已配置的权限列表。",
            "parameters": {
                "type": "object",
                "properties": {"unit_id": {"type": "string"}},
                "required": ["unit_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_unit",
            "description": "更新知识单元的标题、摘要、分类或状态。",
            "parameters": {
                "type": "object",
                "properties": {
                    "unit_id": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "category": {"type": "string"},
                    "status": {"type": "string", "enum": ["active", "archived"]},
                },
                "required": ["unit_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_units",
            "description": "批量删除知识单元（连带切片与权限）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "unit_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["unit_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_unit_permissions",
            "description": (
                "为知识单元配置四维数据权限（全量覆盖）。必须先明确对象类型 "
                "(global/department/role/user) 与具体值（部门名、角色名、用户名）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "unit_id": {"type": "string"},
                    "targets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "target_type": {
                                    "type": "string",
                                    "enum": ["global", "department", "role", "user"],
                                },
                                "target_value": {
                                    "type": "string",
                                    "description": "global 时留空；department 填部门名；role 填角色名/编码；user 填用户名/姓名",
                                },
                            },
                            "required": ["target_type"],
                        },
                    },
                },
                "required": ["unit_id", "targets"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_faq_recommendations",
            "description": "查看待审核的 FAQ 推荐（由高频问答沉淀），按频次降序。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "review_faq",
            "description": "审核 FAQ：approve 发布并写入缓存，reject 驳回。",
            "parameters": {
                "type": "object",
                "properties": {
                    "faq_id": {"type": "string"},
                    "action": {"type": "string", "enum": ["approve", "reject"]},
                    "edited_answer": {"type": "string"},
                },
                "required": ["faq_id", "action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_knowledge_gaps",
            "description": "查看未解决的知识缺口（用户没问出答案的问题），按提问次数降序。",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 10}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dashboard_metrics",
            "description": "获取运营看板核心指标：访问量、UV、知识单元数、Token 总量、平均响应耗时。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def _require(db: Session, user: User, code: str) -> None:
    if not user_has_permission(db, user.id, code):
        raise BizError(f"当前账号缺少权限：{code}", code=403, status_code=403)


def _unit_brief(unit: KnowledgeUnit) -> dict:
    return {
        "unit_id": unit.id,
        "unit_code": unit.unit_code,
        "title": unit.title,
        "category": unit.category,
        "status": unit.status,
        "summary": unit.summary,
        "chunk_count": len(unit.chunks) if unit.chunks is not None else 0,
        "source_file_name": unit.source_file_name,
        "created_at": unit.created_at.isoformat() if unit.created_at else None,
    }


def resolve_target(db: Session, target_type: str, target_value: str | None) -> tuple[str, str | None, str]:
    """把名称解析为 ID，返回 (type, id, 展示名)。"""
    if target_type not in TARGET_TYPES:
        raise BizError(f"未知的授权对象类型：{target_type}")
    if target_type == "global":
        return "global", None, "全体成员"
    value = (target_value or "").strip()
    if not value:
        raise BizError(f"{target_type} 类型必须提供具体值（target_value）")

    if target_type == "department":
        dept = (
            db.query(Department)
            .filter((Department.name == value) | (Department.id == value))
            .first()
        )
        if dept is None:
            names = [d.name for d in db.query(Department).all()]
            raise BizError(f"部门「{value}」不存在，可选：{'、'.join(names) or '无'}")
        return "department", dept.id, dept.name

    if target_type == "role":
        role = (
            db.query(Role)
            .filter((Role.role_name == value) | (Role.role_code == value) | (Role.id == value))
            .first()
        )
        if role is None:
            names = [r.role_name for r in db.query(Role).all()]
            raise BizError(f"角色「{value}」不存在，可选：{'、'.join(names) or '无'}")
        return "role", role.id, role.role_name

    user = (
        db.query(User)
        .filter((User.username == value) | (User.display_name == value) | (User.id == value))
        .first()
    )
    if user is None:
        names = [u.display_name or u.username for u in db.query(User).all()]
        raise BizError(f"用户「{value}」不存在，可选：{'、'.join(names) or '无'}")
    return "user", user.id, user.display_name or user.username


def set_permissions(db: Session, unit_id: str, targets: list[dict]) -> dict:
    unit = db.get(KnowledgeUnit, unit_id)
    if unit is None:
        raise BizError("知识单元不存在", code=404, status_code=404)
    if not targets:
        raise BizError("至少需要一个授权对象")

    resolved: list[tuple[str, str | None, str]] = []
    seen: set[tuple[str, str | None]] = set()
    for item in targets:
        ttype = (item or {}).get("target_type")
        if ttype is None:
            raise BizError("授权对象缺少 target_type")
        triple = resolve_target(db, ttype, (item or {}).get("target_value"))
        if (triple[0], triple[1]) in seen:
            continue
        seen.add((triple[0], triple[1]))
        resolved.append(triple)

    db.query(UnitPermission).filter(UnitPermission.unit_id == unit_id).delete()
    for ttype, tid, _name in resolved:
        db.add(UnitPermission(unit_id=unit_id, target_type=ttype, target_id=tid))
    db.commit()
    return {
        "unit_id": unit_id,
        "title": unit.title,
        "targets": [
            {"target_type": t, "target_id": i, "target_name": n} for t, i, n in resolved
        ],
        "message": "已授权给：" + "、".join(n for _t, _i, n in resolved),
    }


def permission_view(db: Session, unit_id: str) -> list[dict]:
    perms = db.query(UnitPermission).filter(UnitPermission.unit_id == unit_id).all()
    out = []
    for p in perms:
        name = "全体成员"
        if p.target_type == "department" and p.target_id:
            dept = db.get(Department, p.target_id)
            name = dept.name if dept else "（已删除部门）"
        elif p.target_type == "role" and p.target_id:
            role = db.get(Role, p.target_id)
            name = role.role_name if role else "（已删除角色）"
        elif p.target_type == "user" and p.target_id:
            user = db.get(User, p.target_id)
            name = (user.display_name or user.username) if user else "（已删除用户）"
        out.append(
            {"target_type": p.target_type, "target_id": p.target_id, "target_name": name}
        )
    return out


async def dispatch(name: str, args: dict, db: Session, user: User) -> str:
    """执行工具，返回给模型的 JSON 字符串。"""
    args = args or {}

    if name == "import_knowledge":
        _require(db, user, "knowledge:import")
        paths = args.get("file_paths") or ([args["file_path"]] if args.get("file_path") else [])
        if not paths:
            raise BizError("请提供 file_paths")
        results = []
        for raw in paths:
            path = Path(raw)
            if not path.is_absolute():
                path = (BASE_DIR / raw).resolve()
            try:
                path.relative_to(BASE_DIR.resolve())
            except ValueError as exc:
                raise BizError("只允许导入项目目录内的文件") from exc
            results.append(ingest.import_path(db, user.id, str(path), args.get("category") or "未分类"))
        return json.dumps({"imported": results}, ensure_ascii=False)

    if name == "list_units":
        _require(db, user, "knowledge:read")
        query = db.query(KnowledgeUnit)
        if args.get("keyword"):
            like = f"%{args['keyword']}%"
            query = query.filter(
                (KnowledgeUnit.title.like(like)) | (KnowledgeUnit.content.like(like))
            )
        if args.get("category"):
            query = query.filter(KnowledgeUnit.category == args["category"])
        if args.get("status"):
            query = query.filter(KnowledgeUnit.status == args["status"])
        total = query.count()
        page = max(int(args.get("page", 1)), 1)
        size = min(max(int(args.get("page_size", 10)), 1), 50)
        units = (
            query.order_by(KnowledgeUnit.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
            .all()
        )
        return json.dumps(
            {"total": total, "page": page, "page_size": size, "items": [_unit_brief(u) for u in units]},
            ensure_ascii=False,
        )

    if name == "get_unit":
        _require(db, user, "knowledge:read")
        unit = db.get(KnowledgeUnit, args.get("unit_id", ""))
        if unit is None:
            raise BizError("知识单元不存在", code=404, status_code=404)
        data = _unit_brief(unit)
        data["content"] = unit.content
        data["permissions"] = permission_view(db, unit.id)
        return json.dumps(data, ensure_ascii=False)

    if name == "update_unit":
        _require(db, user, "knowledge:update")
        unit = db.get(KnowledgeUnit, args.get("unit_id", ""))
        if unit is None:
            raise BizError("知识单元不存在", code=404, status_code=404)
        for field in ("title", "summary", "category", "status"):
            if args.get(field) is not None:
                setattr(unit, field, args[field])
        db.commit()
        db.refresh(unit)
        return json.dumps({"updated": _unit_brief(unit)}, ensure_ascii=False)

    if name == "delete_units":
        _require(db, user, "knowledge:delete")
        unit_ids = args.get("unit_ids") or []
        deleted = ingest.delete_units(db, unit_ids)
        return json.dumps({"deleted": deleted, "unit_ids": unit_ids}, ensure_ascii=False)

    if name == "set_unit_permissions":
        _require(db, user, "knowledge:permission")
        result = set_permissions(db, args.get("unit_id", ""), args.get("targets") or [])
        return json.dumps(result, ensure_ascii=False)

    if name == "list_faq_recommendations":
        _require(db, user, "settlement:review")
        rows = faq_service.list_recommendations(db, args.get("threshold"))
        return json.dumps(
            {"items": [faq_service.faq_to_dict(f) for f in rows]}, ensure_ascii=False
        )

    if name == "review_faq":
        _require(db, user, "settlement:review")
        faq = db.get(Faq, args.get("faq_id", ""))
        if faq is None:
            raise BizError("FAQ 不存在", code=404, status_code=404)
        action = args.get("action")
        if action not in ("approve", "reject"):
            raise BizError("action 只能是 approve 或 reject")
        faq_service.review_faq(db, faq, action, args.get("edited_answer"), user.id)
        return json.dumps({"faq": faq_service.faq_to_dict(faq)}, ensure_ascii=False)

    if name == "list_knowledge_gaps":
        _require(db, user, "settlement:review")
        gaps = dashboard_service.refresh_knowledge_gaps(db)
        limit = min(max(int(args.get("limit", 10)), 1), 50)
        return json.dumps(
            {"items": [dashboard_service.gap_to_dict(g) for g in gaps[:limit]]}, ensure_ascii=False
        )

    if name == "get_dashboard_metrics":
        _require(db, user, "dashboard:read")
        return json.dumps(dashboard_service.metrics(db), ensure_ascii=False)

    raise BizError(f"未知工具：{name}")
