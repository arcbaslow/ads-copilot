from ads_copilot.connectors.yandex_direct import _parse_tsv, _int, _float


def test_parse_tsv_basic() -> None:
    text = "CampaignId\tImpressions\tCost\n123\t1000\t5000000\n"
    rows = _parse_tsv(text)
    assert rows == [{"CampaignId": "123", "Impressions": "1000", "Cost": "5000000"}]


def test_parse_tsv_strips_bom() -> None:
    text = "\ufeffQuery\tClicks\nцветы купить\t12\n"
    rows = _parse_tsv(text)
    assert rows[0]["Query"] == "цветы купить"
    assert rows[0]["Clicks"] == "12"


def test_parse_tsv_empty() -> None:
    assert _parse_tsv("") == []
    assert _parse_tsv("   \n") == []


def test_int_handles_dashes_and_nulls() -> None:
    assert _int(None) == 0
    assert _int("") == 0
    assert _int("--") == 0
    assert _int("42") == 42
    assert _int("42.7") == 42


def test_float_handles_nulls() -> None:
    assert _float(None) == 0.0
    assert _float("--") == 0.0
    assert _float("3.14") == 3.14
