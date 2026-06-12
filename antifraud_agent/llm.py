"""LLM 客户端封装：OpenAI 兼容接口，未配置 key 时返回 None 让调用方走规则兜底。"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from .config import settings

logger = logging.getLogger(__name__)


def llm_available() -> bool:
    return bool(settings.llm_api_key)


def chat_json(system: str, user: str, max_tokens: int = 2000) -> Optional[dict[str, Any]]:
    """调用 LLM 并解析 JSON 输出。失败或未配置时返回 None。"""
    if not llm_available():
        return None
    try:
        resp = httpx.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": settings.llm_model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as exc:  # 网络/解析失败都降级，不阻塞流水线
        logger.warning("LLM 调用失败，降级为规则模式: %s", exc)
        return None
