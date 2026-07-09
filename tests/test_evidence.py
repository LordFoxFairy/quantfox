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


_FUND_PROFILE = {
    "applicable": True,
    "basic": {"name": "测试基金", "company": "某基金", "manager": "王三", "type": "混合型", "inception": "2015-01-01", "scale": "10亿"},
    "holdings": {"as_of": "2024Q1", "top10_concentration": 30.0, "top": [{"code": "600000", "name": "浦发", "pct": 5.0}]},
    "rating": {"morningstar": 4.0, "fee": "0.15%", "type": "混合型"},
}


def test_build_full_card_v2():
    a = Asset(symbol="501018", type="otc_fund", name="测试基金")
    card = build_evidence(
        a,
        prices=_series([100.0 * (1.001 ** i) for i in range(400)]),
        profile=_FUND_PROFILE,
        track_record={"past_signals": 3, "hit_rate": 0.66},
    )
    assert isinstance(card, EvidenceCard)
    assert card.schema_version == "2.0"
    assert card.data_quality.price == "ok"
    # 专业基本面块
    assert card.profile["basic"]["manager"] == "王三"
    assert card.data_quality.profile == "ok"
    # 风险绩效指标都在
    assert card.metrics["sharpe"] is not None
    assert card.metrics["max_drawdown"] is not None
    assert card.returns["1m"] is not None
    # 基金无 OHLC → 相关指标不可用
    assert card.data_quality.ohlc == "unavailable"
    assert card.indicators["ohlc"]["available"] is False
    assert "证据卡" in card.to_markdown()


def test_gold_card_has_ohlc_no_profile():
    a = Asset(symbol="Au99.99", type="gold", name="黄金")
    card = build_evidence(a, prices=_gold(list(range(1, 400))),
                          profile={"applicable": False}, track_record=None)
    assert card.data_quality.ohlc == "available"
    assert card.data_quality.profile == "n/a"
    assert card.indicators["ohlc"]["atr14"] is not None


def test_missing_prices_flags_quality():
    a = Asset(symbol="501018", type="otc_fund")
    card = build_evidence(a, prices=_series([]), profile={"applicable": True}, track_record=None)
    assert card.data_quality.price == "missing"
    assert card.price.latest is None
    assert card.metrics == {}
