import datetime as dt

import pandas as pd

from quantfox.data.resolve import Asset
from quantfox.evidence import EvidenceCard, build_evidence, compute_flags


def _series(vals):
    dates = pd.date_range("2022-01-03", periods=len(vals), freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in vals]})


def _gold(vals):
    df = _series(vals)
    df["high"] = df["value"] * 1.01
    df["low"] = df["value"] * 0.99
    return df


def _asof(df):
    """把 today 设成序列最后一天，避免离线 fixture 被判 stale。"""
    return dt.date.fromisoformat(df["date"].iloc[-1])


_FUND_PROFILE = {
    "applicable": True,
    "basic": {"name": "测试基金", "company": "某基金", "manager": "王三", "type": "混合型", "inception": "2015-01-01", "scale": "10亿"},
    "holdings": {"as_of": "2024Q1", "top10_concentration": 30.0, "top": [{"code": "600000", "name": "浦发", "pct": 5.0}]},
    "rating": {"morningstar": 4.0, "fee": "0.15%", "type": "混合型"},
}


def test_build_full_card_v2():
    a = Asset(symbol="501018", type="otc_fund", name="测试基金")
    prices = _series([100.0 * (1.001 ** i) for i in range(400)])
    card = build_evidence(a, prices=prices, profile=_FUND_PROFILE,
                          track_record={"past_signals": 3, "hit_rate": 0.66}, today=_asof(prices))
    assert isinstance(card, EvidenceCard)
    assert card.schema_version == "2.1"
    assert card.data_quality.price == "ok"
    assert card.profile["basic"]["manager"] == "王三"
    assert card.data_quality.profile == "ok"
    assert card.metrics["sharpe"] is not None
    assert card.metrics["max_drawdown"] is not None
    assert card.returns["1m"] is not None
    assert card.data_quality.ohlc == "unavailable"
    assert card.indicators["ohlc"]["available"] is False
    # 400 个交易日 ≈1.59 年 <3 年 → 只有 short_history（回撤/波动均正常，非债基）
    assert card.flags == ["short_history"]
    assert "证据卡" in card.to_markdown()


def test_stale_price_flagged():
    a = Asset(symbol="501018", type="otc_fund")
    prices = _series([100.0 + i for i in range(300)])
    # today 比最后净值晚 30 天 → 应判 stale
    today = _asof(prices) + dt.timedelta(days=30)
    card = build_evidence(a, prices=prices, profile={"applicable": False}, track_record=None, today=today)
    assert card.data_quality.price == "stale"
    assert any("未更新" in n for n in card.data_quality.notes)
    # 300 交易日 <3 年、profile 不可用故 fund_type=None、回撤/波动都正常
    assert card.flags == ["short_history"]


def test_gold_card_has_ohlc_no_profile():
    a = Asset(symbol="Au99.99", type="gold", name="黄金")
    prices = _gold(list(range(1, 400)))
    card = build_evidence(a, prices=prices, profile={"applicable": False},
                          track_record=None, today=_asof(prices))
    assert card.data_quality.ohlc == "available"
    assert card.data_quality.profile == "n/a"
    assert card.indicators["ohlc"]["atr14"] is not None
    # 1..399 线性序列早期分母极小 → 波动率被拉得很高（>8%）且无回撤 → nav_spike_suspect；
    # 399 交易日 <3 年 → short_history。二者共存不冲突。
    assert card.flags == ["nav_spike_suspect", "short_history"]


def test_missing_prices_flags_quality():
    a = Asset(symbol="501018", type="otc_fund")
    card = build_evidence(a, prices=_series([]), profile={"applicable": True}, track_record=None)
    assert card.data_quality.price == "missing"
    assert card.price.latest is None
    assert card.metrics == {}
    # 无价格数据 → 无法判 history_years/回撤波动，flags 不误报
    assert card.flags == []


def test_flags_empty_array_key_present_in_json():
    a = Asset(symbol="501018", type="otc_fund")
    prices = _series([100.0 * (1.001 ** i) for i in range(800)])  # >3年，稳健上涨，不该触发任何 flag
    card = build_evidence(a, prices=prices, profile={"applicable": False}, track_record=None, today=_asof(prices))
    assert card.flags == []
    assert '"flags": []' in card.to_json()


# --- C2: compute_flags 纯函数（合成数据，阈值边界） ---

def test_flag_nav_spike_suspect_triggers_on_low_dd_high_vol():
    metrics = {"max_drawdown": -0.01, "ann_vol": 0.12}
    assert compute_flags(metrics, fund_type=None, history_years=5) == ["nav_spike_suspect"]


def test_flag_nav_spike_suspect_boundary_exact_3pct_does_not_trigger():
    # |max_dd|==3% 恰好不触发（阈值是 <3%）
    metrics = {"max_drawdown": -0.03, "ann_vol": 0.20}
    assert compute_flags(metrics, fund_type=None, history_years=5) == []


def test_flag_bond_equity_risk_triggers_on_bond_type_deep_drawdown():
    metrics = {"max_drawdown": -0.15, "ann_vol": 0.10}
    assert compute_flags(metrics, fund_type="债券型", history_years=5) == ["bond_equity_risk"]


def test_flag_bond_equity_risk_skipped_when_fund_type_unknown():
    # fund_type=None（未知）→ 即便回撤很深也不误判债基踩雷
    metrics = {"max_drawdown": -0.30, "ann_vol": 0.10}
    assert compute_flags(metrics, fund_type=None, history_years=5) == []


def test_flag_bond_equity_risk_skipped_for_non_bond_type():
    metrics = {"max_drawdown": -0.30, "ann_vol": 0.10}
    assert compute_flags(metrics, fund_type="股票型", history_years=5) == []


def test_flag_short_history_triggers_below_3_years():
    metrics = {"max_drawdown": -0.05, "ann_vol": 0.10}
    assert compute_flags(metrics, fund_type=None, history_years=2.5) == ["short_history"]


def test_flag_short_history_boundary_exact_3_years_does_not_trigger():
    metrics = {"max_drawdown": -0.05, "ann_vol": 0.10}
    assert compute_flags(metrics, fund_type=None, history_years=3.0) == []


def test_flag_history_years_unknown_not_misreported():
    metrics = {"max_drawdown": -0.05, "ann_vol": 0.10}
    assert compute_flags(metrics, fund_type=None, history_years=None) == []


def test_flag_missing_metrics_no_crash_no_misreport():
    assert compute_flags({}, fund_type="债券型", history_years=None) == []


def test_flags_can_combine_multiple():
    metrics = {"max_drawdown": -0.02, "ann_vol": 0.15}
    flags = compute_flags(metrics, fund_type="纯债型", history_years=1.0)
    # 回撤/波动不匹配 + 短历史 同时成立；债基未跌破 -10% 所以 bond_equity_risk 不触发
    assert flags == ["nav_spike_suspect", "short_history"]
