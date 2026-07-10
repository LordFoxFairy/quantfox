"""五榜纯逻辑：候选池 + 五榜（potential/high_return/steady/pullback/defensive）。
全部用合成 universe + 合成 metrics 行，不触网。
"""
import pandas as pd

from quantfox.gold_report import build_boards, select_pool


def _uni(codes, r1y_base=10.0):
    n = len(codes)
    return pd.DataFrame({
        "code": codes, "name": [f"示例基金{c}" for c in codes],
        "r_1w": [0.1] * n, "r_1m": [1.0] * n, "r_3m": [3.0] * n, "r_6m": [6.0] * n,
        "r_1y": [r1y_base + i for i in range(n)],
        "r_2y": [15.0] * n, "r_3y": [20.0] * n, "ytd": [5.0] * n, "fee": [0.0015] * n,
    })


def _met(code, fund_type="股票型", **kw):
    row = {"code": code, "name": f"示例基金{code}", "fund_type": fund_type,
           "sharpe": 1.0, "calmar": 0.8, "max_drawdown": -0.2, "ann_vol": 0.15,
           "price_pct": 0.5, "dist_from_52w_high": 0.05, "ma20_above_ma60": True,
           "flags": [], "error": None}
    row.update(kw)
    return row


UNIVERSES = {"股票型": _uni([f"10{i:04d}" for i in range(30)]),
             "混合型": _uni([f"20{i:04d}" for i in range(30)]),
             "债券型": _uni([f"30{i:04d}" for i in range(30)], r1y_base=3.0),
             "指数型": _uni([f"40{i:04d}" for i in range(30)]),
             "QDII": _uni([f"50{i:04d}" for i in range(30)])}


def test_pool_bounded_and_deduped():
    pool = select_pool(UNIVERSES)
    assert 0 < len(pool) <= 80 and len(pool) == len(set(pool))


def test_boards_shapes_and_gates():
    pool = select_pool(UNIVERSES)
    metrics = [_met(c) for c in pool]
    # 构造榜单素材：一只捡漏（打折20%卡玛1.2）、一只债基假稳、一只高估值
    metrics[0].update(dist_from_52w_high=0.20, calmar=1.2)
    metrics[1].update(fund_type="债券型", flags=["bond_equity_risk"], ann_vol=0.02)
    metrics[2].update(price_pct=0.95)
    screen_rows = [{"code": m["code"], "name": m["name"], "theme": "宽基", "score": 90 - i,
                    "overheated": i == 0} for i, m in enumerate(metrics[:12])]
    boards = build_boards(UNIVERSES, metrics, screen_rows, top=10)
    assert set(boards) == {"potential", "high_return", "steady", "pullback", "defensive"}
    assert len(boards["potential"]) == 10 and boards["potential"][0]["overheated"] is True
    assert all(len(b) <= 10 for b in boards.values())
    # 回调捡漏：满足 卡玛>0.5 且 打折>15% 的那只在榜
    assert any(r["code"] == metrics[0]["code"] for r in boards["pullback"])
    # 防守榜：clean（无 flags）行必须全部排在 flagged 行之前（假稳不剔除但沉底标红）
    dfs = boards["defensive"]
    n_clean = len([x for x in dfs if not x["flags"]])
    assert all(not r["flags"] for r in dfs[:n_clean])
    assert all(r["flags"] for r in dfs[n_clean:])
    # 高估值标记透传
    hi = [r for b in boards.values() for r in b if r["code"] == metrics[2]["code"]]
    assert all(r["price_pct"] > 0.85 for r in hi)


def test_sort_key_not_polluted_across_boards():
    pool = select_pool(UNIVERSES)
    metrics = [_met(c) for c in pool]
    # 一只债券型：同时命中 稳健(Pareto)、回调捡漏(卡玛1.5×打折30%)、防守(债券型低波)
    metrics[0].update(fund_type="债券型", calmar=1.5, sharpe=2.0,
                      dist_from_52w_high=0.30, ann_vol=0.05, flags=[])
    boards = build_boards(UNIVERSES, metrics, [], top=10)
    code = metrics[0]["code"]
    steady_row = next(r for r in boards["steady"] if r["code"] == code)
    pull_row = next(r for r in boards["pullback"] if r["code"] == code)
    def_row = next(r for r in boards["defensive"] if r["code"] == code)
    assert steady_row["sort_key"] == 1.5           # 卡玛
    assert pull_row["sort_key"] == 0.45            # 0.30*1.5
    assert def_row["sort_key"] == 0.05             # 年化波动
    assert steady_row is not pull_row and pull_row is not def_row


def test_name_theme_mismatch_flagged():
    pool = select_pool(UNIVERSES)
    metrics = [_met(c) for c in pool]
    metrics[3]["name"] = "示例医疗精选"
    screen_rows = [{"code": metrics[3]["code"], "name": metrics[3]["name"],
                    "theme": "半导体", "score": 99, "overheated": False}]
    boards = build_boards(UNIVERSES, metrics, screen_rows, top=10)
    row = next(r for r in boards["potential"] if r["code"] == metrics[3]["code"])
    assert row["name_theme_mismatch"] is True
