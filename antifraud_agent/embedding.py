"""文本向量化，三种后端：

- hash : 零依赖兜底。中文按字符 2-gram 做 feature hashing，离线可用，适合 demo 与测试。
- local: sentence-transformers 本地模型（如 BGE/E5），生产推荐。
- openai: OpenAI 兼容 embedding 接口。
"""

from __future__ import annotations

import hashlib
import logging
import re

import numpy as np

from .config import settings

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[\u4e00-\u9fa5]|[A-Za-z0-9]+")

_local_model = None


def _tokenize(text: str) -> list[str]:
    chars = _TOKEN_RE.findall(text.lower())
    bigrams = ["".join(chars[i : i + 2]) for i in range(len(chars) - 1)]
    return chars + bigrams


def _hash_embed(text: str, dim: int) -> np.ndarray:
    vec = np.zeros(dim, dtype=np.float32)
    for token in _tokenize(text):
        h = int.from_bytes(hashlib.md5(token.encode("utf-8")).digest()[:8], "little")
        idx = h % dim
        sign = 1.0 if (h >> 63) & 1 else -1.0
        vec[idx] += sign
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


def _local_embed(texts: list[str]) -> np.ndarray:
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer

        _local_model = SentenceTransformer(settings.embedding_model)
    return np.asarray(_local_model.encode(texts, normalize_embeddings=True), dtype=np.float32)


def _openai_embed(texts: list[str]) -> np.ndarray:
    import httpx

    resp = httpx.post(
        f"{settings.llm_base_url.rstrip('/')}/embeddings",
        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        json={"model": settings.embedding_model, "input": texts},
        timeout=60,
    )
    resp.raise_for_status()
    data = sorted(resp.json()["data"], key=lambda d: d["index"])
    arr = np.asarray([d["embedding"] for d in data], dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return arr / norms


def embed(texts: list[str]) -> np.ndarray:
    """返回 L2 归一化后的向量矩阵 (n, dim)。"""
    backend = settings.embedding_backend
    try:
        if backend == "local":
            return _local_embed(texts)
        if backend == "openai":
            return _openai_embed(texts)
    except Exception as exc:
        logger.warning("embedding 后端 %s 失败，降级为 hash: %s", backend, exc)
    return np.stack([_hash_embed(t, settings.embedding_dim) for t in texts])
