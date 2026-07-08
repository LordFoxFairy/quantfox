import pandas as pd

from money.percentile import price_percentile


def _series(vals):
    dates = pd.date_range("2020-01-01", periods=len(vals), freq="D").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in vals]})


def test_latest_is_highest():
    df = _series(list(range(1, 400)))  # 最新值最大
    r = price_percentile(df, years=1)
    assert r["price_pct"] is not None and r["price_pct"] > 0.99


def test_insufficient_returns_none():
    df = _series([1, 2, 3])
    assert price_percentile(df, years=1)["price_pct"] is None
