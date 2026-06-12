"""规则抽取兜底：无 LLM 时基于知识库关键词从文章中抽出可用的案例骨架。

质量不如 LLM，但保证流水线离线可跑，且字段全部来自原文，不存在幻觉。
"""

from __future__ import annotations

import re
from typing import Optional

from ..knowledge import FRAUD_KNOWLEDGE
from ..schemas import FraudCase, MoneyFlow, RawDocument

# 金额：支持 “5.8万元”“58000元”“1,200元” 等写法
_AMOUNT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(万余?元|万|余?元)")
_PAYMENT_METHODS = ["银行转账", "银行卡转账", "微信转账", "支付宝转账", "扫码支付", "ATM", "现金", "虚拟币", "USDT", "网银"]
_AGE_GROUPS = {"老年": "老年", "中老年": "中老年", "大学生": "青年", "学生": "青少年", "年轻": "青年", "退休": "老年"}


def classify_fraud_type(text: str) -> tuple[str, list[str], float]:
    """根据关键词命中数判定诈骗类型，返回 (类型, 命中词, 归一化得分)。"""
    best_type, best_hits = "其他", []
    for fraud_type, kb in FRAUD_KNOWLEDGE.items():
        hits = [kw for kw in kb["keywords"] if kw in text]
        if len(hits) > len(best_hits):
            best_type, best_hits = fraud_type, hits
    score = min(len(best_hits) / 4.0, 1.0)
    return best_type, best_hits, score


def _extract_amount(text: str) -> Optional[float]:
    amounts = []
    for m in _AMOUNT_RE.finditer(text):
        value = float(m.group(1).replace(",", ""))
        if "万" in m.group(2):
            value *= 10000
        amounts.append(value)
    return max(amounts) if amounts else None  # 取最大值近似为损失金额


def _extract_quotes(text: str) -> list[str]:
    """提取文中的引号话术（骗子原话往往在引号内）。"""
    quotes = re.findall(r"[“\"]([^”\"]{4,60})[”\"]", text)
    return quotes[:8]


def _extract_victim_age(text: str) -> Optional[str]:
    for kw, group in _AGE_GROUPS.items():
        if kw in text:
            return group
    return None


def rule_extract(doc: RawDocument) -> Optional[FraudCase]:
    """规则抽取。命中度太低（很可能不是诈骗案例文章）时返回 None。"""
    text = doc.title + "\n" + doc.text
    fraud_type, hits, score = classify_fraud_type(text)
    if fraud_type == "其他" or len(hits) < 2:
        return None

    kb = FRAUD_KNOWLEDGE[fraud_type]
    amount = _extract_amount(text)
    payment = next((p for p in _PAYMENT_METHODS if p in text), None)

    summary = doc.text[:120].replace("\n", " ")
    case = FraudCase(
        title=doc.title or f"{fraud_type}案例",
        source_url=doc.url,
        source_name=doc.source_name,
        publish_date=doc.publish_date,
        fraud_type=fraud_type,
        scenario=summary,
        fraud_script=_extract_quotes(doc.text),
        key_risk_signals=list(dict.fromkeys(kb["risk_signals"] + hits))[:10],
        money_flow=MoneyFlow(payment_method=payment, amount=amount),
        loss_amount=amount,
        summary=summary,
        recommended_warning=kb["warning"],
        confidence=round(0.3 + 0.4 * score, 2),  # 规则抽取置信度上限 0.7
        raw_text_hash=doc.text_hash,
        extraction_method="rule",
    )
    case.victim_profile.age_group = _extract_victim_age(text)
    return case
