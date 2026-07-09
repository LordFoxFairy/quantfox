import datetime as dt

import pandas as pd

from quantfox.data.resolve import Asset
from quantfox.evidence import EvidenceCard, build_evidence


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
    assert card.schema_version == "2.0"
    assert card.data_quality.price == "ok"
    assert card.profile["basic"]["manager"] == "王三"
    assert card.data_quality.profile == "ok"
    assert card.metrics["sharpe"] is not None
    assert card.metrics["max_drawdown"] is not None
    assert card.returns["1m"] is not None
    assert card.data_quality.ohlc == "unavailable"
    assert card.indicators["ohlc"]["available"] is False
    assert "证据卡" in card.to_markdown()


def test_stale_price_flagged():
    a = Asset(symbol="501018", type="otc_fund")
    prices = _series([100.0 + i for i in range(300)])
    # today 比最后净值晚 30 天 → 应判 stale
    today = _asof(prices) + dt.timedelta(days=30)
    card = build_evidence(a, prices=prices, profile={"applicable": False}, track_record=None, today=today)
    assert card.data_quality.price == "stale"
    assert any("未更新" in n for n in card.data_quality.notes)


def test_gold_card_has_ohlc_no_profile():
    a = Asset(symbol="Au99.99", type="gold", name="黄金")
    prices = _gold(list(range(1, 400)))
    card = build_evidence(a, prices=prices, profile={"applicable": False},
                          track_record=None, today=_asof(prices))
    assert card.data_quality.ohlc == "available"
    assert card.data_quality.profile == "n/a"
    assert card.indicators["ohlc"]["atr14"] is not None


def test_missing_prices_flags_quality():
    a = Asset(symbol="501018", type="otc_fund")
    card = build_evidence(a, prices=_series([]), profile={"applicable": True}, track_record=None)
    assert card.data_quality.price == "missing"
    assert card.price.latest is None
    assert card.metrics == {}
