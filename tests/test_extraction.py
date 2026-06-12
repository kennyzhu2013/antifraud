from pathlib import Path

from antifraud_agent.crawler import load_local_articles
from antifraud_agent.extraction import extract_case
from antifraud_agent.extraction.rule_extractor import classify_fraud_type, rule_extract

SAMPLES = Path(__file__).parent.parent / "data" / "sample_articles"


def test_classify_fraud_type():
    fraud_type, hits, score = classify_fraud_type("对方自称公安，说我涉嫌洗钱，要求转到安全账户配合调查")
    assert fraud_type == "冒充公检法"
    assert len(hits) >= 3
    assert score > 0.5


def test_rule_extract_samples():
    docs = load_local_articles(SAMPLES)
    assert len(docs) == 5
    expected_types = {"冒充公检法", "刷单返利", "冒充客服", "投资理财", "冒充熟人"}
    extracted_types = set()
    for doc in docs:
        case = rule_extract(doc)
        assert case is not None, f"样例未被识别: {doc.title}"
        extracted_types.add(case.fraud_type)
        # 入库前必须无 PII 残留
        assert "13912345678" not in case.model_dump_json()
        assert "430103198805124321" not in case.model_dump_json()
    assert extracted_types == expected_types


def test_extract_case_pipeline_offline():
    """无 LLM key 时 extract_case 自动走规则兜底并通过校验。"""
    docs = load_local_articles(SAMPLES)
    case = extract_case(docs[0])
    assert case is not None
    assert case.extraction_method == "rule"
    assert case.fraud_type == "冒充公检法"
    assert case.loss_amount == 58000
    assert case.recommended_warning


def test_non_fraud_article_rejected():
    from antifraud_agent.schemas import RawDocument

    doc = RawDocument(url="local://x", text="今天天气晴朗，本市举办了马拉松比赛，共有三千名选手参加。" * 3)
    assert extract_case(doc) is None
