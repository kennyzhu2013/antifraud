"""Validation Agent：入库前校验抽取结果。

检查项：必填字段、金额/日期合理性、PII 残留、与原文一致性（防幻觉的轻量检查）。
"""

from __future__ import annotations

import logging
from datetime import datetime

from .. import pii
from ..schemas import FRAUD_TYPES, FraudCase, RawDocument

logger = logging.getLogger(__name__)

MAX_REASONABLE_AMOUNT = 1e9  # 单案损失超过 10 亿元基本是抽取错误


def validate_case(case: FraudCase, doc: RawDocument) -> tuple[bool, list[str]]:
    """返回 (是否通过, 问题列表)。问题可修复的会就地修复并继续通过。"""
    problems: list[str] = []

    if not case.summary and not case.scenario:
        problems.append("缺少摘要与场景描述")
        return False, problems

    if case.fraud_type not in FRAUD_TYPES:
        case.fraud_type = "其他"
        problems.append("诈骗类型不在枚举内，已归为其他")

    # 金额合理性
    for label, value in [("loss_amount", case.loss_amount), ("money_flow.amount", case.money_flow.amount)]:
        if value is not None and not (0 < value < MAX_REASONABLE_AMOUNT):
            problems.append(f"金额异常({label}={value})，已清空")
            if label == "loss_amount":
                case.loss_amount = None
            else:
                case.money_flow.amount = None

    # 日期合理性
    if case.publish_date:
        try:
            d = datetime.fromisoformat(case.publish_date[:10])
            if d.year < 2000 or d > datetime.now():
                raise ValueError
        except ValueError:
            problems.append(f"发布日期异常({case.publish_date})，已清空")
            case.publish_date = None

    # PII 残留检查 + 强制脱敏
    for field_name in ["title", "scenario", "summary"]:
        value = getattr(case, field_name)
        leaked = pii.contains_pii(value)
        if leaked:
            problems.append(f"{field_name} 残留 PII {leaked}，已脱敏")
            setattr(case, field_name, pii.redact(value))
    case.fraud_script = [pii.redact(s) for s in case.fraud_script]
    case.key_risk_signals = [pii.redact(s) for s in case.key_risk_signals]

    # 轻量防幻觉：LLM 给出的话术若大部分在原文中找不到任何片段支撑，降低置信度
    if case.extraction_method == "llm" and case.fraud_script:
        grounded = sum(1 for s in case.fraud_script if _loosely_in(s, doc.text))
        if grounded / len(case.fraud_script) < 0.3:
            case.confidence = min(case.confidence, 0.4)
            problems.append("话术与原文匹配度低，已下调置信度")

    case.raw_text_hash = doc.text_hash
    return True, problems


def _loosely_in(snippet: str, text: str) -> bool:
    """片段或其任一 6 字子串出现在原文中即视为有依据。"""
    s = snippet.strip()
    if not s:
        return False
    if s in text:
        return True
    return any(s[i : i + 6] in text for i in range(0, max(len(s) - 5, 1), 3))
