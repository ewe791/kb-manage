"""基于授权片段生成回答（LLM 只在这一步参与，不接触任何权限信息）。"""
from __future__ import annotations

import re
from collections.abc import AsyncIterator

from app.config import settings
from app.services import llm

SYSTEM_PROMPT = """你是企业知识库问答助手。必须严格遵守以下规则：
1. 只能依据【资料片段】中的内容回答，禁止使用片段之外的常识、推测或编造。
2. 如果片段不足以回答问题，直接回答“根据现有资料，暂未找到明确答案。”并简要说明缺少哪方面信息。
3. 回答使用简体中文，条理清晰，能分点时用编号列表。
4. 每个引用的信息后面标注片段编号，例如 [1]、[2]；不要编造不存在的编号。
5. 不要在回答里提及“片段/上下文/资料库”等系统用语，也不要复述编号以外的原文大段内容。
"""

REFUSAL_TEXT = "根据现有资料，暂未找到明确答案。"
NO_PERMISSION_TEXT = "知识库中暂未找到您有权访问的相关内容，建议联系知识管理员补充权限或提问。"

_MARK_RE = re.compile(r"\[(\d{1,2})\]")


def _citation_items(authorized_units: list[dict]) -> list[dict]:
    return [
        {
            "index": idx + 1,
            "unit_id": u["unit_id"],
            "title": u.get("title", ""),
            "snippet": u.get("snippet", ""),
        }
        for idx, u in enumerate(authorized_units)
    ]


def build_messages(question: str, authorized_units: list[dict]) -> list[dict]:
    """仅使用授权单元拼接 Prompt。"""
    blocks: list[str] = []
    for idx, unit in enumerate(authorized_units, start=1):
        content = (unit.get("content") or unit.get("snippet") or "").strip()
        if len(content) > 1800:
            content = content[:1800] + "…"
        blocks.append(f"[{idx}] 《{unit.get('title', '未命名')}》\n{content}")
    context = "\n\n".join(blocks) if blocks else "（无可用片段）"
    user_prompt = (
        "【资料片段】\n"
        f"{context}\n\n"
        "【用户问题】\n"
        f"{question}\n\n"
        "请依据以上片段作答。"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def extract_citations(answer: str, authorized_units: list[dict]) -> list[dict]:
    refs: list[int] = []
    for match in _MARK_RE.finditer(answer or ""):
        num = int(match.group(1))
        if 1 <= num <= len(authorized_units) and num not in refs:
            refs.append(num)
    if not refs:
        return []
    result = []
    for num in sorted(refs):
        unit = authorized_units[num - 1]
        result.append(
            {
                "unit_id": unit["unit_id"],
                "title": unit.get("title", ""),
                "snippet": unit.get("snippet", ""),
                "ref_index": num,
            }
        )
    return result


def estimate_tokens(text: str) -> int:
    """无 usage 时的保守估算：中文约 1 字 1 token，英文约 4 字符 1 token。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return int(cjk + other / 4) + 1


async def answer_with_context(question: str, authorized_units: list[dict]) -> dict:
    if not authorized_units:
        return {
            "answer": NO_PERMISSION_TEXT,
            "citations": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "model": settings.LLM_MODEL,
        }
    messages = build_messages(question, authorized_units)
    completion = await llm.chat_completion(messages)
    answer = (completion.choices[0].message.content or "").strip()
    usage = completion.usage
    return {
        "answer": answer,
        "citations": extract_citations(answer, authorized_units),
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        "model": settings.LLM_MODEL,
    }


async def stream_answer_with_context(question: str, authorized_units: list[dict]) -> AsyncIterator[dict]:
    """流式生成：yield {"type": "delta"|"final", ...}。"""
    if not authorized_units:
        yield {"type": "delta", "text": NO_PERMISSION_TEXT}
        yield {
            "type": "final",
            "answer": NO_PERMISSION_TEXT,
            "citations": [],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        return

    messages = build_messages(question, authorized_units)
    parts: list[str] = []
    usage = None
    async for delta_text, chunk_usage in llm.stream_completion(messages):
        if delta_text:
            parts.append(delta_text)
            yield {"type": "delta", "text": delta_text}
        if chunk_usage is not None:
            usage = chunk_usage

    answer = "".join(parts).strip()
    if usage is not None:
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or 0)
    else:
        prompt_tokens = estimate_tokens(messages[0]["content"]) + estimate_tokens(messages[1]["content"])
        completion_tokens = estimate_tokens(answer)
        total_tokens = prompt_tokens + completion_tokens

    yield {
        "type": "final",
        "answer": answer,
        "citations": extract_citations(answer, authorized_units),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
