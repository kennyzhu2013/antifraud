"""从人工标注的通话转写 CSV 中提取案例。

适配格式：每行一通电话，content 列为 ASR 转写文本（可含 left:/right: 说话人标记），
comment 列为人工审核的诈骗类型。人工标签可信度高，直接作为 fraud_type（置信度 0.9），
话术与风险信号从转写文本中按知识库抽取；可选用 LLM 生成摘要。

同时处理两类常见脏数据：
- 编码不确定：自动在 UTF-8 / GB18030 间探测；
- 乱码损坏：统计替换符占比，超阈值的行跳过并计数（典型如 GBK 文件被按 UTF-8 误转码后出现的“锟斤拷”）。
"""

from __future__ import annotations

import csv
import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import pii
from .knowledge import FRAUD_KNOWLEDGE, GENERIC_HIGH_RISK_PHRASES
from .llm import chat_json
from .schemas import FraudCase, MoneyFlow
from .extraction.rule_extractor import classify_fraud_type

logger = logging.getLogger(__name__)

# 人工标签 -> 案例库 fraud_type。按顺序匹配子串，可按自己业务的标签体系扩充。
LABEL_MAP: list[tuple[str, str]] = [
    ("公检法", "冒充公检法"),
    ("冒充客服", "冒充客服"),
    ("客服", "冒充客服"),
    ("刷单", "刷单返利"),
    ("返利", "刷单返利"),
    ("投资", "投资理财"),
    ("理财", "投资理财"),
    ("荐股", "投资理财"),
    ("贷款", "虚假贷款"),
    ("杀猪盘", "杀猪盘"),
    ("交友", "杀猪盘"),
    ("裸聊", "裸聊敲诈"),
    ("中奖", "中奖诈骗"),
    ("快递", "快递理赔"),
    ("理赔", "快递理赔"),
    ("冒充熟人", "冒充熟人"),
    ("冒充领导", "冒充熟人"),
    ("换脸", "AI换脸变声"),
    ("变声", "AI换脸变声"),
    ("购物", "虚假购物"),
]

# 乱码判定：替换符（U+FFFD）与“锟”字符合计占比超过该值认为该行已损坏
MOJIBAKE_RATIO_THRESHOLD = 0.05

_SPEAKER_RE = re.compile(r"(left|right)\s*[:：]")
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;\n]")

_SUMMARY_SYSTEM = """你是反诈案例整理助手。用户提供一通诈骗电话的转写文本和人工标注的诈骗类型。
请输出严格 JSON：
{"scenario": "一句话概括作案场景", "summary": "100字以内案情摘要",
 "fraud_script": ["骗子的关键话术，逐条引用原文"], "recommended_warning": "一句防范提示"}
不要编造转写中不存在的内容，不要输出真实姓名、电话、卡号。"""


@dataclass
class CsvIngestStats:
    total_rows: int = 0
    ingested: int = 0
    duplicated: int = 0
    corrupted: int = 0
    unmapped: int = 0
    label_distribution: dict[str, int] = field(default_factory=dict)


def read_csv_rows(path: Path) -> list[dict]:
    """读 CSV，自动探测编码（BOM/UTF-8/GB18030），返回 dict 行列表。"""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(encoding)
            logger.info("CSV 编码识别为 %s", encoding)
            return list(csv.DictReader(text.splitlines()))
        except UnicodeDecodeError:
            continue
    # 都失败时用 GB18030 容错读取，损坏行交给 mojibake_ratio 过滤
    logger.warning("无法确定编码，按 GB18030 容错读取: %s", path)
    return list(csv.DictReader(raw.decode("gb18030", errors="replace").splitlines()))


def mojibake_ratio(text: str) -> float:
    """替换符占比。'锟' 是 GBK 文件被按 UTF-8 误转码后的典型残留。"""
    if not text:
        return 1.0
    bad = text.count("\ufffd") + text.count("锟")
    return bad / len(text)


def map_label(label: str, content: str) -> str | None:
    """人工标签 -> fraud_type。标签映射不到时退回到内容关键词分类。"""
    label = (label or "").strip()
    for needle, fraud_type in LABEL_MAP:
        if needle in label:
            return fraud_type
    fraud_type, hits, _ = classify_fraud_type(content)
    if fraud_type != "其他" and len(hits) >= 2:
        return fraud_type
    return None


def split_turns(content: str) -> list[tuple[str, str]]:
    """按 left:/right: 把转写拆成 (speaker, text) 轮次；无标记时整体视为单轮。"""
    matches = list(_SPEAKER_RE.finditer(content))
    if not matches:
        return [("unknown", content.strip())]
    turns = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        text = content[m.end() : end].strip().strip(",，")
        if text:
            turns.append((m.group(1), text))
    return turns


