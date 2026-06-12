from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SAMPLES = Path(__file__).parent.parent / "data" / "sample_articles"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from antifraud_agent import api
    from antifraud_agent.config import settings

    monkeypatch.setattr(settings, "db_path", tmp_path / "cases.db")
    with TestClient(api.app) as c:
        # 通过内部 store 直接灌入样例案例
        from antifraud_agent.crawler import load_local_articles
        from antifraud_agent.extraction import extract_case

        for doc in load_local_articles(SAMPLES):
            api.store.upsert_case(extract_case(doc))
        yield c


def test_detect_endpoint(client):
    resp = client.post(
        "/detect",
        json={"transcript": "我是公安局的，你的银行卡涉嫌洗钱，要配合调查，案件保密不要告诉家人，把钱转账到安全账户。"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["risk_level"] == "high"
    assert body["fraud_type"] == "冒充公检法"


def test_detect_empty_rejected(client):
    assert client.post("/detect", json={"transcript": "  "}).status_code == 400


def test_stats_and_get_case(client):
    stats = client.get("/stats").json()
    assert stats["total"] == 5
    case_id = client.post("/detect", json={"transcript": "刷单做任务返佣金，先垫付"}).json()["similar_cases"][0]["case_id"]
    case = client.get(f"/cases/{case_id}").json()
    assert case["case_id"] == case_id
    assert client.get("/cases/not-exist").status_code == 404
