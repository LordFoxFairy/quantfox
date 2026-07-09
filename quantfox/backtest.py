"""历史回测（机械规则基线，非 LLM 判断的回测）。

诚实边界：真正下判断的是 LLM，无法便宜地重放几年历史；这里回测的是**确定性规则**
（估值均值回归 / 趋势 / 组合），给出一份**上线前就有的样本外战绩基线**——LLM 应以此为下限争取超越。
严格 point-in-time（每个决策点只用截至当日的数据）、扣交易成本、对比无条件上涨基率与买入持有。
"""
import pandas as pd

from .storage import round_trip_cost


def _pct_rank(win: pd.Series) -> float:
    return float((win <= win.iloc[-1]).mean())


def rule_valuation(s: pd.Series) -> int:
    """估值均值回归：低分位买、高分位回避。"""
    if len(s) < 252:
        return 0
    win = s.tail(252 * 3)
    pct = _pct_rank(win)
    if pct < 0.3:
        return 1
    if pct > 0.8:
        return -1
    return 0


def rule_trend(s: pd.Series) -> int:
    """趋势：均线多头买、空头回避。"""
    if len(s) < 60:
        return 0
    ma5, ma20, ma60 = s.tail(5).mean(), s.tail(20).mean(), s.tail(60).mean()
    if ma5 >= ma20 >= ma60:
        return 1
    if ma5 <= ma20 <= ma60:
        return -1
    return 0


def rule_combo(s: pd.Series) -> int:
    """组合：估值不高 + 趋势向上才买。"""
    v, t = rule_valuation(s), rule_trend(s)
    if t > 0 and v >= 0 and (len(s) < 252 or _pct_rank(s.tail(252 * 3)) < 0.6):
        return 1
    if t < 0 or v < 0:
        return -1
    return 0


RULES = {"valuation": rule_valuation, "trend": rule_trend, "combo": rule_combo}


def _max_drawdown(equity: pd.Series) -> float:
    return float((equity / equity.cummax() - 1.0).min())


def backtest(prices: pd.DataFrame, rule: str = "valuation", horizon: int = 20,
             asset_type: str = "otc_fund", warmup: int = 252) -> dict:
    fn = RULES.get(rule)
    if fn is None:
        raise ValueError(f"未知规则 {rule}，可选 {list(RULES)}")
    s = prices["value"].reset_index(drop=True).astype(float)
    n = len(s)
    if n < warmup + horizon + 1:
        return {"rule": rule, "horizon": horizon, "n_windows": 0,
                "note": "历史数据不足以回测"}

    # 全序列 h 期前瞻上涨基率（point-in-time 无关，用于对照"跟涨"）
    fwd_all = s.shift(-horizon) / s - 1.0
    base_up = float((fwd_all.dropna() > 0).mean())
    cost = round_trip_cost(horizon, asset_type)

    buy_rets, buy_hits, avoid_hits = [], [], []
    avoid_n = 0
    period_rets = []  # 非重叠窗口，构建策略净值
    t = warmup
    while t + horizon < n:
        sig = fn(s.iloc[:t + 1])  # 只用截至 t 的数据
        fwd = float(s.iloc[t + horizon] / s.iloc[t] - 1.0)
        if sig > 0:
            net = fwd - cost
            buy_rets.append(net)
            buy_hits.append(1 if net > 0 else 0)
            period_rets.append(net)
        else:
            period_rets.append(0.0)  # 不买=持币
            if sig < 0:
                avoid_n += 1
                avoid_hits.append(1 if fwd < 0 else 0)
        t += horizon  # 非重叠

    prets = pd.Series(period_rets)
    # 策略净值：从 1.0 起，每个非重叠窗口乘 (1+净收益)。（修复：不再把起始 1.0 当成一次收益）
    equity = pd.concat([pd.Series([1.0]), (1.0 + prets).cumprod()], ignore_index=True) \
        if period_rets else pd.Series([1.0])
    ann = 252 / horizon
    sharpe = float(prets.mean() / prets.std() * (ann ** 0.5)) if prets.std() else None
    buy_hr = (sum(buy_hits) / len(buy_hits)) if buy_hits else None
    bh = float(s.iloc[t] / s.iloc[warmup] - 1.0)  # 同期买入持有
    # 标的真实日度最大回撤（策略净值只按窗口端点算，会低估路径回撤，故补这个真实风险参照）
    asset_dd = _max_drawdown(s.iloc[warmup:t + 1])

    return {
        "rule": rule, "horizon": horizon, "n_windows": len(period_rets),
        "base_up_rate": round(base_up, 4),
        "buy": {
            "n": len(buy_rets),
            "hit_rate": round(buy_hr, 4) if buy_hr is not None else None,
            "avg_net_return": round(sum(buy_rets) / len(buy_rets), 4) if buy_rets else None,
            "edge_vs_baserate": round(buy_hr - base_up, 4) if buy_hr is not None else None,
        },
        "avoid": {"n": avoid_n,
                  "hit_rate": round(sum(avoid_hits) / len(avoid_hits), 4) if avoid_hits else None},
        "strategy": {
            "total_return": round(float(equity.iloc[-1] - 1.0), 4),
            "sharpe": round(sharpe, 4) if sharpe is not None else None,
            "max_drawdown_windowed": round(_max_drawdown(equity), 4),
            "asset_max_drawdown_daily": round(asset_dd, 4),
        },
        "buy_and_hold_return": round(bh, 4),
        "note": ("机械规则基线（非 LLM 判断的回测）；point-in-time、已扣成本。"
                 "策略回撤按窗口端点算会低估路径回撤，asset_max_drawdown_daily 是标的真实日度回撤参照。"
                 "edge>0 且扣成本后 net>0、夏普/回撤优于买入持有才算规则有效；否则只是跟涨。LLM 应以此为下限争取超越。"),
    }
