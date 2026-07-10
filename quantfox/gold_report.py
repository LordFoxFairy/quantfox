"""全景淘金周报：五榜纯逻辑（不取数、不渲染——可注入可测试）。
诚实内建：高收益榜特意保留但满屏警示；估值>0.85 标红；假稳 flags 不剔除但沉底；
幸存者偏差与"过去≠未来"由渲染层固定文案承担。"""
import pandas as pd

_INDUSTRY_WORDS = ["医疗", "医药", "半导体", "新能源", "白酒", "军工", "科技", "消费",
                   "金融", "地产", "黄金", "芯片", "光伏", "汽车"]


def select_pool(universes: dict) -> list:
    """候选池 ≤80：每类 r_1y top8 ∪ 股票/混合/指数/QDII 的 r_3y top8 ∪ 债券型 r_3y top20。"""
    codes = []
    for t, df in universes.items():
        codes += list(df.sort_values("r_1y", ascending=False)["code"].head(8))
    for t in ("股票型", "混合型", "指数型", "QDII"):
        if t in universes:
            codes += list(universes[t].sort_values("r_3y", ascending=False)["code"].head(8))
    if "债券型" in universes:
        codes += list(universes["债券型"].sort_values("r_3y", ascending=False)["code"].head(20))
    seen, out = set(), []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out[:80]


def _fund_type_of(code, universes):
    for t, df in universes.items():
        if (df["code"] == code).any():
            return t
    return None


def _name_theme_mismatch(name, theme):
    if not name or not theme:
        return False
    for w in _INDUSTRY_WORDS:
        if w in name and w not in theme:
            return True
    return False


def _base_row(m, universes):
    code = m["code"]
    r1y = None
    name = m.get("name")
    t = m.get("fund_type") or _fund_type_of(code, universes)
    if t and t in universes:
        hit = universes[t].loc[universes[t]["code"] == code, ["r_1y", "name"]]
        if len(hit):
            # universe 的收益列是百分数单位（21.73 == 21.73%，见 data/universe.py 只对 fee 除百）；
            # 榜单行统一小数口径（渲染层 _pct 会 ×100），在此边界归一。
            r1y = float(hit["r_1y"].iloc[0]) / 100.0
            if not name:  # metrics_batch 的 name 恒为 None（resolve 不带基金名）→ 从 universe 回填
                name = str(hit["name"].iloc[0])
    return {"code": code, "name": name, "fund_type": t, "r_1y": r1y,
            "sharpe": m.get("sharpe"), "calmar": m.get("calmar"),
            "max_drawdown": m.get("max_drawdown"), "ann_vol": m.get("ann_vol"),
            "price_pct": m.get("price_pct"),
            "dist_from_52w_high": m.get("dist_from_52w_high"),
            "ma20_above_ma60": m.get("ma20_above_ma60"),
            "flags": m.get("flags") or [], "name_theme_mismatch": False}


def _pareto_steady(rows):
    """夏普/卡玛双指标非支配集（都不为 None 的行）。"""
    cand = [r for r in rows if r["sharpe"] is not None and r["calmar"] is not None]
    front = []
    for r in cand:
        if not any(o["sharpe"] >= r["sharpe"] and o["calmar"] >= r["calmar"]
                   and (o["sharpe"] > r["sharpe"] or o["calmar"] > r["calmar"]) for o in cand):
            front.append(r)
    return front


def build_boards(universes, pool_metrics, screen_rows, top=10) -> dict:
    metrics_ok = [m for m in pool_metrics if not m.get("error")]
    by_code = {m["code"]: m for m in metrics_ok}
    rows = [_base_row(m, universes) for m in metrics_ok]
    theme_by_code = {s["code"]: s.get("theme") for s in screen_rows}
    for r in rows:
        r["name_theme_mismatch"] = _name_theme_mismatch(r["name"], theme_by_code.get(r["code"]))

    # 潜力榜：直接消费 screen() 输出（多周期一致+动能不过热），透传 score/overheated
    potential = []
    for s in screen_rows[:top]:
        base = _base_row(by_code.get(s["code"], {"code": s["code"], "name": s.get("name")}), universes)
        base.update({"score": s.get("score"), "overheated": bool(s.get("overheated")),
                     "sort_key": s.get("score"),
                     "name_theme_mismatch": _name_theme_mismatch(s.get("name"), s.get("theme"))})
        potential.append(base)

    # 高收益榜：全类型 r_1y top（特意保留，渲染层满屏警示）
    all_uni = pd.concat(universes.values(), ignore_index=True)
    hi = all_uni.sort_values("r_1y", ascending=False).head(top)
    high_return = []
    for _, u in hi.iterrows():
        m = by_code.get(str(u["code"]), {"code": str(u["code"]), "name": u["name"]})
        base = _base_row(m, universes)
        # 同 _base_row：universe 收益列是百分数单位，边界归一成小数
        base.update({"r_1y": float(u["r_1y"]) / 100.0, "sort_key": float(u["r_1y"]) / 100.0})
        high_return.append(base)

    # 以下三榜从同一批 rows 里筛选：先复制再写 sort_key，避免同一只基金
    # 命中多榜时 sort_key 被后算的榜覆盖（跨榜共享可变 dict 的污染）。
    steady = sorted(_pareto_steady(rows), key=lambda r: r["calmar"], reverse=True)[:top]
    steady = [dict(r) for r in steady]
    for r in steady:
        r["sort_key"] = r["calmar"]

    pullback = [r for r in rows
                if (r["calmar"] or 0) > 0.5 and (r["dist_from_52w_high"] or 0) > 0.15]
    pullback = sorted(pullback, key=lambda r: (r["dist_from_52w_high"] or 0) * (r["calmar"] or 0),
                      reverse=True)[:top]
    pullback = [dict(r) for r in pullback]
    for r in pullback:
        r["sort_key"] = round((r["dist_from_52w_high"] or 0) * (r["calmar"] or 0), 4)

    bonds = [r for r in rows if r["fund_type"] == "债券型"]
    clean = sorted([r for r in bonds if not r["flags"]], key=lambda r: r["ann_vol"] or 9)
    flagged = sorted([r for r in bonds if r["flags"]], key=lambda r: r["ann_vol"] or 9)
    defensive = [dict(r) for r in (clean + flagged)[:top]]  # 假稳不剔除但沉底标红（渲染层）
    for r in defensive:
        r["sort_key"] = r["ann_vol"]

    return {"potential": potential, "high_return": high_return, "steady": steady,
            "pullback": pullback, "defensive": defensive}
