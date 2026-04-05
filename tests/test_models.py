from datetime import date

import pytest

from ads_copilot.models import DateRange, Metrics


def test_daterange_validates_order() -> None:
    with pytest.raises(ValueError):
        DateRange(start=date(2026, 4, 10), end=date(2026, 4, 1))


def test_metrics_derived_values() -> None:
    m = Metrics(
        impressions=1000, clicks=50, cost_minor=75_000_000, conversions=5,
        conversion_value_minor=500_000_000,
    )
    assert m.ctr == pytest.approx(0.05)
    assert m.cpc_minor == pytest.approx(1_500_000)
    assert m.cpa_minor == pytest.approx(15_000_000)
    assert m.roas == pytest.approx(500_000_000 / 75_000_000)


def test_metrics_zero_safe() -> None:
    m = Metrics()
    assert m.ctr == 0
    assert m.cpc_minor == 0
    assert m.cpa_minor == 0
    assert m.roas == 0