def scam_side(turns: list[tuple[str, str]]) -> str:
    """判断哪一侧是骗子：风险关键词命中多的一侧；打平取说话字数多的一侧。"""
    all_keywords = [kw for kb in FRAUD_KNOWLEDGE.values() for kw in kb["keywords"]] + GENERIC_HIGH_RISK_PHRASES
    score: dict[str, int] = {}
    chars: dict[str, int] = {}
    for speaker, text in turns:
        score[speaker] = score.get(speaker, 0) + sum(1 for kw in all_keywords if kw in text)
        chars[speaker] = chars.get(speaker, 0) + len(text)
    if not score:
        return "unknown"
    return max(score, key=lambda s: (score[s], chars[s]))


def extract_scripts(scam_text: str, fraud_type: str, max_items: int = 8) -> list[str]:
    """从骗子侧文本中抽取命中风险词的句子作为话术。"""
    keywords = FRAUD_KNOWLEDGE.get(fraud_type, {}).get("keywords", []) + GENERIC_HIGH_RISK_PHRASES
    scripts = []
    for sentence in _SENTENCE_SPLIT_RE.split(scam_text):
        s = sentence.strip()
        if 6 <= len(s) <= 80 and any(kw in s for kw in keywords):
            scripts.append(s)
        if len(scripts) >= max_items:
            break
    return scripts


def transcript_to_case(content: str, label: str, row_id: str, source: str) -> FraudCase | None:
    """单行转写 -> FraudCase。无法判定类型时返回 None。"""
    content = pii.redact(content.strip())
    if not content:
        return None
    fraud_type = map_label(label, content)
    if fraud_type is None:
        return None

    turns = split_turns(content)
    scammer = scam_side(turns)
    scam_text = "。".join(t for sp, t in turns if sp == scammer)

    kb = FRAUD_KNOWLEDGE.get(fraud_type, {})
    scripts = extract_scripts(scam_text or content, fraud_type)
    _, keyword_hits, _ = classify_fraud_type(content)
    signals = list(dict.fromkeys(kb.get("risk_signals", []) + keyword_hits))[:10]

    scenario = (scam_text or content)[:100].replace("\n", " ")
    summary = scenario
    warning = kb.get("warning", "")

    # 可选：LLM 生成更好的摘要与话术（失败自动用上面的规则结果）
    data = chat_json(_SUMMARY_SYSTEM, f"人工标注类型：{label}\n\n通话转写：\n{content[:4000]}")
    if data:
        scenario = data.get("scenario") or scenario
        summary = data.get("summary") or summary
        warning = data.get("recommended_warning") or warning
        llm_scripts = [pii.redact(s) for s in (data.get("fraud_script") or []) if isinstance(s, str)]
        if llm_scripts:
            scripts = llm_scripts

    return FraudCase(
        title=f"{fraud_type}通话案例 {row_id}".strip(),
        source_url=f"csv://{source}#{row_id}",
        source_name="人工标注通话转写",
        fraud_type=fraud_type,
        scenario=scenario,
        fraud_script=scripts,
        key_risk_signals=signals,
        money_flow=MoneyFlow(),
        summary=summary,
        recommended_warning=warning,
        confidence=0.9,  # 人工审核标签，置信度高于自动抽取
        raw_text_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        extraction_method="csv_labeled",
    )


def ingest_csv(
    store,
    path: Path,
    content_col: str = "content",
    label_col: str = "comment",
    id_col: str = "data_id",
) -> CsvIngestStats:
    """整个 CSV 入库，返回统计。store 为 CaseStore。"""
    stats = CsvIngestStats()
    rows = read_csv_rows(path)
    stats.total_rows = len(rows)

    for i, row in enumerate(rows):
        content = (row.get(content_col) or "").strip()
        label = (row.get(label_col) or "").strip()
        row_id = (row.get(id_col) or str(i)).strip()

        if mojibake_ratio(content) > MOJIBAKE_RATIO_THRESHOLD:
            stats.corrupted += 1
            continue

        case = transcript_to_case(content, label, row_id, path.name)
        if case is None:
            stats.unmapped += 1
            continue

        if store.upsert_case(case):
            stats.ingested += 1
            stats.label_distribution[case.fraud_type] = stats.label_distribution.get(case.fraud_type, 0) + 1
        else:
            stats.duplicated += 1

    if stats.corrupted:
        logger.warning(
            "%d/%d 行因乱码被跳过。若原文件为 GBK/GB2312，请勿用 UTF-8 强转，直接上传原始文件即可（本工具会自动识别编码）。",
            stats.corrupted,
            stats.total_rows,
        )
    return stats
