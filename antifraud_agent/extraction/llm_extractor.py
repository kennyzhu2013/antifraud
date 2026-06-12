"""LLM 抽取：调用大模型把文章转成结构化案例。失败返回 None 由上层走规则兜底。"""

from __future__ import annotations

from typing import Optional

from ..llm import chat_json
from ..schemas import FRAUD_TYPES, FraudCase, MoneyFlow, RawDocument, VictimProfile
from .prompts import EXTRACTION_SYSTEM, EXTRACTION_USER_TEMPLATE

MAX_ARTICLE_CHARS = 6000


def llm_extract(doc: RawDocument) -> Optional[FraudCase]:
    data = chat_json(
        EXTRACTION_SYSTEM,
        EXTRACTION_USER_TEMPLATE.format(title=doc.title, text=doc.text[:MAX_ARTICLE_CHARS]),
    )
    if not data or not data.get("is_fraud_case"):
        return None

    fraud_type = data.get("fraud_type") or "其他"
    if fraud_type not in FRAUD_TYPES:
        fraud_type = "其他"

    money = data.get("money_flow") or {}
    victim = data.get("victim_profile") or {}
    return FraudCase(
        title=data.get("title") or doc.title,
        source_url=doc.url,
        source_name=doc.source_name,
        publish_date=doc.publish_date,
        fraud_type=fraud_type,
        scenario=data.get("scenario") or "",
        victim_profile=VictimProfile(
            age_group=victim.get("age_group"),
            occupation=victim.get("occupation"),
            gender=victim.get("gender"),
        ),
        fraud_script=[s for s in (data.get("fraud_script") or []) if isinstance(s, str)],
        key_risk_signals=[s for s in (data.get("key_risk_signals") or []) if isinstance(s, str)],
        money_flow=MoneyFlow(
            payment_method=money.get("payment_method"),
            amount=_to_float(money.get("amount")),
        ),
        loss_amount=_to_float(data.get("loss_amount")),
        summary=data.get("summary") or "",
        recommended_warning=data.get("recommended_warning") or "",
        confidence=float(data.get("confidence") or 0.5),
        raw_text_hash=doc.text_hash,
        extraction_method="llm",
    )


def _to_float(value) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
