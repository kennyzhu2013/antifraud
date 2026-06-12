"""网页正文提取：优先 trafilatura，未安装时降级为 BeautifulSoup 启发式提取。"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

_DATE_RE = re.compile(r"(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})")

_NOISE_TAGS = ["script", "style", "nav", "header", "footer", "aside", "form", "iframe"]


def extract_main_text(html: str) -> tuple[str, str, str | None]:
    """从 HTML 中提取 (标题, 正文, 发布日期)。"""
    try:
        import trafilatura

        text = trafilatura.extract(html, include_comments=False) or ""
        meta = trafilatura.extract_metadata(html)
        title = (meta.title if meta else "") or ""
        date = (meta.date if meta else None) or _find_date(html)
        if text.strip():
            return title, text.strip(), date
    except ImportError:
        pass
    return _soup_extract(html)


def _find_date(text: str) -> str | None:
    m = _DATE_RE.search(text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def _soup_extract(html: str) -> tuple[str, str, str | None]:
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True) or title

    date = _find_date(soup.get_text(" ", strip=True)[:2000])

    for tag in soup(_NOISE_TAGS):
        tag.decompose()

    # 取文本密度最高的容器作为正文，找不到就回退到整个 body
    candidates = soup.find_all(["article", "main", "div", "section"])
    best, best_len = None, 0
    for node in candidates:
        text_len = sum(len(p.get_text(strip=True)) for p in node.find_all("p", recursive=False))
        if text_len > best_len:
            best, best_len = node, text_len
    container = best if best is not None and best_len > 100 else soup

    paragraphs = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    text = "\n".join(p for p in paragraphs if len(p) > 10)
    if not text:
        text = container.get_text("\n", strip=True)
    return title, text, date
