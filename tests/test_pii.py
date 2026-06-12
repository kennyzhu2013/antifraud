from antifraud_agent import pii


def test_redact_phone():
    assert pii.redact("请拨打13912345678联系") == "请拨打[手机号]联系"


def test_redact_id_card():
    text = "身份证号430103198805124321已登记"
    assert "[身份证号]" in pii.redact(text)
    assert "430103" not in pii.redact(text)


def test_redact_bank_card():
    assert "[银行卡号]" in pii.redact("转入账户6217003810026584321")


def test_redact_masked_name():
    assert "王某" not in pii.redact("市民王某接到电话。")


def test_contains_pii():
    assert pii.contains_pii("打 13912345678") == ["手机号"]
    assert pii.contains_pii("正常文本没有敏感信息") == []


def test_redact_keeps_normal_numbers():
    text = "被骗5.8万元，损失58000元"
    assert pii.redact(text) == text
