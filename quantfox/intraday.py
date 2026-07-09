"""盘中异动预警（**非盯盘**）。中长期用户的正确用法：大跌大涨时给个 heads-up，别据此追杀。

- 黄金：`spot_quotations_sge` 有真实时价，可算盘中涨跌。
- 场外基金：**无官方实时净值**——用前十大重仓股的实时涨跌估算今日大致方向；
  仅覆盖披露的前十大、季度滞后、非官方，务必标注清楚。取不到实时行情时优雅降级、诚实说明。
"""
import pandas as pd  # noqa: F401


def _parse_pct(x):
    try:
        return round(float(str(x).replace("%", "").strip()), 2)
    except (ValueError, TypeError):
        return None


def _parse_num(x, nd=4):
    try:
        return round(float(str(x).replace("%", "").strip()), nd)
    except (ValueError, TypeError):
        return None


def official_fund_estimate(df, code: str) -> dict:
    """数据商官方盘中估算（fund_value_estimation_em）——用全部持仓算，比自算前十大准。"""
    row = df[df["基金代码"].astype(str) == str(code)]
    if not len(row):
        return {"available": False, "note": "无该基金盘中官方估算数据"}

    def col(suffix):
        cands = [c for c in df.columns if c.endswith(suffix)]
        return cands[0] if cands else None

    gc, vc = col("估算数据-估算增长率"), col("估算数据-估算值")
    return {
        "available": True,
        "source": "官方盘中估算（全持仓）",
        "est_change_pct": _parse_pct(row[gc].iloc[0]) if gc else None,
        "est_nav": _parse_num(row[vc].iloc[0]) if vc else None,
        "note": "数据商盘中估算净值（用全部持仓算，比自算前十大准）；非官方净值、晚间公布为准；中长期只作异动预警。",
    }


def _default_stock_quotes(codes) -> dict:
    import akshare as ak

    df = ak.stock_zh_a_spot_em()
    df = df[df["代码"].isin(list(codes))]
    return {str(r["代码"]): float(r["涨跌幅"]) for _, r in df.iterrows()}


def estimate_fund_intraday(holdings_top: list, quotes: dict) -> dict:
    """holdings_top: [{code,name,pct}]；quotes: {code: 涨跌幅%}。"""
    covered = [(h, quotes[h["code"]]) for h in holdings_top
               if h.get("code") in quotes and h.get("pct")]
    if not covered:
        return {"available": False,
                "note": "盘中实时行情暂不可用（非交易时段或数据源限制），以晚间官方净值为准"}
    coverage = round(sum(h["pct"] for h, _ in covered), 2)
    est_covered = sum((h["pct"] / 100.0) * (chg / 100.0) for h, chg in covered)
    est_scaled = est_covered / (coverage / 100.0) if coverage else None
    contrib = sorted(
        [{"code": h["code"], "name": h["name"], "pct": h["pct"], "change_pct": round(chg, 2),
          "contrib_pct": round((h["pct"] / 100.0) * (chg / 100.0) * 100, 3)} for h, chg in covered],
        key=lambda x: x["contrib_pct"])
    return {
        "available": True,
        "coverage_pct": coverage,
        "est_from_top_holdings_pct": round(est_covered * 100, 2),
        "est_full_if_representative_pct": round(est_scaled * 100, 2) if est_scaled is not None else None,
        "contributions": contrib,
        "note": (f"仅由前十大(占净值 {coverage}%)实时股价估算、持仓季度滞后、非官方净值；"
                 "中长期只作异动预警，别据此追涨杀跌。"),
    }


def gold_intraday(quotes_df) -> dict:
    df = quotes_df
    if df is None or not len(df):
        return {"available": False, "note": "盘中黄金行情暂不可用"}
    day = df["现价"].astype(float)
    price = float(day.iloc[-1])
    change = price / day.iloc[0] - 1.0 if len(day) > 1 else None
    return {
        "available": True,
        "latest": price,
        "time": str(df["时间"].iloc[-1]) if "时间" in df.columns else None,
        "intraday_change_pct": round(change * 100, 2) if change is not None else None,
        "intraday_high": float(day.max()),
        "intraday_low": float(day.min()),
        "note": "黄金现货 Au99.99 实时；盘中数据、非收盘价。",
    }
