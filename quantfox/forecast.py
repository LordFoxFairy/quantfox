"""前瞻收益分布（不是点预测！）。

用该基金历史滚动，算持有 h 交易日的前瞻收益**分布**：正收益概率 / 中位(最可能) / 均值 /
p10–p90 / 历史极值。并给**估值条件化**版本——只用"当时估值分位与现在相近"的历史点，
回答"从现在这么贵的位置买入，历史上会怎样"，量化"别在山顶买"。

铁律：① 看中位别看均值（均值被牛市尾部拉高）；② 这是历史统计推断、样本偏牛市、当前高估值应向下打折；
③ 绝不输出单一点数字冒充"预测"；④ 非承诺、决策自负。
"""
import pandas as pd

from .percentile import price_percentile


def _dist(fwd: pd.Series) -> dict:
    return {
        "n": int(len(fwd)),
        "p_positive": round(float((fwd > 0).mean()), 4),
        "median": round(float(fwd.median()), 4),   # 最可能——看这个
        "mean": round(float(fwd.mean()), 4),        # 被牛市尾部拉高，别信
        "p10": round(float(fwd.quantile(0.10)), 4),  # 悲观
        "p90": round(float(fwd.quantile(0.90)), 4),  # 乐观
        "worst": round(float(fwd.min()), 4),
        "best": round(float(fwd.max()), 4),
    }


def forecast(prices: pd.DataFrame, horizons=(20, 60, 120, 250)) -> dict:
    s = prices["value"].astype(float).reset_index(drop=True)
    n = len(s)
    cur_pct = price_percentile(prices, 3).get("price_pct")
    # 每个历史点的滚动 3 年估值分位（point-in-time）
    win = 252 * 3
    trail_pct = s.rolling(win, min_periods=252).apply(lambda x: (x <= x[-1]).mean(), raw=True)

    out = {}
    for h in horizons:
        fwd_all = s.shift(-h) / s - 1.0
        fa = fwd_all.dropna()
        d = {"all": _dist(fa)} if len(fa) >= 60 else {"all": {"n": int(len(fa)), "note": "样本不足，别当真"}}
        if cur_pct is not None:
            band = (trail_pct >= max(0.0, cur_pct - 0.1)) & (trail_pct <= min(1.0, cur_pct + 0.1))
            fc = fwd_all[band & fwd_all.notna()].dropna()
            if len(fc) >= 30:
                d["from_similar_valuation"] = _dist(fc)
        out[str(h)] = d

    return {
        "current_valuation_pct": round(cur_pct, 4) if cur_pct is not None else None,
        "horizons_note": "键为交易日：20≈1月 / 60≈3月 / 120≈6月 / 250≈1年",
        "horizons": out,
        "note": ("历史滚动前瞻收益分布，非预测非承诺。**看中位(median)别看均值(mean)**——均值被牛市尾部拉高。"
                 "`from_similar_valuation` 是'从当前估值分位买入'的历史分布，更贴合现在；样本偏牛市，"
                 "当前分位高则实际应更保守。决策与风险自负。"),
    }
