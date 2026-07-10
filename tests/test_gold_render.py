"""周报渲染 + 战绩回看：assemble() 全合成注入，零网络；build_gold_html() 静态断言。"""
import numpy as np
import pandas as pd

from quantfox.gold_report_render import assemble, build_gold_html
from quantfox.storage import Ledger

TODAY = "2026-07-10"
TODAY2 = "2026-07-17"  # 一周后

# 交易日历覆盖两期，含首期/次期及之间的每个工作日（够 check_freshness 用）
TRADE_DATES = [f"2026-07-{d:02d}" for d in range(1, 32) if d not in (4, 5, 11, 12, 18, 19, 25, 26)]


def _uni(codes, r1y_base=10.0):
    n = len(codes)
    return pd.DataFrame({
        "code": codes, "name": [f"示例基金{c}" for c in codes],
        "r_1w": [0.1] * n, "r_1m": [1.0] * n, "r_3m": [3.0] * n, "r_6m": [6.0] * n,
        "r_1y": [r1y_base + i for i in range(n)],
        "r_2y": [15.0] * n, "r_3y": [20.0] * n, "ytd": [5.0] * n, "fee": [0.0015] * n,
    })


UNIVERSES = {"股票型": _uni([f"10{i:04d}" for i in range(20)]),
             "混合型": _uni([f"20{i:04d}" for i in range(20)]),
             "债券型": _uni([f"30{i:04d}" for i in range(20)], r1y_base=3.0),
             "指数型": _uni([f"40{i:04d}" for i in range(20)]),
             "QDII": _uni([f"50{i:04d}" for i in range(20)])}


def _synthetic_prices(code):
    """确定性合成净值：按 code 播种的随机游走，足够长供 simulate_paths(250) 使用。"""
    seed = sum(ord(c) for c in code)
    rng = np.random.default_rng(seed)
    n = 600
    rets = rng.normal(0.0004, 0.01, n)
    nav = 1.0 * np.cumprod(1 + rets)
    dates = pd.bdate_range("2024-01-01", periods=n).strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "value": nav})


def _metrics_fn(codes):
    out = []
    for i, c in enumerate(codes):
        out.append({
            "code": c, "name": f"示例基金{c}", "fund_type": "股票型" if c.startswith("1") else
            ("混合型" if c.startswith("2") else "债券型" if c.startswith("3") else
             "指数型" if c.startswith("4") else "QDII"),
            "sharpe": 1.0 + (i % 5) * 0.1, "calmar": 0.8 + (i % 5) * 0.1,
            "max_drawdown": -0.2, "ann_vol": 0.15,
            "price_pct": 0.9 if i % 7 == 0 else 0.5,  # 部分命中高估值 (>0.85) 红底
            "dist_from_52w_high": 0.20 if i % 4 == 0 else 0.05,
            "ma20_above_ma60": True,
            "flags": ["bond_equity_risk"] if (c.startswith("3") and i % 6 == 0) else [],
            "error": None,
        })
    return out


def _screen_fn(df):
    rows = []
    for i, (_, r) in enumerate(df.iterrows()):
        rows.append({"code": r["code"], "name": r["name"], "theme": "宽基",
                     "score": 90 - i, "overheated": i == 0})
    return rows


def _ledger(tmp_path):
    return Ledger(tmp_path / "ledger.db")


def test_assemble_and_render(tmp_path, monkeypatch):
    # 零网络：next_week_events 在 gold_report_render 命名空间内打桩，不触网
    monkeypatch.setattr("quantfox.gold_report_render.next_week_events", lambda: None)

    led = _ledger(tmp_path)

    payload1 = assemble(UNIVERSES, _synthetic_prices, _metrics_fn, _screen_fn, led,
                        TODAY, TRADE_DATES, top=5)

    # payload 含 boards/health/review/charts/events 键
    for key in ("boards", "health", "review", "charts", "events"):
        assert key in payload1
    assert set(payload1["boards"]) == {"potential", "high_return", "steady", "pullback", "defensive"}
    # 首期 review 为 None（无上期存档可回看）
    assert payload1["review"] is None
    # 事件日历打桩返回 None → payload["events"] 为 None 且 health line 追加不可用提示
    assert payload1["events"] is None
    assert "事件日历不可用" in payload1["health"]["line"]
    # 首期 issues 已落库（存档供下期回看）
    issues1 = led.issues_for(TODAY)
    assert len(issues1) > 0

    # 第二次以 today+7 调 assemble → review 应非空且含每榜平均
    payload2 = assemble(UNIVERSES, _synthetic_prices, _metrics_fn, _screen_fn, led,
                        TODAY2, TRADE_DATES, top=5)
    assert payload2["review"] is not None
    assert payload2["review"]["issue_date"] == TODAY
    assert payload2["review"]["rows"], "回看应含逐只行"
    assert payload2["review"]["board_avg"], "回看应按榜聚合平均"
    for board, avg in payload2["review"]["board_avg"].items():
        assert isinstance(avg, float)

    # 两期 issues 表都有行
    issues2 = led.issues_for(TODAY2)
    assert len(issues1) > 0 and len(issues2) > 0

    html = build_gold_html(payload2)

    # 尾部固定水印
    assert "历史统计推演，非预测承诺" in html
    # health line 原样出现
    assert payload2["health"]["line"] in html
    # 高收益榜警示横幅
    assert "⚠️" in html
    # 五榜标题（中文）
    for label in ("潜力榜", "高收益榜", "稳健榜", "回调捡漏榜", "防守榜"):
        assert label in html
    # ECharts 数据以 JSON 注入：图表数据片段可见（simulate_paths 输出键）
    assert '"p50"' in html and '"p10"' in html and '"p90"' in html
