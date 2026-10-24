"""四维权限引擎（K4 核心）。权限判定全部为硬编码，模型无法参与、无法绕过。

规则：
- 默认无权限：知识单元没有任何 unit_permissions 记录 => 未授权
- global / department / role / user 四类实体 OR 逻辑，任一命中即授权
- user_id 只来自 JWT，不接受请求体传入
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import RolePermission, UnitPermission, User, UserRole

TARGET_TYPES = ("global", "department", "role", "user")


def get_user(db: Session, user_id: str) -> User | None:
    return db.get(User, user_id)


def get_role_ids(db: Session, user_id: str) -> set[str]:
    rows = db.query(UserRole.role_id).filter(UserRole.user_id == user_id).all()
    return {r[0] for r in rows}


def get_permission_codes(db: Session, user_id: str) -> list[str]:
    role_ids = get_role_ids(db, user_id)
    if not role_ids:
        return []
    rows = (
        db.query(RolePermission.permission_code)
        .filter(RolePermission.role_id.in_(list(role_ids)))
        .distinct()
        .all()
    )
    return sorted({r[0] for r in rows})


def user_has_permission(db: Session, user_id: str, code: str) -> bool:
    return code in set(get_permission_codes(db, user_id))


def check_permissions(db: Session, user_id: str, unit_ids: list[str]) -> dict:
    """返回 {"authorized_unit_ids": [...], "unauthorized_unit_ids": [...]}。"""
    user = get_user(db, user_id)
    if user is None or user.status != "active":
        # 用户不存在/停用：一律视为无权限，绝不泄露单元是否存在
        return {"authorized_unit_ids": [], "unauthorized_unit_ids": list(dict.fromkeys(unit_ids))}

    user_dept = user.department_id
    user_roles = get_role_ids(db, user_id)

    authorized: list[str] = []
    unauthorized: list[str] = []

    for uid in dict.fromkeys(unit_ids):
        perms = db.query(UnitPermission).filter(UnitPermission.unit_id == uid).all()
        if not perms:
            unauthorized.append(uid)
            continue
        ok = any(
            (p.target_type == "global")
            or (p.target_type == "department" and user_dept is not None and p.target_id == user_dept)
            or (p.target_type == "role" and p.target_id in user_roles)
            or (p.target_type == "user" and p.target_id == user_id)
            for p in perms
        )
        (authorized if ok else unauthorized).append(uid)

    return {"authorized_unit_ids": authorized, "unauthorized_unit_ids": unauthorized}


def filter_authorized_units(db: Session, user_id: str, unit_ids: list[str]) -> list[str]:
    """供检索/看板复用：只返回当前用户有权访问的单元 ID。"""
    return check_permissions(db, user_id, unit_ids)["authorized_unit_ids"]
