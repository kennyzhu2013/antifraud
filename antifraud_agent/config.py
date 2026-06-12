"""全局配置，全部支持环境变量覆盖。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


@dataclass
class Settings:
    # 存储
    db_path: Path = field(default_factory=lambda: Path(_env("AF_DB_PATH", str(PROJECT_ROOT / "data" / "cases.db"))))

    # 爬虫
    user_agent: str = field(default_factory=lambda: _env("AF_USER_AGENT", "antifraud-case-bot/0.1 (+research; respects robots.txt)"))
    request_timeout: float = field(default_factory=lambda: float(_env("AF_REQUEST_TIMEOUT", "15")))
    crawl_delay_seconds: float = field(default_factory=lambda: float(_env("AF_CRAWL_DELAY", "2.0")))
    max_retries: int = field(default_factory=lambda: int(_env("AF_MAX_RETRIES", "3")))

    # LLM（OpenAI 兼容接口；不配 key 时自动降级为纯规则模式）
    llm_api_key: str = field(default_factory=lambda: _env("AF_LLM_API_KEY", os.environ.get("OPENAI_API_KEY", "")))
    llm_base_url: str = field(default_factory=lambda: _env("AF_LLM_BASE_URL", "https://api.openai.com/v1"))
    llm_model: str = field(default_factory=lambda: _env("AF_LLM_MODEL", "gpt-4o-mini"))

    # Embedding：openai / local（sentence-transformers）/ hash（零依赖兜底）
    embedding_backend: str = field(default_factory=lambda: _env("AF_EMBEDDING_BACKEND", "hash"))
    embedding_model: str = field(default_factory=lambda: _env("AF_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"))
    embedding_dim: int = field(default_factory=lambda: int(_env("AF_EMBEDDING_DIM", "256")))

    # 检测
    high_risk_threshold: float = field(default_factory=lambda: float(_env("AF_HIGH_RISK", "0.7")))
    medium_risk_threshold: float = field(default_factory=lambda: float(_env("AF_MEDIUM_RISK", "0.4")))
    top_k_similar: int = field(default_factory=lambda: int(_env("AF_TOP_K", "5")))


settings = Settings()
