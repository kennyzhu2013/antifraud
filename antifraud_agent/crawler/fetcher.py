"""合规抓取器：robots.txt 检查、域级限速、失败重试。"""

from __future__ import annotations

import logging
import time
import urllib.robotparser
from urllib.parse import urlparse

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

_robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}
_last_fetch_at: dict[str, float] = {}


def robots_allows(url: str) -> bool:
    """检查 robots.txt 是否允许抓取。robots.txt 不可达时保守放行（多数政务站无 robots）。"""
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    rp = _robots_cache.get(base)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            resp = httpx.get(f"{base}/robots.txt", timeout=settings.request_timeout, follow_redirects=True)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            else:
                rp.allow_all = True
        except Exception:
            rp.allow_all = True
        _robots_cache[base] = rp
    return rp.can_fetch(settings.user_agent, url)


def _throttle(netloc: str) -> None:
    last = _last_fetch_at.get(netloc, 0.0)
    wait = settings.crawl_delay_seconds - (time.monotonic() - last)
    if wait > 0:
        time.sleep(wait)
    _last_fetch_at[netloc] = time.monotonic()


def fetch(url: str) -> str | None:
    """抓取单个 URL 的 HTML。不合规或最终失败返回 None。"""
    if not robots_allows(url):
        logger.info("robots.txt 禁止抓取，跳过: %s", url)
        return None

    netloc = urlparse(url).netloc
    for attempt in range(settings.max_retries):
        _throttle(netloc)
        try:
            resp = httpx.get(
                url,
                headers={"User-Agent": settings.user_agent},
                timeout=settings.request_timeout,
                follow_redirects=True,
            )
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            logger.warning("抓取失败(%d/%d) %s: %s", attempt + 1, settings.max_retries, url, exc)
            time.sleep(2**attempt)
    return None
