import pandas as pd

from quantfox.intraday import estimate_fund_intraday, gold_intraday, official_fund_estimate


def test_official_estimate_parses_growth():
    df = pd.DataFrame({
        "基金代码": ["000001", "161725"],
        "基金名称": ["华夏成长混合", "招商白酒"],
        "2026-07-09-估算数据-估算值": ["1.6048", "0.90"],
        "2026-07-09-估算数据-估算增长率": ["6.00%", "-1.20%"],
    })
    r = official_fund_estimate(df, "000001")
    assert r["available"] is True
    assert r["est_change_pct"] == 6.0
    assert r["est_nav"] == 1.6048
    assert official_fund_estimate(df, "999999")["available"] is False


def test_fund_estimate_from_holdings():
    holdings = [
        {"code": "002025", "name": "航天电器", "pct": 4.0},
        {"code": "600862", "name": "中航高科", "pct": 3.0},
    ]
    quotes = {"002025": -5.0, "600862": -3.0}  # 涨跌幅 %
    r = estimate_fund_intraday(holdings, quotes)
    assert r["available"] is True
    assert r["coverage_pct"] == 7.0
    # 覆盖部分贡献 = 4%*-5% + 3%*-3% = -0.29%
    assert r["est_from_top_holdings_pct"] == -0.29
    # 若整基同步：-0.29% / 7% = 约 -4.1%
    assert r["est_full_if_representative_pct"] == round(-0.29 / 7.0 * 100, 2)
    # 贡献按大小排序，最拖累的在前
    assert r["contributions"][0]["code"] == "002025"


def test_fund_estimate_no_quotes_degrades():
    r = estimate_fund_intraday([{"code": "002025", "name": "x", "pct": 4.0}], {})
    assert r["available"] is False
    assert "以晚间官方净值为准" in r["note"]


def test_gold_intraday():
    df = pd.DataFrame({"品种": ["Au99.99"] * 3, "时间": ["14:46", "14:47", "14:48"],
                       "现价": [900.0, 896.5, 881.0]})
    r = gold_intraday(df)
    assert r["available"] is True
    assert r["latest"] == 881.0
    assert r["intraday_change_pct"] == round((881.0 / 900.0 - 1) * 100, 2)
    assert r["intraday_high"] == 900.0 and r["intraday_low"] == 881.0
