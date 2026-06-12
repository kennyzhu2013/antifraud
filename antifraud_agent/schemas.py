"""统一数据模型：案例 schema 与检测输出 schema。"""

from __future__ import annotations

import hashlib
import uuid
from typing import Optional

from pydantic import BaseModel, Field

FRAUD_TYPES = [
    "冒充公检法",
    "冒充客服",
    "刷单返利",
    "投资理财",
    "虚假贷款",
    "杀猪盘",
    "裸聊敲诈",
    "中奖诈骗",
    "快递理赔",
    "冒充熟人",
    "AI换脸变声",
    "虚假购物",
    "其他",
]


class RawDocument(BaseModel):
    """爬虫产出的原始文档（已清洗正文）。"""

    url: str
    source_name: str = ""
    title: str = ""
    publish_date: Optional[str] = None
    text: str
    fetched_at: str = ""

    @property
    def text_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


class VictimProfile(BaseModel):
    age_group: Optional[str] = None
    occupation: Optional[str] = None
    gender: Optional[str] = None


class MoneyFlow(BaseModel):
    payment_method: Optional[str] = None
    amount: Optional[float] = None


class FraudCase(BaseModel):
    """结构化诈骗案例（案例库的一行）。"""

    case_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    source_url: str = ""
    source_name: str = ""
    publish_date: Optional[str] = None
    fraud_type: str = "其他"
    scenario: str = ""
    victim_profile: VictimProfile = Field(default_factory=VictimProfile)
    fraud_script: list[str] = Field(default_factory=list)
    key_risk_signals: list[str] = Field(default_factory=list)
    money_flow: MoneyFlow = Field(default_factory=MoneyFlow)
    loss_amount: Optional[float] = None
    summary: str = ""
    recommended_warning: str = ""
    confidence: float = 0.5
    raw_text_hash: str = ""
    extraction_method: str = "rule"  # rule / llm / csv_labeled

    def embedding_text(self) -> str:
        """用于向量化的文本：聚合最有判别力的字段。"""
        parts = [self.fraud_type, self.scenario, self.summary]
        parts += self.fraud_script + self.key_risk_signals
        return "\n".join(p for p in parts if p)


class DetectionResult(BaseModel):
    """通话检测输出。"""

    risk_level: str = "low"  # low / medium / high
    risk_score: float = 0.0
    fraud_type: Optional[str] = None
    matched_signals: list[str] = Field(default_factory=list)
    similar_cases: list[dict] = Field(default_factory=list)  # [{case_id, title, fraud_type, similarity}]
    reason: str = ""
    suggested_action: str = ""
