"""统一的序列化输出。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.agent.tools import permission_view
from app.models import Department, KnowledgeUnit, QaAccessLog, Role, User


def unit_dict(db: Session, unit: KnowledgeUnit, with_content: bool = False) -> dict:
    creator = db.get(User, unit.creator_id) if unit.creator_id else None
    data = {
        "id": unit.id,
        "unit_id": unit.id,
        "unit_code": unit.unit_code,
        "title": unit.title,
        "summary": unit.summary,
        "category": unit.category,
        "source_file_name": unit.source_file_name,
        "file_type": unit.file_type,
        "file_size": unit.file_size,
        "status": unit.status,
        "creator_id": unit.creator_id,
        "creator_name": (creator.display_name or creator.username) if creator else "系统",     
        "chunk_count": len(unit.chunks),
        "permissions": permission_view(db, unit.id),
        "created_at": unit.created_at.isoformat() if unit.created_at else None,
        "updated_at": unit.updated_at.isoformat() if unit.updated_at else None,
    }
    if with_content:
        data["content"] = unit.content
    return data


def user_dict(db: Session, user: User, with_permissions: bool = True) -> dict:
    from app.services.permission_engine import get_permission_codes

    roles = [
        {"id": ur.role.id, "role_name": ur.role.role_name, "role_code": ur.role.role_code}
        for ur in user.user_roles
        if ur.role is not None
    ]
    data = {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "department_id": user.department_id,
        "department_name": user.department.name if user.department else None,
        "status": user.status,
        "roles": roles,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }
    if with_permissions:
        data["permissions"] = get_permission_codes(db, user.id)
    return data


def department_dict(dept: Department) -> dict:
    return {
        "id": dept.id,
        "name": dept.name,
        "parent_id": dept.parent_id,
        "leader_id": dept.leader_id,
        "sort_order": dept.sort_order,
    }


def role_dict(role: Role) -> dict:
    return {
        "id": role.id,
        "role_name": role.role_name,
        "role_code": role.role_code,
        "description": role.description,
        "permissions": [p.permission_code for p in role.permissions],
    }


def log_dict(log: QaAccessLog) -> dict:
    return {
        "id": log.id,
        "session_id": log.session_id,
        "user_id": log.user_id,
        "question": log.question,
        "answer": log.answer,
        "recalled_unit_ids": log.recalled_unit_ids_json,
        "authorized_unit_ids": log.authorized_unit_ids_json,
        "unauthorized_unit_ids": log.unauthorized_unit_ids_json,
        "prompt_tokens": log.prompt_tokens,
        "completion_tokens": log.completion_tokens,
        "total_tokens": log.total_tokens,
        "response_time_ms": log.response_time_ms,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }
