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


def test_assemble_and_render(tmp_path):
    led = _ledger(tmp_path)

    # 首期：注入返回合成事件的 events_fn（零网络，走公开 API 注入而非 monkeypatch）
    fake_events = [{"date": "2026-07-13", "event": "测试CPI公布"}]
    payload1 = assemble(UNIVERSES, _synthetic_prices, _metrics_fn, _screen_fn, led,
                        TODAY, TRADE_DATES, top=5, events_fn=lambda: fake_events)

    # payload 含 boards/health/review/charts/events 键
    for key in ("boards", "health", "review", "charts", "events"):
        assert key in payload1
    assert set(payload1["boards"]) == {"potential", "high_return", "steady", "pullback", "defensive"}
    # 首期 review 为 None（无上期存档可回看）
    assert payload1["review"] is None
    # 事件可用 → 原样进 payload，health line 不带"不可用"提示
    assert payload1["events"] == fake_events
    assert "事件日历不可用" not in payload1["health"]["line"]
    # 事件可用时渲染出事件日历节
    html1 = build_gold_html(payload1)
    assert "下周事件" in html1 and "测试CPI公布" in html1
    # 首期 issues 已落库（存档供下期回看）
    issues1 = led.issues_for(TODAY)
    assert len(issues1) > 0

    # 第二次以 today+7 调 assemble，events_fn 返回 None → review 应非空且含每榜平均
    payload2 = assemble(UNIVERSES, _synthetic_prices, _metrics_fn, _screen_fn, led,
                        TODAY2, TRADE_DATES, top=5, events_fn=lambda: None)
    # 事件不可用 → payload["events"] 为 None 且 health line 追加不可用提示
    assert payload2["events"] is None
    assert "事件日历不可用" in payload2["health"]["line"]
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
    # 事件不可用 → 整节省略（不渲染"下周事件"），仅 health line 注明
    assert "下周事件" not in html
    assert "事件日历不可用" in html
    # 金矿摘要：榜首带一句话理由（Fix 5，potential 榜首用深筛分）
    assert "深筛分" in html
    # 高收益榜理由走 _pct 百分数格式化：universe 收益列是百分数单位（合成最大 r_1y=29.0 即 29%），
    # build_boards 边界归一成小数 0.29 → 渲染 +29.0%；不许出现 100 倍错标（+2900.0%）
    assert "1年 +29.0%（裸收益，风险自负）" in html
    assert "+2900.0%" not in html
    # 数值理由四舍五入到 2 位小数（合成 calmar 0.8+4*0.1 浮点为 1.2000000000000002，须渲染成 1.2）
    assert "卡玛 1.2）" in html
    assert "1.2000000" not in html


def test_holdings_section_wired_when_holdings_fn_given(tmp_path):
    """Fix 1：assemble 传 holdings_fn → payload["holdings"] 填充，HTML 含我的持仓小节 +
    对账 verdict + 5日中位路径；不传则整节省略（当前行为不变）。"""
    led = _ledger(tmp_path)
    fake_holdings = [
        {"code": "100000", "name": "示例基金100000", "pnl_pct": 0.0512,
         "last_reconcile_verdict": "ok", "cone_p50_5d": [0.001, 0.002, -0.001, 0.0, 0.003]},
        {"code": "100001", "name": "示例基金100001（取价失败）", "pnl_pct": None,
         "last_reconcile_verdict": None, "cone_p50_5d": None},
    ]
    payload = assemble(UNIVERSES, _synthetic_prices, _metrics_fn, _screen_fn, led,
                       TODAY, TRADE_DATES, top=5, events_fn=lambda: None,
                       holdings_fn=lambda: fake_holdings)
    assert payload["holdings"] == fake_holdings

    html = build_gold_html(payload)
    assert "我的持仓" in html
    assert "ok" in html
    assert "5.12" in html  # pnl_pct 渲染成百分比
    assert "样本不足" in html  # cone_p50_5d=None 的行
    # p50 序列以百分数逗号（顿号）串渲染
    assert "+0.1%" in html or "0.1%" in html

    # 不传 holdings_fn（默认 None）→ payload 不含该键，整节省略（当前行为不变）
    payload_no_holdings = assemble(UNIVERSES, _synthetic_prices, _metrics_fn, _screen_fn, led,
                                   TODAY2, TRADE_DATES, top=5, events_fn=lambda: None)
    assert "holdings" not in payload_no_holdings
    html_no_holdings = build_gold_html(payload_no_holdings)
    assert "我的持仓" not in html_no_holdings


def test_board_names_backfilled_from_universe_when_metrics_lack_name(tmp_path):
    """真实 metrics_batch 的 name 恒为 None（resolve 不带基金名）——board 行必须从 universe 回填，
    否则周报摘要四个榜的"榜首"全显示 '—'（真实报告里实际发生过）。"""
    def metrics_fn_no_name(codes):
        out = _metrics_fn(codes)
        for r in out:
            r["name"] = None  # 复现真实 gap：metrics_batch -> resolve(code).name is None
        return out

    led = _ledger(tmp_path)
    payload = assemble(UNIVERSES, _synthetic_prices, metrics_fn_no_name, _screen_fn, led,
                       TODAY, TRADE_DATES, top=5, events_fn=lambda: None)
    for board in ("high_return", "steady", "pullback", "defensive"):
        rows = payload["boards"][board]
        assert rows, f"{board} 应有上榜行（合成数据全命中）"
        assert str(rows[0].get("name") or "").startswith("示例基金"), board
        assert str(payload["summary"][board]["top1"] or "").startswith("示例基金"), board

    html = build_gold_html(payload)
    assert "榜首：—" not in html  # 五榜榜首名字全部可见


def test_regime_header_three_branch_fallback(tmp_path):
    """Task 5：头部 regime 双重降级 —— meta.regime_line 存在则渲染之（转义）；
    缺失但 meta.market_valuation 存在则走现有展示（不变）；两者皆无则显示"regime 不可用"。"""
    led = _ledger(tmp_path)
    payload = assemble(UNIVERSES, _synthetic_prices, _metrics_fn, _screen_fn, led,
                       TODAY, TRADE_DATES, top=5, events_fn=lambda: None)

    # 分支1：regime_line 存在 → 渲染其内容，且做 HTML 转义
    payload["meta"]["regime_line"] = "整体估值偏贵 · 趋势偏多 · 热点：新能源&AI"
    html1 = build_gold_html(payload)
    assert "整体估值偏贵 · 趋势偏多 · 热点：新能源&amp;AI" in html1
    assert "regime 不可用" not in html1

    # 分支2：regime_line 缺失，market_valuation 存在 → 现有展示不变
    del payload["meta"]["regime_line"]
    payload["meta"]["market_valuation"] = {"available": True, "percentile_10y": 0.62, "level": "中性略高"}
    html2 = build_gold_html(payload)
    assert "大盘估值：全A近10年 62% 分位（中性略高）" in html2
    assert "regime 不可用" not in html2

    # 分支3：两者皆无 → "regime 不可用"
    payload["meta"]["market_valuation"] = None
    html3 = build_gold_html(payload)
    assert "regime 不可用" in html3


def test_same_day_rerun_does_not_duplicate_report_issues(tmp_path):
    """Fix 4：同一 today 重跑 assemble 两次，report_issues 存档不重复（幂等）。"""
    led = _ledger(tmp_path)
    assemble(UNIVERSES, _synthetic_prices, _metrics_fn, _screen_fn, led,
             TODAY, TRADE_DATES, top=5, events_fn=lambda: None)
    n1 = len(led.issues_for(TODAY))
    assert n1 > 0

    payload2 = assemble(UNIVERSES, _synthetic_prices, _metrics_fn, _screen_fn, led,
                        TODAY, TRADE_DATES, top=5, events_fn=lambda: None)
    n2 = len(led.issues_for(TODAY))
    assert n2 == n1  # 未重复存档
    assert payload2["meta"]["issues_already_archived"] is True
