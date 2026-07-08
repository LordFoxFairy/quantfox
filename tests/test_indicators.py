import pandas as pd

from money.indicators import compute_indicators


def _series(vals):
    dates = pd.date_range("2023-01-01", periods=len(vals), freq="D").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in vals]})


def test_uptrend_alignment_bullish():
    df = _series([i for i in range(1, 121)])  # 单调上升
    ind = compute_indicators(df)
    assert ind["ma"]["alignment"] == "多头"
    assert ind["returns"]["1m"] > 0
    assert 0 <= ind["rsi14"] <= 100


def test_short_series_fills_none():
    df = _series([1, 2, 3])  # 太短
    ind = compute_indicators(df)
    assert ind["ma"]["ma60"] is None
    assert ind["returns"]["1y"] is None
