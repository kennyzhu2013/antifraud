"""通话文本规则初筛：关键词命中 -> (规则分, 疑似类型, 命中信号)。"""

from __future__ import annotations

from ..knowledge import FRAUD_KNOWLEDGE, GENERIC_HIGH_RISK_PHRASES


def rule_score(text: str) -> tuple[float, str | None, list[str]]:
    """返回 (0~1 规则分, 最可能的诈骗类型, 命中的信号词)。"""
    matched: list[str] = []

    best_type, best_hits = None, 0
    for fraud_type, kb in FRAUD_KNOWLEDGE.items():
        hits = [kw for kw in kb["keywords"] if kw in text]
        matched.extend(hits)
        if len(hits) > best_hits:
            best_type, best_hits = fraud_type, len(hits)

    generic_hits = [p for p in GENERIC_HIGH_RISK_PHRASES if p in text]
    matched.extend(generic_hits)

    # 类型词每个 0.15 分、通用高危词每个 0.25 分，封顶 1.0
    score = min(best_hits * 0.15 + len(generic_hits) * 0.25, 1.0)
    if best_hits < 1 and not generic_hits:
        best_type = None
    return score, best_type, list(dict.fromkeys(matched))
