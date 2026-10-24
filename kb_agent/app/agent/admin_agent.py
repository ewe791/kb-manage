"""管理员 Agent：手写 Function Calling 循环（不使用 LangChain 等框架）。"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools import TOOL_SPECS, dispatch
from app.models import User
from app.services import llm
from app.utils.response import BizError

logger = logging.getLogger(__name__)

MAX_ROUNDS = 6

ADMIN_SYSTEM_PROMPT = """你是「知识库管理助手」，服务于知识管理员。
特别关注两件事：
1) 配数据权限时必须明确对象类型（global/department/role/user）和具体值，
   缺一不可；配置后复述"已授权给：财务部、财务专员角色、张三"。
2) 用户问"最近有什么没答上来的问题"时调 list_knowledge_gaps，
   按提问次数降序汇报，提示可一键创建知识单元。

工作原则：
- 需要操作知识库时必须调用工具，不要凭空声称已经完成；工具返回后再向用户汇报。
- 权限配置调用 set_unit_permissions，targets 里逐个给出 target_type 与 target_value
  （部门写部门名、角色写角色名、人员写姓名或用户名）；只给部门看时不要额外加 global。
- 用户只说了部门/角色/人员的自然语言描述时，直接转成对应 target_type，不要反问类型。
- 汇报要简洁，用中文，列出单元标题、切片数、授权对象等关键结果。
- 无法完成时说明原因，不要编造 unit_id 或数据。
"""


def _assistant_message(message: Any) -> dict:
    payload: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
    if getattr(message, "tool_calls", None):
        payload["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
            }
            for tc in message.tool_calls
        ]
    return payload


async def run_admin_agent(
    db: Session,
    user: User,
    message: str,
    history: list[dict] | None = None,
    session_id: str | None = None,
) -> dict:
    messages: list[dict] = [{"role": "system", "content": ADMIN_SYSTEM_PROMPT}]
    for item in history or []:
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    trace: list[dict] = []
    for _round in range(MAX_ROUNDS):
        completion = await llm.chat_completion(messages, tools=TOOL_SPECS, tool_choice="auto")
        choice = completion.choices[0].message
        messages.append(_assistant_message(choice))

        if not getattr(choice, "tool_calls", None):
            return {
                "answer": (choice.content or "").strip(),
                "tool_trace": trace,
                "session_id": session_id,
            }

        for call in choice.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            try:
                result = await dispatch(name, args, db, user)
                trace.append({"tool": name, "arguments": args, "ok": True})
            except BizError as exc:
                result = json.dumps({"error": exc.message}, ensure_ascii=False)
                trace.append({"tool": name, "arguments": args, "ok": False, "error": exc.message})
            except Exception as exc:  # noqa: BLE001
                logger.exception("工具执行异常：%s", name)
                result = json.dumps({"error": f"工具执行失败：{exc}"}, ensure_ascii=False)
                trace.append({"tool": name, "arguments": args, "ok": False, "error": str(exc)})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

    return {
        "answer": "操作步骤较多，尚未全部完成。请确认后我再继续处理剩余部分。",
        "tool_trace": trace,
        "session_id": session_id,
    }
