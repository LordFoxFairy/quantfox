"""持仓监控：对一只已持有的基金，算客观的"该不该关注"信号。

引擎只算客观信号 + 触发标记；是否真要动作由 LLM（fund-watch 技能）结合舆情判断。
面向中长期持有——默认"继续持有"，只有触发才提示，避免过度交易。
"""
import pandas as pd

from .indicators import compute_indicators
from .percentile import price_percentile

DRAWDOWN_TRIGGER = -0.15   # 熔断/回撤触发线
VALUATION_HIGH = 0.9       # 估值高位线（近3年分位）


def check_holding(prices: pd.DataFrame, entry_price: float, entry_date: str,
                  asset_type: str = "otc_fund") -> dict:
    s = prices["value"].astype(float).reset_index(drop=True)
    latest = float(s.iloc[-1])
    since = prices[prices["date"] >= entry_date]["value"].astype(float).reset_index(drop=True)
    if len(since):
        dd_from_peak = float((since / since.cummax() - 1.0).iloc[-1])
        max_dd_since = float((since / since.cummax() - 1.0).min())
    else:
        dd_from_peak = max_dd_since = 0.0
    ret_since = latest / entry_price - 1.0
    pct = price_percentile(prices, 3).get("price_pct")
    ma60 = compute_indicators(prices)["ma"]["ma60"]
    below_ma60 = (latest < ma60) if ma60 else None

    # 风险类触发 → "需关注"（真要动作的）
    flags = []
    if ret_since <= DRAWDOWN_TRIGGER:
        flags.append(f"浮亏 {ret_since * 100:.0f}%，触发/接近熔断线（{DRAWDOWN_TRIGGER * 100:.0f}%）")
    if dd_from_peak <= DRAWDOWN_TRIGGER:
        flags.append(f"自持有期高点回撤 {dd_from_peak * 100:.0f}%")
    if below_ma60:
        flags.append("跌破 MA60（中期趋势转弱）")
    # 软提示 → 不惊扰赢家（稳步上涨的健康持仓不应被误报"需关注"）
    notes = []
    if pct is not None and pct >= VALUATION_HIGH:
        notes.append(f"已在近 3 年 {pct * 100:.0f}% 高位，可考虑逢高减仓/落袋部分")

    return {
        "latest": round(latest, 4),
        "latest_date": str(prices["date"].iloc[-1]),
        "return_since_entry": round(ret_since, 4),
        "drawdown_from_peak_since_entry": round(dd_from_peak, 4),
        "max_drawdown_since_entry": round(max_dd_since, 4),
        "valuation_pct_3y": round(pct, 4) if pct is not None else None,
        "below_ma60": below_ma60,
        "flags": flags,
        "notes": notes,
        "status": "需关注" if flags else "正常持有",
    }
