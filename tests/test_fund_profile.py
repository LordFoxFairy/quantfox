import pandas as pd

from quantfox.data.fund_profile import load_profile
from quantfox.data.resolve import Asset


def _fetchers():
    basic = pd.DataFrame({
        "item": ["基金代码", "基金名称", "基金全称", "成立时间", "基金公司", "基金经理", "基金类型"],
        "value": ["000001", "华夏成长混合", "华夏成长证券投资基金", "2001-12-18", "华夏基金", "王三", "混合型"],
    })
    holdings = pd.DataFrame({
        "股票代码": ["002025", "600862"],
        "股票名称": ["航天电器", "中航高科"],
        "占净值比例": [3.46, 3.24],
        "季度": ["2024年1季度股票投资明细", "2024年1季度股票投资明细"],
    })
    rating = pd.DataFrame({
        "代码": ["000001", "270007"],
        "简称": ["华夏成长混合", "广发大盘"],
        "基金公司": ["华夏基金", "广发"],
        "5星评级家数": [1, 0],
        "晨星评级": [4.0, 3.0],
        "上海证券": [3.0, 1.0],
        "济安金信": [3.0, 2.0],
        "手续费": ["0.15%", "0.15%"],
        "类型": ["混合型-灵活", "混合型-灵活"],
    })
    return {
        "basic": lambda code: basic,
        "holdings": lambda code: holdings,
        "rating": lambda code: rating,
    }


def test_gold_not_applicable():
    p = load_profile(Asset(symbol="Au99.99", type="gold"))
    assert p["applicable"] is False


def test_fund_profile_full():
    p = load_profile(Asset(symbol="000001", type="otc_fund"), fetchers=_fetchers())
    assert p["applicable"] is True
    assert p["basic"]["name"] == "华夏成长混合"
    assert p["basic"]["manager"] == "王三"
    assert p["basic"]["company"] == "华夏基金"
    assert p["holdings"]["top"][0]["name"] == "航天电器"
    assert p["holdings"]["top10_concentration"] > 0
    assert p["rating"]["morningstar"] == 4.0
    assert p["rating"]["type"] == "混合型-灵活"


def test_fund_profile_uses_single_latest_holding_quarter():
    fetchers = _fetchers()
    holdings = pd.DataFrame({
        "股票代码": ["000001", "000002", "000003"],
        "股票名称": ["旧季度高仓", "新季度A", "新季度B"],
        "占净值比例": [40.0, 3.0, 2.0],
        "季度": ["2024年1季度股票投资明细", "2024年2季度股票投资明细", "2024年2季度股票投资明细"],
    })
    fetchers["holdings"] = lambda code: holdings

    p = load_profile(Asset(symbol="000001", type="otc_fund"), fetchers=fetchers)

    assert p["holdings"]["as_of"] == "2024年2季度股票投资明细"
    assert [h["name"] for h in p["holdings"]["top"]] == ["新季度A", "新季度B"]
    assert p["holdings"]["top10_concentration"] == 5.0


def test_fund_profile_resilient_to_fetch_error():
    def _boom(code):
        raise RuntimeError("net down")

    fetchers = {"basic": _boom, "holdings": _boom, "rating": _boom}
    p = load_profile(Asset(symbol="000001", type="otc_fund"), fetchers=fetchers)
    assert p["applicable"] is True
    assert p["basic"] is None
    assert p["holdings"]["top"] == []
