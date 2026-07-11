import numpy as np
import pandas as pd

from quantfox.market import INDICES, build_market_view

_DATES = pd.date_range("2015-01-01", periods=1200, freq="B").astype(str)

_SECTORS = [
    {"code": "1", "name": "半导体", "r_1m": 0.20, "r_3m": 0.30},
    {"code": "2", "name": "白酒", "r_1m": 0.15, "r_3m": 0.05},
    {"code": "3", "name": "白色家电", "r_1m": 0.10, "r_3m": 0.01},
    {"code": "4", "name": "保险", "r_1m": 0.02, "r_3m": -0.01},
    {"code": "5", "name": "包装印刷", "r_1m": -0.01, "r_3m": -0.02},
    {"code": "6", "name": "电池", "r_1m": -0.05, "r_3m": -0.03},
    {"code": "7", "name": "电机", "r_1m": -0.10, "r_3m": -0.08},
    {"code": "8", "name": "地产", "r_1m": -0.18, "r_3m": -0.20},
]


def _hist(seed, trend, n=1200):
    rng = np.random.default_rng(seed)
    steps = rng.normal(trend, 0.01, n)
    values = 100 * np.cumprod(1 + steps)
    return pd.DataFrame({"date": _DATES, "value": values})


def _pe(seed, target_pct, n=1200):
    rng = np.random.default_rng(seed)
    values = rng.uniform(0, 1, n)
    values[-1] = np.quantile(values, target_pct)
    dates = pd.date_range("2015-01-01", periods=n, freq="B").astype(str)
    return pd.DataFrame({"date": dates, "value": values})


def _fetchers(trend=0.001, target_pct=0.55, sectors=_SECTORS, breadth=0.62):
    hist_map = {code: _hist(seed=i, trend=trend) for i, (code, _) in enumerate(INDICES)}
    pe_map = {code: _pe(seed=i + 100, target_pct=target_pct) for i, (code, _) in enumerate(INDICES)}
    return {
        "index_hist": lambda code: hist_map[code],
        "index_pe": lambda code: pe_map[code],
        "breadth": lambda: breadth,
        "sector_momentum": lambda: sectors,
    }


def test_full_success_has_regime_line_and_three_data_blocks():
    view = build_market_view(_fetchers())

    assert len(view["indices"]) == len(INDICES)
    for entry in view["indices"]:
        assert entry["pe_percentile_10y"] is not None
        assert entry["r_20"] is not None
        assert entry["r_60"] is not None
        assert entry["ma20_gt_ma60"] is not None

    assert view["breadth"] == 0.62

    assert [s["name"] for s in view["sectors"]["top"]] == ["半导体", "白酒", "白色家电", "保险", "包装印刷"]
    assert [s["name"] for s in view["sectors"]["bottom"]] == ["地产", "电机", "电池", "包装印刷", "保险"]

    assert view["health"]["healthy"] is True
    # 成功也要记账：5 指数（hist+PE 双成功）+ breadth + sectors = 7 条 ok
    assert view["health"]["ok"] == 7
    assert view["health"]["failed"] == 0
    # detail 只放 stale+failed，ok 项不进 detail
    assert view["health"]["detail"] == []
    assert "估值" in view["regime_line"]
    assert "半导体/白酒" in view["regime_line"]


def test_single_index_fetcher_raises_health_detail_others_fine():
    fetchers = _fetchers()
    good_hist = fetchers["index_hist"]

    def flaky_hist(code):
        if code == "000300":
            raise RuntimeError("接口不可用")
        return good_hist(code)

    fetchers["index_hist"] = flaky_hist

    view = build_market_view(fetchers)

    hs300 = next(e for e in view["indices"] if e["code"] == "000300")
    assert hs300["r_20"] is None
    assert hs300["r_60"] is None
    assert hs300["ma20_gt_ma60"] is None
    # 估值块不受这只指数日线失败影响
    assert hs300["pe_percentile_10y"] is not None

    others = [e for e in view["indices"] if e["code"] != "000300"]
    assert len(others) == 4
    for e in others:
        assert e["r_20"] is not None
        assert e["ma20_gt_ma60"] is not None

    assert view["health"]["healthy"] is False
    assert view["health"]["failed"] >= 1
    assert any("日线不可用" in d["note"] for d in view["health"]["detail"])


def test_breadth_and_sectors_none_abstain_with_health_lines():
    fetchers = _fetchers()
    fetchers["breadth"] = lambda: None
    fetchers["sector_momentum"] = lambda: None

    view = build_market_view(fetchers)

    assert view["breadth"] is None
    assert view["sectors"] == {"top": [], "bottom": []}
    assert "热点" not in view["regime_line"]

    assert view["health"]["healthy"] is False
    notes = [d["note"] for d in view["health"]["detail"]]
    assert "宽度不可用" in notes
    assert "行业轮动不可用" in notes


