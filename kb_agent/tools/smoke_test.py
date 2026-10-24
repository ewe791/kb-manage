"""端到端验收脚本：两条演示链路 + 管理员 Agent + 看板 + FAQ 沉淀缓存。

前置：后端运行在 127.0.0.1:8010，且已执行 seed.init_seed。
用法：python tools/smoke_test.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import os

import httpx

BASE = os.getenv("KB_API_BASE", "http://127.0.0.1:8000/api")
ROOT = Path(__file__).resolve().parent.parent
client = httpx.Client(base_url=BASE, timeout=180.0, trust_env=False)


def login(username: str, password: str) -> tuple[str, dict]:
    data = client.post("/auth/login", json={"username": username, "password": password}).json()
    if data.get("code") != 0:
        raise SystemExit(f"登录失败 {username}: {data}")
    return data["data"]["access_token"], data["data"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def out_status(code: int, message: str | None) -> str:
    return f"{code} {message or ''}".strip()


def main() -> None:
    print("=" * 74)
    lisi_token, lisi = login("lisi", "Ls@123456")
    zs_token, zs = login("zhangsan", "Zs@123456")
    ww_token, ww = login("wangwu", "Ww@123456")
    admin_token, admin = login("admin", "Admin@123")
    print(f"李四（市场部·普通员工）权限：{lisi['permissions']}")
    print(f"张三（财务部·财务专员）权限：{zs['permissions']}")
    print(f"王五（人力资源部·普通员工）权限：{ww['permissions']}")
    print(f"管理员权限数：{len(admin['permissions'])}")

    units = client.get("/knowledge/units", headers=auth(admin_token), params={"page_size": 50}).json()["data"]["items"]
    finance = next(u for u in units if "财务报销" in u["title"])
    print(f"\n知识单元：{[(u['title'], u['chunk_count'], u['permissions']) for u in units]}")

    print("\n--- check-permissions：同一批单元，不同人不同结果 ---")
    for name, token in (("李四", lisi_token), ("张三", zs_token), ("王五", ww_token)):
        r = client.post("/knowledge/check-permissions", headers=auth(token),
                        json={"unit_ids": [u["id"] for u in units]}).json()["data"]
        print(f"{name}: 授权 {len(r['authorized_unit_ids'])} 条 / 未授权 {len(r['unauthorized_unit_ids'])} 条")

    print("\n--- 演示链路 1：李四问「差旅住宿标准是多少」---")
    lisi_answer = client.post("/ai/chat", headers=auth(lisi_token),
                              json={"question": "差旅住宿标准是多少"}).json()["data"]
    print(f"unauthorized_count={lisi_answer['unauthorized_count']} cached={lisi_answer['cached']}")
    print(lisi_answer["answer"])

    print("\n--- 演示链路 2：张三问同一问题 ---")
    zs_answer = client.post("/ai/chat", headers=auth(zs_token),
                            json={"question": "差旅住宿标准是多少"}).json()["data"]
    print(f"unauthorized_count={zs_answer['unauthorized_count']}")
    print(f"引用：{[(c['title'], c['ref_index']) for c in zs_answer['citations']]}")
    print(zs_answer["answer"][:420])

    print("\n--- SSE 流式（李四，权限缺失提示事件）---")
    events: list[str] = []
    deltas: list[str] = []
    with client.stream("POST", "/ai/chat/stream", headers=auth(lisi_token),
                       json={"question": "出差住宿费能报多少"}) as resp:
        event = ""
        for line in resp.iter_lines():
            if line.startswith("event: "):
                event = line[7:].strip()
                events.append(event)
            elif line.startswith("data: "):
                payload = json.loads(line[6:])
                if event == "message_delta":
                    deltas.append(payload.get("delta_text", ""))
                elif event == "citations":
                    print("citations:", payload["citations"])
                elif event == "permission_warning":
                    print("permission_warning:", payload)
                elif event == "done":
                    print("done:", payload)
    print("事件序列:", " -> ".join(dict.fromkeys(events)))
    print("回答:", "".join(deltas)[:140].replace("\n", " "))

    print("\n--- 管理员 Agent：知识缺口 ---")
    gaps_resp = client.post("/agent/admin/chat", headers=auth(admin_token),
                            json={"message": "最近有什么没答上来的问题？按提问次数降序汇报"}).json()
    print("工具调用:", gaps_resp["data"]["tool_trace"])
    print(gaps_resp["data"]["answer"][:450])

    print("\n--- 管理员 Agent：导入 + 只给人力资源部看 ---")
    demo_doc = ROOT / "data" / "行政设备领用制度.md"
    demo_doc.write_text(
        "# 行政设备领用制度\n\n"
        "## 一、适用范围\n本制度适用于总部及各分支机构全体员工的办公设备领用与归还。\n\n"
        "## 二、领用流程\n1. 员工在 OA 提交设备领用申请，注明设备型号、用途与预计归还日期。\n"
        "2. 直属上级审批后，由行政部在 2 个工作日内备货。\n"
        "3. 领用人当面验收设备并签署领用单，注明设备编号与外观状况。\n\n"
        "## 三、归还与赔偿\n设备归还时须经行政部验收；人为损坏的，按设备折旧后净值的 50% 赔偿。\n",
        encoding="utf-8",
    )
    import_resp = client.post("/agent/admin/chat", headers=auth(admin_token), json={
        "message": f"把 {demo_doc.relative_to(ROOT).as_posix()} 这份文档导入，分类是行政制度，只给人力资源部看"
    }).json()
    print("工具调用:", import_resp["data"]["tool_trace"])
    print(import_resp["data"]["answer"][:420])

    new_units = client.get("/knowledge/units", headers=auth(admin_token),
                           params={"keyword": "行政设备领用制度"}).json()["data"]["items"]
    if new_units:
        created = new_units[0]
        print(f"新建单元：{created['title']} 权限={created['permissions']}")
        for name, token in (("王五", ww_token), ("李四", lisi_token)):
            r = client.post("/knowledge/check-permissions", headers=auth(token),
                            json={"unit_ids": [created["id"]]}).json()["data"]
            print(f"  {name} -> {'授权' if r['authorized_unit_ids'] else '未授权'}")
        client.request("DELETE", "/knowledge/units", headers=auth(admin_token),
                       json={"unit_ids": [created["id"]]})
        print("  已清理演示单元")

    print("\n--- 看板 ---")
    for path in ("/dashboard/metrics", "/dashboard/rankings/questions",
                 "/dashboard/rankings/units", "/dashboard/stats/tokens"):
        data = client.get(path, headers=auth(admin_token)).json()
        print(path, "->", json.dumps(data.get("data"), ensure_ascii=False)[:240])

    print("\n--- FAQ 沉淀：张三同一问题累计 5 次 -> 生成推荐 ---")
    for _ in range(5):
        client.post("/ai/chat", headers=auth(zs_token), json={"question": "差旅住宿标准是多少"})
    faqs = client.get("/settlement/faqs/recommendations", headers=auth(admin_token)).json()["data"]
    print("FAQ 推荐条数:", len(faqs))
    for faq in faqs[:3]:
        print(f"  - {faq['question']}（命中 {faq['hit_count']} 次，{faq['status']}，来源单元 {faq['related_unit_id']}）")

    if faqs:
        faq = faqs[0]
        reviewed = client.post(f"/settlement/faqs/{faq['id']}/review", headers=auth(admin_token),
                               json={"action": "approve", "edited_answer": faq["answer"]}).json()
        print("审核结果:", reviewed["data"]["status"])
        hit = client.post("/ai/chat", headers=auth(zs_token),
                          json={"question": faq["question"]}).json()["data"]
        print(f"张三再问 cached={hit['cached']} 耗时={hit['response_time_ms']}ms")
        print("回答:", hit["answer"][:160].replace("\n", " "))
        leak = client.post("/ai/chat", headers=auth(lisi_token),
                           json={"question": faq["question"]}).json()["data"]
        print(f"李四再问 cached={leak['cached']} unauthorized_count={leak['unauthorized_count']}（缓存不越权）")

    print("\n--- 知识缺口列表 ---")
    gaps = client.get("/settlement/knowledge-gaps", headers=auth(admin_token)).json()["data"]
    for gap in gaps[:5]:
        print(f"  - {gap['question_pattern']} × {gap['ask_count']} ({gap['status']})")

    print("\n--- 组织：部门树 / 角色权限 / 用户启停用 ---")
    tree = client.get("/org/departments/tree", headers=auth(admin_token)).json()["data"]
    print("部门树:", [(n["name"], f"{n['member_count']}人", n["leader_name"]) for n in tree])
    roles = client.get("/org/roles", headers=auth(admin_token)).json()["data"]
    role = next(r for r in roles if r["role_code"] == "employee")
    upd = client.post(f"/org/roles/{role['id']}/permissions", headers=auth(admin_token),
                      json={"permissions": list(dict.fromkeys(role["permissions"]))}).json()
    print("角色权限覆盖:", upd["data"]["role_name"], "->", upd["data"]["permissions"])
    zs_user = next(u for u in client.get("/org/users", headers=auth(admin_token),
                                         params={"keyword": "zhangsan"}).json()["data"]["items"])
    off = client.put(f"/org/users/{zs_user['id']}", headers=auth(admin_token), json={"status": "disabled"}).json()
    blocked = client.post("/auth/login", json={"username": "zhangsan", "password": "Zs@123456"})
    print("停用后登录:", out_status(blocked.status_code, blocked.json().get("message")))
    client.put(f"/org/users/{zs_user['id']}", headers=auth(admin_token), json={"status": "active"})
    print("恢复启用:", off["data"]["status"], "-> active")

    print("\n--- 会话管理：历史会话与消息 ---")
    sessions = client.get("/ai/sessions", headers=auth(zs_token)).json()["data"]
    print("会话数:", len(sessions))
    if sessions:
        detail = client.get(f"/ai/sessions/{sessions[0]['session_id']}/messages", headers=auth(zs_token)).json()["data"]
        print("会话消息数:", len(detail["messages"]), "| 首条:", detail["messages"][0]["question"])

    print("\n--- 看板：周趋势 / 响应时间分布 ---")
    week = client.get("/dashboard/stats/tokens", headers=auth(admin_token),
                      params={"granularity": "week"}).json()["data"]
    print("周趋势:", week)
    rt = client.get("/dashboard/stats/response-time", headers=auth(admin_token)).json()["data"]
    print(f"响应分布: total={rt['total']} p50={rt['p50_ms']} p95={rt['p95_ms']}",
          [(b["label"], b["count"]) for b in rt["buckets"]])

    print("\n--- 知识单元：正文更新后重建切片 ---")
    detail = client.get(f"/knowledge/units/{finance['id']}", headers=auth(admin_token)).json()["data"]
    before = detail["chunk_count"]
    appended = detail["content"] + "\n\n## 附：本次验收追加条款\n验收专用条款：住宿标准按城市分档执行。\n"
    client.put(f"/knowledge/units/{finance['id']}", headers=auth(admin_token),
               json={"content": appended})
    after = client.get(f"/knowledge/units/{finance['id']}", headers=auth(admin_token)).json()["data"]["chunk_count"]
    print(f"切片数 {before} -> {after}（正文变更已重建索引）")

    print("\n--- 知识缺口：一键创建知识单元 ---")
    gaps_now = client.get("/settlement/knowledge-gaps", headers=auth(admin_token)).json()["data"]
    if gaps_now:
        gap = gaps_now[0]
        created = client.post(f"/settlement/knowledge-gaps/{gap['id']}/create-unit", headers=auth(admin_token),
                              json={
                                  "title": gap["question_pattern"],
                                  "content": "## 标准说明\n差旅住宿费按城市分档：一线城市 600 元/晚，二线城市 450 元/晚，其他城市 350 元/晚。\n",
                                  "category": "财务制度",
                                  "targets": [{"target_type": "department", "target_id": "财务部"}],
                              }).json()
        if created.get("code") == 0:
            unit = created["data"]["unit"]
            print(f"已建档：{unit['title']}，切片 {unit['chunk_count']}，缺口状态 {created['data']['gap']['status']}")
            print("  权限:", [p["target_name"] for p in unit["permissions"]])
            client.request("DELETE", "/knowledge/units", headers=auth(admin_token),
                           json={"unit_ids": [unit["id"]]})
            print("  已清理演示单元")
        else:
            print("失败:", created)

    print("\n--- 权限拦截验证：无 org:manage 的用户访问组织接口 ---")
    denied = client.get("/org/users", headers=auth(lisi_token))
    print("李四 GET /org/users ->", denied.status_code, denied.json()["message"])
    denied2 = client.get("/dashboard/metrics", headers=auth(lisi_token))
    print("李四 GET /dashboard/metrics ->", denied2.status_code, denied2.json()["message"])

    print("\n" + "=" * 74)
    print("验收脚本执行完毕")


if __name__ == "__main__":
    sys.exit(main())
