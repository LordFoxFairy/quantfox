import pandas as pd

from quantfox.indicators import compute_indicators


def _series(vals):
    dates = pd.date_range("2023-01-01", periods=len(vals), freq="D").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in vals]})


def _ohlc(vals):
    df = _series(vals)
    df["high"] = df["value"] * 1.01
    df["low"] = df["value"] * 0.99
    return df


def test_uptrend_alignment_bullish():
    df = _series(list(range(1, 121)))
    ind = compute_indicators(df)
    assert ind["ma"]["alignment"] == "多头"
    for k in ("rsi6", "rsi12", "rsi24"):
        assert 0 <= ind["rsi"][k] <= 100
    assert ind["ema"]["ema12"] is not None


def test_short_series_fills_none():
    ind = compute_indicators(_series([1, 2, 3]))
    assert ind["ma"]["ma60"] is None
    assert ind["ma"]["ma250"] is None
    assert ind["macd"]["dif"] is None


def test_close_only_has_no_ohlc_indicators():
    ind = compute_indicators(_series(list(range(1, 60))))
    assert ind["ohlc"]["available"] is False
    assert ind["ohlc"]["atr14"] is None


def test_gold_ohlc_indicators_computed():
    ind = compute_indicators(_ohlc(list(range(1, 60))))
    assert ind["ohlc"]["available"] is True
    assert ind["ohlc"]["atr14"] is not None
    assert ind["ohlc"]["kdj"] is not None
    assert ind["ohlc"]["cci14"] is not None
    assert ind["ohlc"]["wr14"] is not None


def test_price_levels():
    ind = compute_indicators(_series(list(range(1, 300))))
    pl = ind["price_levels"]
    assert pl["high_52w"] >= pl["low_52w"]
    assert 0 <= pl["pct_position"] <= 1
