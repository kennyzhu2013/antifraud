"""抽取流水线：优先 LLM，失败/未配置则规则兜底，再统一校验。"""

from __future__ import annotations

import logging
from typing import Optional

from ..schemas import FraudCase, RawDocument
from .llm_extractor import llm_extract
from .rule_extractor import rule_extract
from .validator import validate_case

logger = logging.getLogger(__name__)


def extract_case(doc: RawDocument) -> Optional[FraudCase]:
    """从单篇文档抽取案例。不是诈骗案例或校验失败时返回 None。"""
    case = llm_extract(doc)
    if case is None:
        case = rule_extract(doc)
    if case is None:
        logger.info("未识别为诈骗案例，跳过: %s", doc.url)
        return None

    ok, problems = validate_case(case, doc)
    if problems:
        logger.info("校验提示 %s: %s", doc.url, "; ".join(problems))
    if not ok:
        logger.warning("校验未通过，丢弃: %s", doc.url)
        return None
    return case
