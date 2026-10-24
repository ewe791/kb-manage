"""评测夹具（K-E1 / K-E2 共用）。

数据严格按《项目二_知识库Agent_评测》文档 1 节与 2 节构造：
  部门：d_fin(财务部)、d_mkt(市场部)、d_hr(HR部)
  角色：r_fin(财务专员)、r_mkt(市场专员)、r_hr(HR专员)
  用户：u_zhang(dept=d_fin, role=r_fin)、u_li(dept=d_mkt, role=r_mkt)、u_wang(dept=d_hr, role=r_hr)
  单元：unit_global / unit_fin / unit_role / unit_user / unit_mixed / unit_none / unit_multi
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{BASE / 'data' / 'test.db'}")

from app.database import Base  # noqa: E402
from app.models import (  # noqa: E402
    Department,
    KnowledgeChunk,
    KnowledgeUnit,
    Role,
    UnitPermission,
    User,
    UserRole,
)
from app.services.security import hash_password  # noqa: E402

SEED_DOCS = BASE / "seed" / "docs"

# unit_fin 的敏感内容，用于端到端泄露判定
SENSITIVE_TEXT = "住宿标准 800 元"


_RESULTS: dict[str, dict] = {}


def pytest_runtest_logreport(report):  # pragma: no cover - 仅统计用
    """按测试文件累计通过/失败数，供评测报告使用。"""
    if report.when != "call":
        if report.when == "setup" and report.skipped and hasattr(report, "fspath"):
            bucket = _RESULTS.setdefault(Path(str(report.fspath)).name, {"passed": 0, "failed": 0, "skipped": 0})
            bucket["skipped"] += 1
        return
    bucket = _RESULTS.setdefault(Path(str(report.fspath)).name, {"passed": 0, "failed": 0, "skipped": 0})
    if report.passed:
        bucket["passed"] += 1
    elif report.failed:
        bucket["failed"] += 1


def pytest_sessionfinish(session, exitstatus):  # pragma: no cover - 仅用于落盘
    """会话结束时把「用例通过情况 + 数值指标」写入 reports/eval_metrics.json。"""
    import json
    from datetime import datetime

    metrics_path = BASE / "reports" / "eval_metrics.json"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from tests.metrics_store import snapshot

        payload = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "suites": {k: dict(v) for k, v in sorted(_RESULTS.items())},
            "metrics": snapshot(),
        }
        metrics_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _add_unit(db, code: str, title: str, content: str) -> KnowledgeUnit:
    unit = KnowledgeUnit(unit_code=code, title=title, content=content, summary=content[:80])
    db.add(unit)
    db.flush()
    db.add(KnowledgeChunk(unit_id=unit.id, chunk_index=0, chunk_text=content))
    db.flush()
    return unit


@pytest.fixture()
def fx(db):
    """权限评测夹具：返回 dict，键名与评测文档一致。"""
    d_fin = Department(name="财务部")
    d_mkt = Department(name="市场部")
    d_hr = Department(name="HR部")
    db.add_all([d_fin, d_mkt, d_hr])
    db.flush()

    r_fin = Role(role_name="财务专员", role_code="r_fin")
    r_mkt = Role(role_name="市场专员", role_code="r_mkt")
    r_hr = Role(role_name="HR专员", role_code="r_hr")
    db.add_all([r_fin, r_mkt, r_hr])
    db.flush()

    u_zhang = User(
        username="u_zhang", password_hash=hash_password("x"), display_name="小张", department_id=d_fin.id
    )
    u_li = User(username="u_li", password_hash=hash_password("x"), display_name="小李", department_id=d_mkt.id)
    u_wang = User(username="u_wang", password_hash=hash_password("x"), display_name="小王", department_id=d_hr.id)
    db.add_all([u_zhang, u_li, u_wang])
    db.flush()
    db.add_all(
        [
            UserRole(user_id=u_zhang.id, role_id=r_fin.id),
            UserRole(user_id=u_li.id, role_id=r_mkt.id),
            UserRole(user_id=u_wang.id, role_id=r_hr.id),
        ]
    )

    units = {
        "unit_global": _add_unit(db, "U_GLOBAL", "全员制度", "全员可见的制度内容。"),
        "unit_fin": _add_unit(
            db, "U_FIN", "财务报销制度", f"差旅住宿标准按城市分档，一线城市 {SENSITIVE_TEXT}。"
        ),
        "unit_role": _add_unit(db, "U_ROLE", "财务专员手册", "财务专员专用的报销口径说明。"),
        "unit_user": _add_unit(db, "U_USER", "小张专属", "仅小张可见的个人内容。"),
        "unit_mixed": _add_unit(db, "U_MIXED", "混合授权制度", "财务部或市场专员可见的内容。"),
        "unit_none": _add_unit(db, "U_NONE", "无权限单元", "没有任何授权记录的内容。"),
        "unit_multi": _add_unit(db, "U_MULTI", "多部门制度", "财务部和 HR 部共同可见的内容。"),
    }
    db.flush()

    db.add_all(
        [
            UnitPermission(unit_id=units["unit_global"].id, target_type="global", target_id=None),
            UnitPermission(unit_id=units["unit_fin"].id, target_type="department", target_id=d_fin.id),
            UnitPermission(unit_id=units["unit_role"].id, target_type="role", target_id=r_fin.id),
            UnitPermission(unit_id=units["unit_user"].id, target_type="user", target_id=u_zhang.id),
            # OR：财务部 或 市场专员
            UnitPermission(unit_id=units["unit_mixed"].id, target_type="department", target_id=d_fin.id),
            UnitPermission(unit_id=units["unit_mixed"].id, target_type="role", target_id=r_mkt.id),
            # 多部门：财务部 + HR 部
            UnitPermission(unit_id=units["unit_multi"].id, target_type="department", target_id=d_fin.id),
            UnitPermission(unit_id=units["unit_multi"].id, target_type="department", target_id=d_hr.id),
        ]
    )
    db.commit()

    return {
        "db": db,
        "departments": {"d_fin": d_fin, "d_mkt": d_mkt, "d_hr": d_hr},
        "roles": {"r_fin": r_fin, "r_mkt": r_mkt, "r_hr": r_hr},
        "users": {"u_zhang": u_zhang, "u_li": u_li, "u_wang": u_wang},
        "units": units,
    }


@pytest.fixture()
def seed_kb(db):
    """导入 3 篇示例文档，并对测试用户授予全局权限（用于忠实度 / 检索评测）。"""
    from app.services.ingest import import_path

    dept = Department(name="评测部")
    db.add(dept)
    db.flush()
    user = User(
        username="u_eval", password_hash=hash_password("x"), display_name="评测员", department_id=dept.id
    )
    db.add(user)
    db.flush()

    units = {}
    for filename, category in [
        ("财务报销制度.md", "财务制度"),
        ("产品使用手册.md", "产品文档"),
        ("HR考勤政策.md", "人力资源"),
    ]:
        result = import_path(db, user.id, str(SEED_DOCS / filename), category=category)
        unit = db.get(KnowledgeUnit, result["unit_id"])
        units[unit.title] = unit
        db.add(UnitPermission(unit_id=unit.id, target_type="global", target_id=None))
    db.commit()

    from app.services.vector_store import store

    store.mark_dirty()
    store.ensure(db)
    return {"db": db, "user": user, "units": units}
