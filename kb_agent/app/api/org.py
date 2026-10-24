"""组织与 RBAC：部门（树）/ 角色（权限点）/ 用户（启停用）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_permission
from app.models import Department, Role, RolePermission, User, UserRole
from app.schemas import (
    DepartmentCreateRequest,
    DepartmentUpdateRequest,
    RoleCreateRequest,
    RolePermissionsRequest,
    RoleUpdateRequest,
    UserCreateRequest,
    UserUpdateRequest,
)
from app.services.security import hash_password
from app.utils.response import BizError, ok, page_data
from app.utils.serializers import department_dict, role_dict, user_dict

router = APIRouter(prefix="/org", tags=["组织权限"])

ALLOWED_PERMISSION_CODES = [
    "knowledge:create",
    "knowledge:read",
    "knowledge:update",
    "knowledge:delete",
    "knowledge:import",
    "knowledge:permission",
    "ai:access",
    "dashboard:read",
    "settlement:review",
    "org:manage",
]


# ---------------- 部门 ----------------
@router.get("/departments")
def list_departments(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    rows = db.query(Department).order_by(Department.sort_order, Department.created_at).all()
    member_counts: dict[str, int] = {}
    for (dept_id,) in db.query(User.department_id).filter(User.department_id.isnot(None)).all():
        member_counts[dept_id] = member_counts.get(dept_id, 0) + 1
    leader_names = {u.id: (u.display_name or u.username) for u in db.query(User).all()}
    result = []
    for dept in rows:
        data = department_dict(dept)
        data["member_count"] = member_counts.get(dept.id, 0)
        data["leader_name"] = leader_names.get(dept.leader_id or "", None)
        result.append(data)
    return ok(result)


@router.get("/departments/tree")
def department_tree(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    rows = db.query(Department).order_by(Department.sort_order, Department.created_at).all()
    member_counts: dict[str, int] = {}
    for (dept_id,) in db.query(User.department_id).filter(User.department_id.isnot(None)).all():
        member_counts[dept_id] = member_counts.get(dept_id, 0) + 1
    leader_names = {u.id: (u.display_name or u.username) for u in db.query(User).all()}

    nodes: dict[str, dict] = {}
    for dept in rows:
        nodes[dept.id] = {
            **department_dict(dept),
            "member_count": member_counts.get(dept.id, 0),
            "leader_name": leader_names.get(dept.leader_id or ""),
            "children": [],
        }
    roots: list[dict] = []
    for node in nodes.values():
        parent_id = node.get("parent_id")
        if parent_id and parent_id in nodes:
            nodes[parent_id]["children"].append(node)
        else:
            roots.append(node)
    return ok(roots)


@router.post("/departments")
def create_department(
    payload: DepartmentCreateRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("org:manage")),
):
    if db.query(Department).filter(Department.name == payload.name).first():
        raise BizError("部门名称已存在")
    dept = Department(**payload.model_dump())
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return ok(department_dict(dept), "部门已创建")


@router.put("/departments/{dept_id}")
def update_department(
    dept_id: str,
    payload: DepartmentUpdateRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("org:manage")),
):
    dept = db.get(Department, dept_id)
    if dept is None:
        raise BizError("部门不存在", code=404, status_code=404)
    if payload.name is not None and payload.name != dept.name:
        if db.query(Department).filter(Department.name == payload.name).first():
            raise BizError("部门名称已存在")
        dept.name = payload.name
    if payload.parent_id is not None:
        if payload.parent_id == dept_id:
            raise BizError("上级部门不能是自己")
        cursor = db.get(Department, payload.parent_id) if payload.parent_id else None
        while cursor is not None:  # 防止形成环
            if cursor.id == dept_id:
                raise BizError("不能把部门挂到自己的下级部门下")
            cursor = db.get(Department, cursor.parent_id) if cursor.parent_id else None
        dept.parent_id = payload.parent_id or None
    if payload.leader_id is not None:
        dept.leader_id = payload.leader_id or None
    if payload.sort_order is not None:
        dept.sort_order = payload.sort_order
    db.commit()
    db.refresh(dept)
    return ok(department_dict(dept), "部门已更新")


@router.get("/departments/{dept_id}/members")
def department_members(
    dept_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    if db.get(Department, dept_id) is None:
        raise BizError("部门不存在", code=404, status_code=404)
    rows = db.query(User).filter(User.department_id == dept_id).all()
    return ok([user_dict(db, u) for u in rows])


# ---------------- 角色 ----------------
@router.get("/roles")
def list_roles(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    rows = db.query(Role).order_by(Role.created_at).all()
    return ok([role_dict(r) for r in rows])


@router.post("/roles")
def create_role(
    payload: RoleCreateRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("org:manage")),
):
    if db.query(Role).filter(Role.role_code == payload.role_code).first():
        raise BizError("角色编码已存在")
    unknown = set(payload.permissions) - set(ALLOWED_PERMISSION_CODES)
    if unknown:
        raise BizError(f"未知权限点：{'、'.join(sorted(unknown))}")
    role = Role(
        role_name=payload.role_name,
        role_code=payload.role_code,
        description=payload.description,
    )
    db.add(role)
    db.flush()
    for code in sorted(set(payload.permissions)):
        db.add(RolePermission(role_id=role.id, permission_code=code, permission_type="api"))
    db.commit()
    db.refresh(role)
    return ok(role_dict(role), "角色已创建")


@router.put("/roles/{role_id}")
def update_role(
    role_id: str,
    payload: RoleUpdateRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("org:manage")),
):
    role = db.get(Role, role_id)
    if role is None:
        raise BizError("角色不存在", code=404, status_code=404)
    if payload.role_name is not None:
        role.role_name = payload.role_name
    if payload.description is not None:
        role.description = payload.description
    if payload.permissions is not None:
        _replace_role_permissions(db, role, payload.permissions)
    db.commit()
    db.refresh(role)
    return ok(role_dict(role), "角色已更新")


@router.post("/roles/{role_id}/permissions")
def assign_role_permissions(
    role_id: str,
    payload: RolePermissionsRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("org:manage")),
):
    """角色权限分配（全量覆盖）。"""
    role = db.get(Role, role_id)
    if role is None:
        raise BizError("角色不存在", code=404, status_code=404)
    _replace_role_permissions(db, role, payload.permissions)
    db.commit()
    db.refresh(role)
    return ok(role_dict(role), "权限已分配")


def _replace_role_permissions(db: Session, role: Role, permissions: list[str]) -> None:
    unknown = set(permissions) - set(ALLOWED_PERMISSION_CODES)
    if unknown:
        raise BizError(f"未知权限点：{'、'.join(sorted(unknown))}")
    db.query(RolePermission).filter(RolePermission.role_id == role.id).delete()
    for code in sorted(set(permissions)):
        db.add(RolePermission(role_id=role.id, permission_code=code, permission_type="api"))


@router.get("/permission-codes")
def available_permission_codes(_user: User = Depends(get_current_user)):
    return ok(ALLOWED_PERMISSION_CODES)


# ---------------- 用户 ----------------
@router.get("/users")
def list_users(
    keyword: str | None = Query(default=None),
    department_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("org:manage")),
):
    query = db.query(User)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter((User.username.like(like)) | (User.display_name.like(like)))
    if department_id:
        query = query.filter(User.department_id == department_id)
    if status:
        query = query.filter(User.status == status)
    total = query.count()
    rows = query.order_by(User.created_at).offset((page - 1) * page_size).limit(page_size).all()
    return page_data([user_dict(db, u) for u in rows], total, page, page_size)


@router.post("/users")
def create_user(
    payload: UserCreateRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("org:manage")),
):
    if db.query(User).filter(User.username == payload.username).first():
        raise BizError("用户名已存在")
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name or payload.username,
        department_id=payload.department_id,
        status=payload.status or "active",
    )
    db.add(user)
    db.flush()
    for role_id in payload.role_ids:
        if db.get(Role, role_id):
            db.add(UserRole(user_id=user.id, role_id=role_id))
    db.commit()
    db.refresh(user)
    return ok(user_dict(db, user), "用户已创建")


@router.put("/users/{user_id}")
def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("org:manage")),
):
    user = db.get(User, user_id)
    if user is None:
        raise BizError("用户不存在", code=404, status_code=404)
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.department_id is not None:
        user.department_id = payload.department_id or None
    if payload.status is not None:
        if payload.status not in ("active", "disabled"):
            raise BizError("状态只能是 active 或 disabled")
        user.status = payload.status
    if payload.password:
        user.password_hash = hash_password(payload.password)
    if payload.role_ids is not None:
        db.query(UserRole).filter(UserRole.user_id == user_id).delete()
        for role_id in payload.role_ids:
            if db.get(Role, role_id):
                db.add(UserRole(user_id=user_id, role_id=role_id))
    db.commit()
    db.refresh(user)
    return ok(user_dict(db, user), "用户已更新")


@router.post("/users/{user_id}/password/reset")
def reset_password(
    user_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("org:manage")),
):
    """重置为默认初始密码，提示管理员转告用户及时修改。"""
    user = db.get(User, user_id)
    if user is None:
        raise BizError("用户不存在", code=404, status_code=404)
    default_password = "Kb@123456"
    user.password_hash = hash_password(default_password)
    db.commit()
    return ok({"username": user.username, "password": default_password}, "密码已重置")