def test_short_pe_series_abstains_that_indexs_valuation_only():
    fetchers = _fetchers()
    good_pe = fetchers["index_pe"]
    short_pe = _pe(seed=999, target_pct=0.5, n=500)

    def flaky_pe(code):
        if code == "000300":
            return short_pe
        return good_pe(code)

    fetchers["index_pe"] = flaky_pe

    view = build_market_view(fetchers)

    hs300 = next(e for e in view["indices"] if e["code"] == "000300")
    assert hs300["pe_percentile_10y"] is None
    # 动量块不受这只指数估值弃权影响
    assert hs300["r_20"] is not None

    others = [e for e in view["indices"] if e["code"] != "000300"]
    for e in others:
        assert e["pe_percentile_10y"] is not None

    assert view["health"]["healthy"] is False
    assert any("估值弃权" in d["note"] for d in view["health"]["detail"])


def test_valuation_label_thresholds():
    expensive = build_market_view(_fetchers(target_pct=0.9))
    assert "整体估值偏贵" in expensive["regime_line"]

    mid = build_market_view(_fetchers(target_pct=0.55))
    assert "整体估值中位" in mid["regime_line"]

    cheap = build_market_view(_fetchers(target_pct=0.1))
    assert "整体估值偏便宜" in cheap["regime_line"]


def test_valuation_fully_abstained_when_all_pe_fetchers_fail():
    fetchers = _fetchers()

    def failing_pe(code):
        raise RuntimeError("接口不可用")

    fetchers["index_pe"] = failing_pe

    view = build_market_view(fetchers)
    assert all(e["pe_percentile_10y"] is None for e in view["indices"])
    assert "估值不可用" in view["regime_line"]


def test_momentum_majority_label_switches_with_trend():
    up_view = build_market_view(_fetchers(trend=0.0025))
    assert "趋势偏多" in up_view["regime_line"]

    down_view = build_market_view(_fetchers(trend=-0.0025))
    assert "趋势偏弱" in down_view["regime_line"]


def test_pe_percentile_uses_trailing_10y_window_not_full_history():
    # 3000 点：前 500 点极高（1e6），后 2500 点为 1..2500，最后一点=2000。
    # 近10年窗口（尾部2500点）分位 = 2001/2500；全历史分位 = 2001/3000——两者可测差异明显。
    n_old, n_win = 500, 2500
    values = np.concatenate([np.full(n_old, 1e6), np.arange(1, n_win + 1, dtype=float)])
    values[-1] = 2000.0
    dates = pd.date_range("2013-01-01", periods=n_old + n_win, freq="B").astype(str)
    windowed_pe = pd.DataFrame({"date": dates, "value": values})

    fetchers = _fetchers()
    good_pe = fetchers["index_pe"]
    fetchers["index_pe"] = lambda code: windowed_pe if code == "000300" else good_pe(code)

    view = build_market_view(fetchers)
    hs300 = next(e for e in view["indices"] if e["code"] == "000300")
    assert hs300["pe_percentile_10y"] == 2001 / 2500  # 窗口口径
    assert hs300["pe_percentile_10y"] != 2001 / 3000  # 不是全历史口径


def test_momentum_abstains_when_all_index_hist_fail():
    fetchers = _fetchers()

    def failing_hist(code):
        raise RuntimeError("接口不可用")

    fetchers["index_hist"] = failing_hist

    view = build_market_view(fetchers)
    assert all(e["ma20_gt_ma60"] is None for e in view["indices"])
    assert "动量不可用" in view["regime_line"]
    assert "趋势偏弱" not in view["regime_line"]


def test_momentum_majority_uses_available_denominator():
    # 5 指数中 3 只日线失败，剩 2 只全为多头 → 以可用数为分母应判"趋势偏多"
    #（若仍用固定分母 5，2/5 会被误判为"趋势偏弱"）。
    fetchers = _fetchers(trend=0.0025)
    good_hist = fetchers["index_hist"]
    dead = {"399006", "000688", "000922"}
    fetchers["index_hist"] = lambda code: (_ for _ in ()).throw(RuntimeError("接口不可用")) \
        if code in dead else good_hist(code)

    view = build_market_view(fetchers)
    alive = [e for e in view["indices"] if e["code"] not in dead]
    assert all(e["ma20_gt_ma60"] is True for e in alive)
    assert "趋势偏多" in view["regime_line"]
