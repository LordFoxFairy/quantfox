import math

import pandas as pd

from quantfox.forecast import forecast


def _df(vals):
    dates = pd.date_range("2016-01-04", periods=len(vals), freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in vals]})


def test_uptrend_high_positive_probability():
    # 单调上涨：任意持有期前瞻收益恒正 → p_positive=1，中位>0
    r = forecast(_df([100 + i for i in range(1000)]), horizons=(20, 60))
    h20 = r["horizons"]["20"]["all"]
    assert h20["p_positive"] == 1.0
    assert h20["median"] > 0
    assert "median" in h20 and "p10" in h20 and "p90" in h20


def test_structure_and_valuation_conditional():
    vals = [100 + 20 * math.sin(i / 40.0) for i in range(1500)]  # 均值回归
    r = forecast(_df(vals), horizons=(20, 120))
    assert r["current_valuation_pct"] is not None
    h = r["horizons"]["20"]
    assert "all" in h
    assert 0.0 <= h["all"]["p_positive"] <= 1.0
    # 估值条件化分布（可能有，样本够时）
    if "from_similar_valuation" in h:
        assert 0.0 <= h["from_similar_valuation"]["p_positive"] <= 1.0


def test_insufficient_sample_flagged():
    r = forecast(_df([1, 2, 3, 4, 5] * 10), horizons=(250,))  # 250 期前瞻几乎无样本
    assert "note" in r["horizons"]["250"]["all"] or r["horizons"]["250"]["all"]["n"] < 60
