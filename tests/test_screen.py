import pandas as pd

from quantfox.data.universe import load_universe
from quantfox.screen import score_universe, screen


def _raw_universe():
    # 模拟 akshare fund_open_fund_rank_em 的原始列
    return pd.DataFrame({
        "基金代码": ["000001", "000002", "000003", "000004", "000005"],
        "基金简称": ["常青A", "昙花B", "平庸C", "新基D", "稳健E"],
        "近3月": [10.0, 30.0, 2.0, 25.0, 8.0],
        "近6月": [20.0, 25.0, 3.0, None, 18.0],
        "近1年": [40.0, 35.0, 5.0, None, 38.0],
        "近2年": [60.0, 10.0, 8.0, None, 55.0],
        "近3年": [90.0, 5.0, 10.0, None, 80.0],
        "今年来": [15.0, 20.0, 4.0, 22.0, 14.0],
        "手续费": ["0.15%", "0.15%", "0.00%", "0.15%", "0.10%"],
    })


def _fetcher(fund_type):
    return _raw_universe()


def test_load_universe_normalizes():
    df = load_universe("股票型", fetcher=_fetcher)
    assert list(df["code"]) == ["000001", "000002", "000003", "000004", "000005"]
    assert df["fee"].iloc[0] == 0.0015
    assert df["r_1y"].iloc[0] == 40.0


def test_score_rewards_long_term_consistency():
    df = load_universe("股票型", fetcher=_fetcher)
    ranked = score_universe(df)
    # 常青A（近1年&近3年都最高）应排在昙花B（只近3月高）之前
    top_codes = list(ranked["code"])
    assert top_codes.index("000001") < top_codes.index("000002")
    # 常青A 应被标记为 consistent
    assert ranked[ranked["code"] == "000001"]["consistent"].iloc[0]
    assert not ranked[ranked["code"] == "000002"]["consistent"].iloc[0]


def test_screen_topn_and_consistent_filter():
    df = load_universe("股票型", fetcher=_fetcher)
    top2 = screen(df, top=2)
    assert len(top2) == 2
    only = screen(df, top=50, consistent_only=True)
    codes = {r["code"] for r in only}
    assert "000001" in codes and "000002" not in codes
    # 太新的（无近1年）不纳入
    assert "000004" not in {r["code"] for r in screen(df, top=50)}
