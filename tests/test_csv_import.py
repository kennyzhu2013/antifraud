from pathlib import Path

import pytest

from antifraud_agent.csv_import import (
    ingest_csv,
    map_label,
    mojibake_ratio,
    read_csv_rows,
    scam_side,
    split_turns,
    transcript_to_case,
)
from antifraud_agent.detection import CallRiskDetector
from antifraud_agent.store import CaseStore

TRANSCRIPT_TOUZI = (
    "left:您好，我是恒某投资的客服，之前您在我们公司办理过投资产品。"
    "我们和上海证券有合作，现在开通绿色通道，导师在群里分享内幕消息，稳赚不赔，"
    "前期不收取任何费用，加一下微信13812345678拉您进官方福利群。"
    "right:好的，那我加一下。left:加完之后导师会带您充值入金，高收益的。"
)
TRANSCRIPT_GJF = (
    "left:我是市公安局的民警，你的银行卡涉嫌洗钱，需要配合调查，"
    "案件保密，不要告诉家人，把钱转账到安全账户。right:啊？我没有做过这种事啊。"
)

CSV_TEXT = (
    "data_id,content,comment\n"
    f"1001,{TRANSCRIPT_TOUZI},虚假投资\n"
    f"1002,{TRANSCRIPT_GJF},冒充公检法诈骗\n"
    "1003,left:喂你好，请问是物业吗？right:是的，您说。,正常通话\n"
)


def _write(tmp_path: Path, encoding: str) -> Path:
    p = tmp_path / f"data_{encoding}.csv"
    p.write_bytes(CSV_TEXT.encode(encoding))
    return p


@pytest.mark.parametrize("encoding", ["utf-8", "gb18030"])
def test_read_csv_encoding_detection(tmp_path, encoding):
    rows = read_csv_rows(_write(tmp_path, encoding))
    assert len(rows) == 3
    assert rows[0]["comment"] == "虚假投资"


def test_split_turns_and_scam_side():
    turns = split_turns(TRANSCRIPT_TOUZI)
    assert [s for s, _ in turns] == ["left", "right", "left"]
    assert scam_side(turns) == "left"


def test_map_label():
    assert map_label("虚假投资", "") == "投资理财"
    assert map_label("冒充公检法诈骗", "") == "冒充公检法"
    # 标签映射不到时退回内容关键词分类
    assert map_label("未知类型", TRANSCRIPT_GJF) == "冒充公检法"
    assert map_label("正常通话", "喂你好，请问是物业吗") is None


def test_transcript_to_case_offline():
    case = transcript_to_case(TRANSCRIPT_TOUZI, "虚假投资", "1001", "data.csv")
    assert case is not None
    assert case.fraud_type == "投资理财"
    assert case.confidence == 0.9
    assert case.extraction_method == "csv_labeled"
    assert case.source_url == "csv://data.csv#1001"
    # 话术来自骗子侧并完成脱敏
    assert case.fraud_script
    assert "13812345678" not in case.model_dump_json()
    assert any("内幕消息" in s for s in case.fraud_script)


def test_mojibake_detection():
    assert mojibake_ratio("锟斤拷锟斤拷投锟斤拷") > 0.2
    assert mojibake_ratio("正常的中文通话内容，没有乱码。") == 0.0


def test_ingest_csv_end_to_end(tmp_path):
    store = CaseStore(tmp_path / "cases.db")
    stats = ingest_csv(store, _write(tmp_path, "gb18030"))
    assert stats.total_rows == 3
    assert stats.ingested == 2          # 两条诈骗转写入库
    assert stats.unmapped == 1          # 正常通话被跳过
    assert stats.label_distribution == {"投资理财": 1, "冒充公检法": 1}

    # 重复导入全部去重
    stats2 = ingest_csv(store, _write(tmp_path, "utf-8"))
    assert stats2.ingested == 0
    assert stats2.duplicated == 2

    # 入库后的案例可被通话检测命中
    result = CallRiskDetector(store).detect("导师说有内幕消息，带我炒股稳赚不赔，让我充值入金")
    assert result.fraud_type == "投资理财"
    assert result.similar_cases[0]["fraud_type"] == "投资理财"
    store.close()


def test_corrupted_rows_skipped(tmp_path):
    corrupted = "data_id,content,comment\n1,锟斤拷锟斤拷投锟斤拷锟斤拷锟斤拷,锟斤拷投锟斤拷\n"
    p = tmp_path / "bad.csv"
    p.write_text(corrupted, encoding="utf-8")
    store = CaseStore(tmp_path / "cases.db")
    stats = ingest_csv(store, p)
    assert stats.corrupted == 1
    assert stats.ingested == 0
    store.close()
