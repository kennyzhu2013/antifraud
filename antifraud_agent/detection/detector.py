"""通话风险检测：规则初筛 + 相似案例向量检索 + （可选）LLM 综合研判。

输入为 ASR 转写后的通话文本片段。实时场景下按滑动窗口（每 5-10 秒）反复调用即可。
最终风险分 = 0.45 * 规则分 + 0.35 * 相似案例分 + 0.20 * LLM 分（无 LLM 时按比例归一）。
"""

from __future__ import annotations

import logging

from ..config import settings
from ..llm import chat_json, llm_available
from ..schemas import DetectionResult, FraudCase
from ..store import CaseStore
from .rules import rule_score

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM = """你是通话反诈风险研判助手。用户提供一段通话转写文本和检索到的相似历史诈骗案例。
请判断该通话是否疑似诈骗，输出严格 JSON：
{"score": 0.0, "fraud_type": "string|null", "reason": "50字以内研判理由"}
score 为 0-1 的风险分。不要编造文本中不存在的内容。"""


class CallRiskDetector:
    def __init__(self, store: CaseStore):
        self.store = store

    def detect(self, transcript: str) -> DetectionResult:
        # 1) 规则初筛
        r_score, rule_type, matched_signals = rule_score(transcript)

        # 2) 向量检索相似案例
        similar = self.store.search_similar(transcript, top_k=settings.top_k_similar)
        sim_score = similar[0][1] if similar else 0.0
        sim_type = similar[0][0].fraud_type if similar else None

        # 3) LLM 综合研判（可选）
        llm_score, llm_type, llm_reason = self._llm_judge(transcript, [c for c, _ in similar[:3]])

        # 4) 加权融合
        if llm_score is not None:
            score = 0.45 * r_score + 0.35 * sim_score + 0.20 * llm_score
        else:
            score = (0.45 * r_score + 0.35 * sim_score) / 0.80

        fraud_type = llm_type or rule_type or (sim_type if sim_score > 0.35 else None)
        level = self._level(score)

        reason = llm_reason or self._build_reason(level, fraud_type, matched_signals, similar)
        return DetectionResult(
            risk_level=level,
            risk_score=round(score, 3),
            fraud_type=fraud_type,
            matched_signals=matched_signals,
            similar_cases=[
                {
                    "case_id": c.case_id,
                    "title": c.title,
                    "fraud_type": c.fraud_type,
                    "similarity": round(s, 3),
                }
                for c, s in similar
            ],
            reason=reason,
            suggested_action=self._action(level, fraud_type, similar),
        )

    def _llm_judge(self, transcript: str, cases: list[FraudCase]) -> tuple[float | None, str | None, str]:
        if not llm_available():
            return None, None, ""
        context = "\n".join(
            f"- [{c.fraud_type}] {c.summary} 风险信号: {', '.join(c.key_risk_signals[:5])}" for c in cases
        )
        data = chat_json(_JUDGE_SYSTEM, f"通话文本：\n{transcript}\n\n相似历史案例：\n{context or '（无）'}")
        if not data:
            return None, None, ""
        try:
            return max(0.0, min(float(data.get("score", 0)), 1.0)), data.get("fraud_type"), data.get("reason", "")
        except (TypeError, ValueError):
            return None, None, ""

    def _level(self, score: float) -> str:
        if score >= settings.high_risk_threshold:
            return "high"
        if score >= settings.medium_risk_threshold:
            return "medium"
        return "low"

    @staticmethod
    def _build_reason(level: str, fraud_type: str | None, signals: list[str], similar) -> str:
        if level == "low":
            return "未发现明显诈骗特征。"
        parts = []
        if fraud_type:
            parts.append(f"通话内容与“{fraud_type}”类诈骗特征吻合")
        if signals:
            parts.append(f"命中风险信号：{'、'.join(signals[:6])}")
        if similar and similar[0][1] > 0.3:
            parts.append(f"与历史案例《{similar[0][0].title}》高度相似")
        return "；".join(parts) + "。"

    @staticmethod
    def _action(level: str, fraud_type: str | None, similar) -> str:
        if level == "high":
            warning = ""
            for case, _ in similar:
                if case.fraud_type == fraud_type and case.recommended_warning:
                    warning = case.recommended_warning
                    break
            return f"立即提醒用户警惕，不要转账或泄露验证码，建议挂断后拨打 96110 核实。{warning}".strip()
        if level == "medium":
            return "提示用户注意通话对方身份，涉及钱款务必多渠道核实。"
        return "无需干预，继续监测。"
