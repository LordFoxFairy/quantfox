import numpy as np
import pandas as pd

from money.metrics import compute_metrics


def _df(vals):
    dates = pd.date_range("2022-01-03", periods=len(vals), freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in vals]})


def test_short_series_returns_none_metrics():
    m = compute_metrics(_df([1, 2, 3, 4, 5]))
    assert m["sharpe"] is None
    assert m["max_drawdown"] is None
    assert m["returns"]["1w"] is None


def test_steady_uptrend_positive_metrics():
    # 每日 +0.1% 稳定上涨：正夏普、正 CAGR、回撤≈0、胜率=1
    vals = [100.0 * (1.001 ** i) for i in range(300)]
    m = compute_metrics(_df(vals))
    assert m["cagr"] > 0
    assert m["sharpe"] > 0
    assert m["win_rate"] == 1.0
    assert m["max_drawdown"] >= -1e-9  # 单调上涨无回撤
    assert m["ann_vol"] is not None and m["ann_vol"] >= 0


def test_drawdown_detected():
    # 先涨后腰斩 → 最大回撤约 -50%
    up = [100.0 + i for i in range(150)]   # 100→249
    down = [249.0 * (0.5 ** (i / 149)) for i in range(150)]  # 腰斩
    m = compute_metrics(_df(up + down))
    assert m["max_drawdown"] < -0.4


def test_var_is_negative_for_volatile():
    rng = np.random.default_rng(0)
    vals = [100.0]
    for _ in range(400):
        vals.append(vals[-1] * (1 + rng.normal(0, 0.02)))
    m = compute_metrics(_df(vals))
    assert m["var95"] is not None and m["var95"] < 0
    assert m["cvar95"] <= m["var95"]  # 尾部均值不高于分位点
