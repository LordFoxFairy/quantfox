import math

import pandas as pd

from quantfox.backtest import backtest


def _df(vals):
    dates = pd.date_range("2016-01-01", periods=len(vals), freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in vals]})


def test_insufficient_data():
    r = backtest(_df(list(range(1, 50))))
    assert r["n_windows"] == 0


def test_backtest_structure_and_point_in_time():
    # 正弦均值回归序列，估值规则应产生一些买/避
    vals = [100 + 20 * math.sin(i / 30.0) for i in range(1200)]
    r = backtest(_df(vals), rule="valuation", horizon=20)
    assert r["n_windows"] > 0
    assert 0.0 <= r["base_up_rate"] <= 1.0
    assert set(r["buy"].keys()) == {"n", "hit_rate", "avg_net_return", "edge_vs_baserate"}
    assert "total_return" in r["strategy"] and "max_drawdown_windowed" in r["strategy"]
    assert "asset_max_drawdown_daily" in r["strategy"]
    assert "buy_and_hold_return" in r


def test_monotonic_uptrend_baserate_one():
    # 单调上涨：前瞻收益恒正 → 基率=1；估值规则几乎不买（一直高分位）
    r = backtest(_df([100 + i for i in range(1200)]), rule="valuation", horizon=20)
    assert r["base_up_rate"] == 1.0
    # 趋势规则在单调上涨里会一直买，命中率高但 edge≈0（只是跟涨）
    rt = backtest(_df([100 + i for i in range(1200)]), rule="trend", horizon=20)
    if rt["buy"]["hit_rate"] is not None:
        assert rt["buy"]["edge_vs_baserate"] <= 0.01


def test_backtest_enters_after_signal_day_close():
    vals = [100.0] * 61 + [200.0] * 30
    r = backtest(_df(vals), rule="trend", horizon=20, warmup=60, asset_type="gold")
    assert r["buy"]["n"] == 1
    assert r["buy"]["avg_net_return"] == -0.004
    assert r["strategy"]["total_return"] == -0.004
    assert r["strategy"]["sharpe"] is None


def test_baserate_uses_same_executable_windows_as_strategy():
    vals = [100.0 + i for i in range(61)] + [160.0 - i for i in range(40)]
    r = backtest(_df(vals), rule="trend", horizon=10, warmup=60, asset_type="gold")
    assert r["base_up_rate"] == 0.0
