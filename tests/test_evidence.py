import pandas as pd

from money.data.resolve import Asset
from money.evidence import EvidenceCard, build_evidence


def _series(vals):
    dates = pd.date_range("2022-01-01", periods=len(vals), freq="D").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in vals]})


def test_build_full_card():
    a = Asset(symbol="501018", type="otc_fund", name="测试基金")
    card = build_evidence(
        a,
        prices=_series(list(range(1, 400))),
        news=[{"title": "利好", "source": "x", "date": "2023-01-01", "url": "", "summary": "s"}],
        track_record={"past_signals": 3, "hit_rate": 0.66, "ic": 0.1, "vs_benchmark": 0.02},
    )
    assert isinstance(card, EvidenceCard)
    assert card.schema_version == "1.0"
    assert card.asset.symbol == "501018"
    assert card.price.latest == 399.0
    assert card.data_quality.price == "ok"
    assert "501018" in card.to_json()
    assert "证据卡" in card.to_markdown()


def test_missing_prices_flags_quality():
    a = Asset(symbol="501018", type="otc_fund")
    card = build_evidence(a, prices=_series([]), news=[], track_record=None)
    assert card.data_quality.price == "missing"
    assert card.price.latest is None
