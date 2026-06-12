"""采集流水线：URL 白名单 -> 抓取 -> 正文提取 -> PII 脱敏 -> RawDocument。

也支持从本地目录读取文章（离线 demo / 人工投喂材料）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .. import pii
from ..schemas import RawDocument
from .extractor import extract_main_text
from .fetcher import fetch

logger = logging.getLogger(__name__)

MIN_TEXT_LENGTH = 80  # 过短的页面基本是列表页/错误页


def crawl_urls(urls: list[str], source_names: dict[str, str] | None = None) -> list[RawDocument]:
    """抓取一批 URL，返回清洗+脱敏后的文档列表。"""
    source_names = source_names or {}
    docs: list[RawDocument] = []
    seen_hashes: set[str] = set()

    for url in urls:
        html = fetch(url)
        if not html:
            continue
        title, text, date = extract_main_text(html)
        if len(text) < MIN_TEXT_LENGTH:
            logger.info("正文过短，跳过: %s", url)
            continue

        doc = RawDocument(
            url=url,
            source_name=source_names.get(url, urlparse(url).netloc),
            title=pii.redact(title),
            publish_date=date,
            text=pii.redact(text),
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
        if doc.text_hash in seen_hashes:
            logger.info("内容重复，跳过: %s", url)
            continue
        seen_hashes.add(doc.text_hash)
        docs.append(doc)
    return docs


def load_seed_sources(path: Path) -> tuple[list[str], dict[str, str]]:
    """读取来源白名单文件：[{"url": ..., "source_name": ...}, ...]"""
    items = json.loads(path.read_text(encoding="utf-8"))
    urls = [it["url"] for it in items]
    names = {it["url"]: it.get("source_name", "") for it in items}
    return urls, names


def load_local_articles(directory: Path) -> list[RawDocument]:
    """从本地目录读取 JSON 文章文件（离线 demo）。

    每个文件格式：{"title": ..., "source_name": ..., "url": ..., "publish_date": ..., "text": ...}
    """
    docs = []
    for fp in sorted(directory.glob("*.json")):
        data = json.loads(fp.read_text(encoding="utf-8"))
        docs.append(
            RawDocument(
                url=data.get("url", f"local://{fp.name}"),
                source_name=data.get("source_name", "本地样例"),
                title=pii.redact(data.get("title", "")),
                publish_date=data.get("publish_date"),
                text=pii.redact(data["text"]),
                fetched_at=datetime.now(timezone.utc).isoformat(),
            )
        )
    return docs
