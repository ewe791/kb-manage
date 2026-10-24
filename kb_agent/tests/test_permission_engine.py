"""K-E1：权限引擎单元测试（硬指标，14 条用例全过）。"""
from __future__ import annotations

from app.services.permission_engine import check_permissions

NONE_ID = "unit-not-exist-0000"


def check(db, user, unit_ids):
    return check_permissions(db, user.id, unit_ids)


def test_KE1_1_global_authorization(fx):
    """K-E1-1 全局授权：任意用户访问 unit_global 均授权。"""
    unit = fx["units"]["unit_global"]
    for name in ("u_zhang", "u_li", "u_wang"):
        result = check(fx["db"], fx["users"][name], [unit.id])
        assert result["authorized_unit_ids"] == [unit.id]
        assert result["unauthorized_unit_ids"] == []


def test_KE1_2_department_hit(fx):
    """K-E1-2 部门命中：u_zhang（财务部）访问 unit_fin 授权。"""
    unit = fx["units"]["unit_fin"]
    assert check(fx["db"], fx["users"]["u_zhang"], [unit.id])["authorized_unit_ids"] == [unit.id]


def test_KE1_3_department_miss(fx):
    """K-E1-3 部门不命中：u_li（市场部）访问 unit_fin 未授权。"""
    unit = fx["units"]["unit_fin"]
    result = check(fx["db"], fx["users"]["u_li"], [unit.id])
    assert result["authorized_unit_ids"] == []
    assert result["unauthorized_unit_ids"] == [unit.id]


def test_KE1_4_role_hit(fx):
    """K-E1-4 角色命中：u_zhang（财务专员）访问 unit_role 授权。"""
    unit = fx["units"]["unit_role"]
    assert check(fx["db"], fx["users"]["u_zhang"], [unit.id])["authorized_unit_ids"] == [unit.id]


def test_KE1_5_role_miss(fx):
    """K-E1-5 角色不命中：u_li（市场专员）访问 unit_role 未授权。"""
    unit = fx["units"]["unit_role"]
    result = check(fx["db"], fx["users"]["u_li"], [unit.id])
    assert result["authorized_unit_ids"] == []
    assert result["unauthorized_unit_ids"] == [unit.id]


def test_KE1_6_user_hit(fx):
    """K-E1-6 个人命中：u_zhang 访问 unit_user 授权。"""
    unit = fx["units"]["unit_user"]
    assert check(fx["db"], fx["users"]["u_zhang"], [unit.id])["authorized_unit_ids"] == [unit.id]


def test_KE1_7_user_miss(fx):
    """K-E1-7 个人不命中：u_li 访问 unit_user 未授权。"""
    unit = fx["units"]["unit_user"]
    result = check(fx["db"], fx["users"]["u_li"], [unit.id])
    assert result["authorized_unit_ids"] == []
    assert result["unauthorized_unit_ids"] == [unit.id]


def test_KE1_8_no_permission_record_denied(fx):
    """K-E1-8 无权限记录默认拒绝。"""
    unit = fx["units"]["unit_none"]
    for name in ("u_zhang", "u_li", "u_wang"):
        result = check(fx["db"], fx["users"][name], [unit.id])
        assert result["authorized_unit_ids"] == []
        assert result["unauthorized_unit_ids"] == [unit.id]


def test_KE1_9_or_logic_department_hit(fx):
    """K-E1-9 OR 逻辑-部门命中：u_zhang 访问 unit_mixed 授权。"""
    unit = fx["units"]["unit_mixed"]
    assert check(fx["db"], fx["users"]["u_zhang"], [unit.id])["authorized_unit_ids"] == [unit.id]


def test_KE1_10_or_logic_role_hit(fx):
    """K-E1-10 OR 逻辑-角色命中：u_li（市场专员）访问 unit_mixed 授权。"""
    unit = fx["units"]["unit_mixed"]
    assert check(fx["db"], fx["users"]["u_li"], [unit.id])["authorized_unit_ids"] == [unit.id]


def test_KE1_11_multi_department_any_hit(fx):
    """K-E1-11 多部门任一命中：u_wang（HR部）访问 unit_multi 授权，u_li 未授权。"""
    unit = fx["units"]["unit_multi"]
    assert check(fx["db"], fx["users"]["u_wang"], [unit.id])["authorized_unit_ids"] == [unit.id]
    assert check(fx["db"], fx["users"]["u_zhang"], [unit.id])["authorized_unit_ids"] == [unit.id]
    result = check(fx["db"], fx["users"]["u_li"], [unit.id])
    assert result["authorized_unit_ids"] == []
    assert result["unauthorized_unit_ids"] == [unit.id]


def test_KE1_12_batch_mixed(fx):
    """K-E1-12 批量混合：u_li 仅 unit_global 授权，其余三项未授权。"""
    units = fx["units"]
    ids = [units["unit_global"].id, units["unit_fin"].id, units["unit_role"].id, units["unit_user"].id]
    result = check(fx["db"], fx["users"]["u_li"], ids)
    assert result["authorized_unit_ids"] == [units["unit_global"].id]
    assert result["unauthorized_unit_ids"] == [
        units["unit_fin"].id,
        units["unit_role"].id,
        units["unit_user"].id,
    ]


def test_KE1_13_empty_list(fx):
    """K-E1-13 空列表：返回两个空列表且不报错。"""
    result = check(fx["db"], fx["users"]["u_li"], [])
    assert result == {"authorized_unit_ids": [], "unauthorized_unit_ids": []}


def test_KE1_14_unknown_unit_id(fx):
    """K-E1-14 不存在的 unit_id：归入 unauthorized，不抛异常。"""
    result = check(fx["db"], fx["users"]["u_zhang"], [NONE_ID])
    assert result["authorized_unit_ids"] == []
    assert result["unauthorized_unit_ids"] == [NONE_ID]


def test_KE1_15_disabled_user_denied(fx):
    """补充：停用账号一律未授权（不泄露单元是否存在）。"""
    user = fx["users"]["u_zhang"]
    user.status = "disabled"
    fx["db"].commit()
    unit = fx["units"]["unit_global"]
    result = check(fx["db"], user, [unit.id])
    assert result["authorized_unit_ids"] == []
    assert result["unauthorized_unit_ids"] == [unit.id]
