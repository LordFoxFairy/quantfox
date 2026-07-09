import pandas as pd

from quantfox.data.valuation import market_valuation


def _fetcher():
    return pd.DataFrame({
        "date": ["2026-07-07", "2026-07-08"],
        "middlePETTM": [39.66, 38.76],
        "quantileInRecent10YearsMiddlePeTtm": [None, 0.64],
    })


def test_market_valuation_latest_with_percentile():
    v = market_valuation(fetcher=_fetcher)
    assert v["available"] is True
    assert v["date"] == "2026-07-08"
    assert v["percentile_10y"] == 0.64
    assert v["level"] == "偏贵"  # 0.6-0.8


def test_market_valuation_sorts_dates_and_normalizes_percent_units():
    def fetcher():
        return pd.DataFrame({
            "date": ["2026-07-08", "2026-07-09"],
            "middlePETTM": [38.76, 39.66],
            "quantileInRecent10YearsMiddlePeTtm": [0.64, 64.0],
        }).iloc[::-1]

    v = market_valuation(fetcher=fetcher)
    assert v["date"] == "2026-07-09"
    assert v["percentile_10y"] == 0.64
    assert v["level"] == "偏贵"


def test_market_valuation_levels():
    def f(pct):
        return lambda: pd.DataFrame({"date": ["2026-07-08"], "middlePETTM": [30.0],
                                     "quantileInRecent10YearsMiddlePeTtm": [pct]})

    assert market_valuation(fetcher=f(0.2))["level"] == "便宜"
    assert market_valuation(fetcher=f(0.5))["level"] == "中性"
    assert market_valuation(fetcher=f(0.9))["level"] == "贵"
