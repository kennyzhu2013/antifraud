from pathlib import Path

import pytest

from antifraud_agent.crawler import load_local_articles
from antifraud_agent.detection import CallRiskDetector
from antifraud_agent.extraction import extract_case
from antifraud_agent.store import CaseStore

SAMPLES = Path(__file__).parent.parent / "data" / "sample_articles"


@pytest.fixture()
def detector(tmp_path):
    store = CaseStore(tmp_path / "cases.db")
    for doc in load_local_articles(SAMPLES):
        case = extract_case(doc)
        assert case is not None
        store.upsert_case(case)
    assert store.count() == 5
    yield CallRiskDetector(store)
    store.close()


def test_high_risk_gongjianfa(detector):
    result = detector.detect(
        "喂，我是市公安局的，你的银行卡涉嫌洗钱，需要配合调查，"
        "这个案件是保密的，不要告诉家人，现在把钱转到我们的安全账户。"
    )
    assert result.risk_level == "high"
    assert result.fraud_type == "冒充公检法"
    assert "安全账户" in result.matched_signals
    assert result.similar_cases
    assert result.similar_cases[0]["fraud_type"] == "冒充公检法"
    assert "96110" in result.suggested_action


def test_medium_or_high_kefu(detector):
    result = detector.detect("您好，我是平台客服，您误开通了百万保障会员，不取消会影响征信，请开启屏幕共享配合操作。")
    assert result.risk_level in ("medium", "high")
    assert result.fraud_type == "冒充客服"


def test_low_risk_normal_call(detector):
    result = detector.detect("妈，我今晚加班，晚饭你们先吃，不用等我了。")
    assert result.risk_level == "low"
    assert result.risk_score < 0.4


def test_similar_case_retrieval(detector):
    result = detector.detect("有个导师带我炒股，说有内幕消息稳赚不赔，让我在他们平台充值入金。")
    assert result.fraud_type == "投资理财"
    top = result.similar_cases[0]
    assert top["fraud_type"] == "投资理财"
