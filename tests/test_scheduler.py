import pytest

from ads_copilot.scheduler.cron import parse_cron


def test_parse_cron_daily_8am() -> None:
    out = parse_cron("0 8 * * *")
    assert out == {
        "minute": "0", "hour": "8", "day": "*", "month": "*", "day_of_week": "*",
    }


def test_parse_cron_complex() -> None:
    out = parse_cron("*/15 9-17 * * 1-5")
    assert out["minute"] == "*/15"
    assert out["hour"] == "9-17"
    assert out["day_of_week"] == "1-5"


def test_parse_cron_wrong_field_count() -> None:
    with pytest.raises(ValueError, match="5 fields"):
        parse_cron("0 8 * *")
    with pytest.raises(ValueError, match="5 fields"):
        parse_cron("0 8 * * * *")


def test_parse_cron_whitespace_tolerated() -> None:
    out = parse_cron("  0  8  *  *  *  ")
    assert out["hour"] == "8"
