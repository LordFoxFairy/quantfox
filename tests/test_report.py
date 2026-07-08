import pandas as pd

from money.data.resolve import Asset
from money.report import build_report_data, render_html


def _fund(vals):
    dates = pd.date_range("2022-01-03", periods=len(vals), freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in vals]})


def _gold(vals):
    df = _fund(vals)
    df["open"] = df["value"] * 0.999
    df["high"] = df["value"] * 1.01
    df["low"] = df["value"] * 0.99
    return df


ANALYSIS = {
    "title": "测试报告",
    "verdict": {"label": "观望", "klass": "hold", "score": 50},
    "dimensions": [{"name": "趋势动量", "score": 60}],
    "commentary_html": "<p>解读</p>",
    "risks_html": "风险",
}


def test_fund_report_data_uses_nav_and_holdings():
    a = Asset(symbol="000001", type="otc_fund", name="测试基金")
    profile = {"applicable": True,
               "holdings": {"top": [{"name": "浦发", "pct": 5.0}, {"name": "茅台", "pct": 4.0}]}}
    data = build_report_data(a, _fund([100 * (1.001 ** i) for i in range(300)]), profile, ANALYSIS)
    assert "nav" in data["price"] and "kline" not in data["price"]
    assert len(data["holdings"]) == 2
    assert data["verdict"]["score"] == 50
    assert len(data["metrics"]) >= 6
    html = render_html(data)
    assert "__REPORT_JSON__" not in html  # 占位符已替换
    assert "echarts" in html


def test_gold_report_uses_candlestick_no_holdings():
    a = Asset(symbol="Au99.99", type="gold", name="黄金")
    data = build_report_data(a, _gold(list(range(50, 350))), {"applicable": False}, ANALYSIS)
    assert "kline" in data["price"]
    assert data["holdings"] == []
