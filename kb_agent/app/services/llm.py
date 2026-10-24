"""LLM 客户端（OpenAI 兼容接口）。密钥只从配置读取。"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI, BadRequestError

from app.config import settings
from app.utils.response import BizError

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if not settings.LLM_API_KEY:
        raise BizError("未配置 LLM_API_KEY，无法调用大模型", code=500, status_code=500)
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            timeout=90.0,
            max_retries=2,
        )
    return _client


async def chat_completion(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Any:
    kwargs: dict[str, Any] = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "temperature": settings.LLM_TEMPERATURE if temperature is None else temperature,
        "max_tokens": settings.LLM_MAX_TOKENS if max_tokens is None else max_tokens,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice or "auto"
    try:
        return await get_client().chat.completions.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM 调用失败")
        raise BizError(f"大模型调用失败：{exc}", code=502, status_code=502) from exc


async def stream_completion(
    messages: list[dict[str, Any]],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AsyncIterator[tuple[str, Any | None]]:
    """流式输出，逐块返回 (delta_text, usage 或 None)。"""
    base: dict[str, Any] = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "temperature": settings.LLM_TEMPERATURE if temperature is None else temperature,
        "max_tokens": settings.LLM_MAX_TOKENS if max_tokens is None else max_tokens,
        "stream": True,
    }
    stream = None
    try:
        stream = await get_client().chat.completions.create(
            **base, stream_options={"include_usage": True}
        )
    except BadRequestError:
        # 部分兼容网关不支持 stream_options，退化为不取 usage（后续按字符估算）
        stream = await get_client().chat.completions.create(**base)
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM 流式调用失败")
        raise BizError(f"大模型调用失败：{exc}", code=502, status_code=502) from exc

    async for chunk in stream:
        usage = getattr(chunk, "usage", None)
        delta_text = ""
        if chunk.choices:
            delta = chunk.choices[0].delta
            delta_text = getattr(delta, "content", None) or ""
        if delta_text or usage:
            yield delta_text, usage
