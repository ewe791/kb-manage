"""演示数据初始化。

执行：python -m seed.init_seed  [--reset]
内容：部门 / 角色 / 用户 -> 导入示例文档 -> 财务制度配权限（部门=财务部 + 角色=财务专员）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import Department, KnowledgeChunk, KnowledgeUnit, Role, RolePermission, UnitPermission, User, UserRole  # noqa: E402
from app.services.ingest import import_path  # noqa: E402
from app.services.security import hash_password  # noqa: E402

SEED_DIR = BASE / "seed"


def reset_tables() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    print("已清空并重建全部数据表")


def ensure_base() -> None:
    Base.metadata.create_all(bind=engine)


def load_config() -> dict:
    return json.loads((SEED_DIR / "users.json").read_text(encoding="utf-8"))


def seed_org(db) -> dict:
    cfg = load_config()
    depts: dict[str, Department] = {}
    for item in cfg["departments"]:
        dept = db.query(Department).filter(Department.name == item["name"]).first()
        if dept is None:
            dept = Department(name=item["name"], sort_order=item.get("sort_order", 0))
            db.add(dept)
            db.flush()
        depts[dept.name] = dept

    roles: dict[str, Role] = {}
    for item in cfg["roles"]:
        role = db.query(Role).filter(Role.role_code == item["role_code"]).first()
        if role is None:
            role = Role(
                role_name=item["role_name"],
                role_code=item["role_code"],
                description=item.get("description", ""),
            )
            db.add(role)
            db.flush()
            for code in item.get("permissions", []):
                db.add(RolePermission(role_id=role.id, permission_code=code, permission_type="api"))
        roles[role.role_code] = role

    users: dict[str, User] = {}
    for item in cfg["users"]:
        user = db.query(User).filter(User.username == item["username"]).first()
        if user is None:
            user = User(
                username=item["username"],
                password_hash=hash_password(item["password"]),
                display_name=item.get("display_name", item["username"]),
                department_id=depts[item["department"]].id if item.get("department") in depts else None,
                status="active",
            )
            db.add(user)
            db.flush()
            for code in item.get("roles", []):
                if code in roles:
                    db.add(UserRole(user_id=user.id, role_id=roles[code].id))
        users[user.username] = user

    # 部门负责人（演示：财务部负责人 = 张三）
    if users.get("zhangsan") and "财务部" in depts:
        depts["财务部"].leader_id = users["zhangsan"].id
    db.commit()
    return {"departments": depts, "roles": roles, "users": users}


def seed_docs(db, ctx: dict) -> dict[str, KnowledgeUnit]:
    admin = ctx["users"]["admin"]
    mapping = {
        "财务报销制度.md": "财务制度",
        "产品使用手册.md": "产品文档",
        "HR考勤政策.md": "人力资源",
    }
    units: dict[str, KnowledgeUnit] = {}
    for filename, category in mapping.items():
        path = SEED_DIR / "docs" / filename
        existing = (
            db.query(KnowledgeUnit)
            .filter(KnowledgeUnit.source_file_name == filename)
            .first()
        )
        if existing is not None:
            units[filename] = existing
            continue
        result = import_path(db, admin.id, str(path), category=category)
        if result.get("unit_id"):
            units[filename] = db.get(KnowledgeUnit, result["unit_id"])
            print(f"  已导入 {filename}：{result['chunk_count']} 个切片")
        else:
            print(f"  导入失败 {filename}：{result.get('status')}")
    return units


def seed_permissions(db, ctx: dict, units: dict[str, KnowledgeUnit]) -> None:
    finance_dept = ctx["departments"]["财务部"]
    finance_role = ctx["roles"]["finance_specialist"]
    hr_dept = ctx["departments"]["人力资源部"]
    employee_role = ctx["roles"]["employee"]

    def apply(unit: KnowledgeUnit, targets: list[tuple[str, str | None]]):
        db.query(UnitPermission).filter(UnitPermission.unit_id == unit.id).delete()
        for ttype, tid in targets:
            db.add(UnitPermission(unit_id=unit.id, target_type=ttype, target_id=tid))
        db.commit()

    finance = units.get("财务报销制度.md")
    if finance:
        # 演示核心：只给财务部 + 财务专员角色
        apply(finance, [("department", finance_dept.id), ("role", finance_role.id)])
        print("  财务报销制度 -> 部门[财务部] + 角色[财务专员]")

    handbook = units.get("产品使用手册.md")
    if handbook:
        apply(handbook, [("global", None)])
        print("  产品使用手册 -> 全局")

    hr = units.get("HR考勤政策.md")
    if hr:
        apply(hr, [("department", hr_dept.id), ("role", employee_role.id)])
        print("  HR考勤政策 -> 部门[人力资源部] + 角色[普通员工]")


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化知识库 Agent 演示数据")
    parser.add_argument("--reset", action="store_true", help="清空所有数据后重建")
    args = parser.parse_args()

    if args.reset:
        reset_tables()
    else:
        ensure_base()

    db = SessionLocal()
    try:
        print("[1/3] 初始化组织与权限 …")
        ctx = seed_org(db)
        print(f"  部门 {len(ctx['departments'])} 个 / 角色 {len(ctx['roles'])} 个 / 用户 {len(ctx['users'])} 个")
        print("[2/3] 导入示例文档并切片向量化 …")
        units = seed_docs(db, ctx)
        print("[3/3] 配置四维数据权限 …")
        seed_permissions(db, ctx, units)
        total_chunks = db.query(KnowledgeChunk).count()
        print(f"完成：知识单元 {db.query(KnowledgeUnit).count()} 个，切片 {total_chunks} 个")
        print("\n演示账号：")
        print("  admin    / Admin@123   系统管理员（全部权限）")
        print("  zhangsan / Zs@123456   财务部·财务专员（可看财务制度）")
        print("  lisi     / Ls@123456   市场部·普通员工（不可看财务制度）")
        print("  wangwu   / Ww@123456   人力资源部·普通员工")
    finally:
        db.close()


if __name__ == "__main__":
    main()
