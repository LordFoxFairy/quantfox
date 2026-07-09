"""持仓监控：对一只已持有的基金，算客观的"该不该关注"信号。

引擎只算客观信号 + 触发标记；是否真要动作由 LLM（fund-watch 技能）结合舆情判断。
面向中长期持有——默认"继续持有"，只有触发才提示，避免过度交易。
"""
import pandas as pd

from .indicators import compute_indicators
from .percentile import price_percentile

DRAWDOWN_TRIGGER = -0.15   # 熔断/回撤触发线
VALUATION_HIGH = 0.9       # 估值高位线（近3年分位）
VALUATION_LOW = 0.35       # 估值低位线（买点线索）
PULLBACK_FROM_HIGH = -0.20  # 从52周高点回落多少算"回调到位"


def format_digest(watching: list, holding: list) -> str:
    """把巡检结果排成一封摘要（报平安也生成）——供定时邮件用，稳定一致。"""
    buy = [w for w in watching if w.get("status") == "可关注买点"]
    exit_ = [h for h in holding if h.get("status") == "需离场"]
    warn = [h for h in holding if h.get("status") == "留意"]
    lines = []
    if buy or exit_ or warn:
        lines.append(f"⚠️ quantfox 巡检：{len(buy)} 个买点 · {len(exit_)} 个需离场 · {len(warn)} 个留意")
    else:
        lines.append("✅ quantfox 巡检：持仓一切正常、观测暂无买点，继续持有，无需动作。")

    if watching:
        lines.append("\n【观测中·找买点】")
        for w in watching:
            sig = "、".join(w.get("entry_signals") or []) or "等待更好买点"
            lines.append(f"· {w['symbol']}：{w.get('status')}（{sig}）")
    if holding:
        lines.append("\n【持有中·看离场】")
        for h in holding:
            ret = h.get("return_since_entry")
            rets = f"{ret * 100:+.1f}%" if ret is not None else "—"
            note = "、".join(h.get("exit_flags") or h.get("early_warnings") or []) or "正常"
            lines.append(f"· {h['symbol']}：浮盈亏 {rets}，{h.get('status')}（{note}）")

    lines.append("\n—— 非投资建议；买卖请自行在支付宝手动操作，决策与风险自负。")
    return "\n".join(lines)


def check_candidate(prices: pd.DataFrame, target_price: float = None,
                    asset_type: str = "otc_fund") -> dict:
    """观测态：找买点线索。只给客观线索，是否真买结合 fund-analyze 深析。"""
    s = prices["value"].astype(float).reset_index(drop=True)
    latest = float(s.iloc[-1])
    pct = price_percentile(prices, 3).get("price_pct")
    high_52w = float(s.tail(250).max())
    from_high = latest / high_52w - 1.0 if high_52w else None
    rsi = compute_indicators(prices)["rsi"]["rsi12"]

    signals = []
    if pct is not None and pct <= VALUATION_LOW:
        signals.append(f"估值已到近 3 年 {pct * 100:.0f}% 低位，性价比出现")
    if from_high is not None and from_high <= PULLBACK_FROM_HIGH:
        signals.append(f"已从 52 周高点回落 {from_high * 100:.0f}%")
    if target_price and latest <= target_price:
        signals.append(f"已到你的目标买入价 {target_price}")
    if rsi is not None and rsi <= 30:
        signals.append(f"RSI {rsi:.0f} 超卖，短期或有反弹")

    return {
        "latest": round(latest, 4),
        "latest_date": str(prices["date"].iloc[-1]),
        "valuation_pct_3y": round(pct, 4) if pct is not None else None,
        "from_52w_high": round(from_high, 4) if from_high is not None else None,
        "rsi12": round(rsi, 1) if rsi is not None else None,
        "entry_signals": signals,
        "status": "可关注买点" if signals else "等待更好买点",
    }


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
    ind = compute_indicators(prices)
    ma5, ma20, ma60 = ind["ma"]["ma5"], ind["ma"]["ma20"], ind["ma"]["ma60"]
    rsi = ind["rsi"]["rsi12"]
    macd_state = ind["macd"]["state"]
    below_ma60 = (latest < ma60) if ma60 else None

    # 确认离场（滞后，风险已兑现）——兜底止损
    exit_flags = []
    if ret_since <= DRAWDOWN_TRIGGER:
        exit_flags.append(f"浮亏 {ret_since * 100:.0f}%，触发熔断线（{DRAWDOWN_TRIGGER * 100:.0f}%）")
    if dd_from_peak <= DRAWDOWN_TRIGGER:
        exit_flags.append(f"自持有期高点回撤 {dd_from_peak * 100:.0f}%")
    if below_ma60:
        exit_flags.append("跌破 MA60（中期趋势已转弱）")

    # 提前预警（领先，大跌之前就示警）——主动减仓/提高警惕
    early = []
    if pct is not None and pct >= VALUATION_HIGH:
        early.append(f"估值近 3 年 {pct * 100:.0f}% 高位，回调风险升高，考虑逢高减")
    if rsi is not None and rsi >= 75:
        early.append(f"RSI {rsi:.0f} 超买，短期过热")
    if macd_state == "死叉":
        early.append("MACD 死叉，动能转弱（早于跌破 MA60）")
    if ma5 and ma20 and ma5 < ma20 and not below_ma60:
        early.append("短期均线走弱（MA5<MA20），中期趋势或承压")
    if ma60 and latest > ma60 * 1.3:
        early.append(f"价格高出 MA60 约 {(latest / ma60 - 1) * 100:.0f}%，超涨易回归")

    status = "需离场" if exit_flags else ("留意" if early else "正常持有")
    return {
        "latest": round(latest, 4),
        "latest_date": str(prices["date"].iloc[-1]),
        "return_since_entry": round(ret_since, 4),
        "drawdown_from_peak_since_entry": round(dd_from_peak, 4),
        "max_drawdown_since_entry": round(max_dd_since, 4),
        "valuation_pct_3y": round(pct, 4) if pct is not None else None,
        "below_ma60": below_ma60,
        "early_warnings": early,   # 提前判断（领先）
        "exit_flags": exit_flags,  # 确认离场（滞后兜底）
        "status": status,
    }
