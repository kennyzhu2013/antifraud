"""PII 脱敏：在入库前抹掉手机号、身份证号、银行卡号、邮箱、具体姓名等敏感信息。

策略：正则替换为占位符，保留语义（例如 [手机号]），不破坏话术结构。
"""

from __future__ import annotations

import re

# 大陆手机号（11 位，1 开头），容忍 +86 前缀与分隔符
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d[-\s]?\d{4}[-\s]?\d{4}(?!\d)")
# 固话：区号-号码
_LANDLINE_RE = re.compile(r"(?<!\d)0\d{2,3}-\d{7,8}(?!\d)")
# 18 位身份证（含 X 校验位）与 15 位旧证
_ID_CARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)|(?<!\d)\d{15}(?!\d)")
# 银行卡：13-19 位连续数字（在身份证之后匹配，避免冲突）
_BANK_CARD_RE = re.compile(r"(?<!\d)\d{13,19}(?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 新闻通稿常见写法：姓 + 某/某某/X X，如 “王某”“李某某”“张XX”
_MASKED_NAME_RE = re.compile(r"[\u4e00-\u9fa5]{1}(某某|某|[Xx×]{1,2})(?=[^\u4e00-\u9fa5]|[\u4e00-\u9fa5])")

_REPLACEMENTS: list[tuple[re.Pattern, str]] = [
    (_ID_CARD_RE, "[身份证号]"),
    (_PHONE_RE, "[手机号]"),
    (_LANDLINE_RE, "[固定电话]"),
    (_BANK_CARD_RE, "[银行卡号]"),
    (_EMAIL_RE, "[邮箱]"),
]


def redact(text: str) -> str:
    """对文本做 PII 脱敏，返回替换后的文本。"""
    for pattern, placeholder in _REPLACEMENTS:
        text = pattern.sub(placeholder, text)
    # “王某/李某某”属于已脱敏写法，统一归一为 [当事人]，避免残留可关联信息
    text = _MASKED_NAME_RE.sub("[当事人]", text)
    return text


def contains_pii(text: str) -> list[str]:
    """检查文本中残留的 PII 类型，用于 Validation Agent 的二次校验。"""
    found = []
    if _ID_CARD_RE.search(text):
        found.append("身份证号")
    if _PHONE_RE.search(text):
        found.append("手机号")
    if _BANK_CARD_RE.search(text):
        found.append("银行卡号")
    if _EMAIL_RE.search(text):
        found.append("邮箱")
    return found
