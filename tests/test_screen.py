import pandas as pd

from quantfox.data.universe import load_universe
from quantfox.screen import score_universe, screen
from quantfox.screen_report import build_screen_report


def test_screen_report_html_renders():
    cands = [
        {"code": "000001", "name": "华夏成长", "theme": "AI/算力/科技", "score": 95.0,
         "overheated": True, "r_1m": 5.0, "r_3m": 40.0, "r_6m": 60.0, "r_1y": 200.0, "r_3y": 300.0, "fee": "0.15%"},
        {"code": "100032", "name": "富国红利", "theme": "红利/价值/低波", "score": 85.0,
         "overheated": False, "r_1m": -1.0, "r_3m": 10.0, "r_6m": 20.0, "r_1y": 30.0, "r_3y": 50.0, "fee": "0.15%"},
    ]
    meta = {"title": "深筛报告", "theme_spread": {"AI/算力/科技": 1, "红利/价值/低波": 1},
            "market_valuation": {"available": True, "percentile_10y": 0.70, "level": "偏贵"},
            "generated_at": "2026-07-10"}
    html = build_screen_report(cands, meta)
    assert "__ROWS__" not in html and "__TITLE__" not in html  # 占位符已替换
    assert "华夏成长" in html and "富国红利" in html
    assert "山顶" in html          # 过热标红
    assert "偏贵" in html          # 大盘估值进了报告头
    assert "≠ 现在能买" in html    # 相对分免责


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


def test_screen_topn_overheat_and_exclude():
    df = load_universe("股票型", fetcher=_fetcher)
    top2 = screen(df, top=2, per_theme=10)
    assert len(top2) == 2
    allres = screen(df, top=50, per_theme=10)
    codes = {r["code"] for r in allres}
    # 太新的（无近1年）不纳入
    assert "000004" not in codes
    # 昙花B（近3月最高=超买）应被标 overheated
    bh = [r for r in allres if r["code"] == "000002"][0]
    assert bh["overheated"] is True or bh["overheated"]
    # 排除过热后，昙花B 不在
    kept = {r["code"] for r in screen(df, top=50, per_theme=10, exclude_overheated=True)}
    assert "000002" not in kept


def test_per_theme_limits_diversity():
    # 同主题3只，per_theme=2 → 最多留2只
    df = pd.DataFrame({
        "基金代码": ["001", "002", "003"], "基金简称": ["半导体龙头", "芯片先锋", "集成电路精选"],
        "近3月": [10.0, 9.0, 8.0], "近6月": [15.0, 14.0, 13.0], "近1年": [40.0, 38.0, 36.0],
        "近2年": [50.0, 48.0, 46.0], "近3年": [60.0, 58.0, 56.0], "今年来": [10.0, 9.0, 8.0],
        "手续费": ["0.15%"] * 3,
    })
    u = load_universe("x", fetcher=lambda t: df)
    res = screen(u, top=50, per_theme=2)
    semi = [r for r in res if r["theme"] == "半导体/芯片"]
    assert len(semi) == 2  # 3只同主题被限到2只
