from pathlib import Path

import pandas as pd

from quantfox.data.prices import load_prices
from quantfox.data.resolve import Asset

FX = Path(__file__).parent / "fixtures"


def _fund_fetcher(asset):
    return pd.read_json(FX / "fund_nav_sample.json")


def _gold_fetcher(asset):
    return pd.read_json(FX / "gold_sample.json")


def test_load_fund_prices_shape():
    a = Asset(symbol="501018", type="otc_fund")
    df = load_prices(a, fetcher=_fund_fetcher)
    assert list(df.columns) == ["date", "value"]
    assert df["date"].is_monotonic_increasing
    assert df["value"].dtype == float
    assert len(df) > 0
    assert df["date"].iloc[0].startswith("202")


def test_load_fund_prices_prefers_cumulative_nav_when_available():
    raw = pd.DataFrame({
        "净值日期": ["2024-01-01", "2024-01-02"],
        "单位净值": [1.0, 0.9],
        "累计净值": [1.0, 1.1],
    })
    a = Asset(symbol="501018", type="otc_fund")
    df = load_prices(a, fetcher=lambda asset: raw)
    assert df["value"].tolist() == [1.0, 1.1]


def test_load_gold_prices_has_ohlc():
    a = Asset(symbol="Au99.99", type="gold")
    df = load_prices(a, fetcher=_gold_fetcher)
    assert df.columns[:2].tolist() == ["date", "value"]
    # 黄金应带 OHLC，用于 ATR/KDJ 等需要最高最低价的指标
    assert "high" in df.columns and "low" in df.columns
    assert df["value"].dtype == float
    assert len(df) > 0
    assert df["date"].iloc[0].startswith("202")


def test_fund_has_no_ohlc():
    a = Asset(symbol="501018", type="otc_fund")
    df = load_prices(a, fetcher=_fund_fetcher)
    assert "high" not in df.columns
