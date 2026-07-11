"""前瞻收益分布（不是点预测！）。

用该基金历史滚动，算持有 h 交易日的前瞻收益**分布**：正收益概率 / 中位(最可能) / 均值 /
p10–p90 / 历史极值。并给**估值条件化**版本——只用"当时估值分位与现在相近"的历史点，
回答"从现在这么贵的位置买入，历史上会怎样"，量化"别在山顶买"。

铁律：① 看中位别看均值（均值被牛市尾部拉高）；② 这是历史统计推断、样本偏牛市、当前高估值应向下打折；
③ 绝不输出单一点数字冒充"预测"；④ 非承诺、决策自负。
"""
import numpy as np
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
        # 为 all 分布添加 warning（如果 n < 200 且不是 note dict）
        if "note" not in d["all"] and d["all"].get("n", 0) < 200:
            d["all"]["warning"] = "样本不足，谨慎参考"
        if cur_pct is not None:
            band = (trail_pct >= max(0.0, cur_pct - 0.1)) & (trail_pct <= min(1.0, cur_pct + 0.1))
            fc = fwd_all[band & fwd_all.notna()].dropna()
            if len(fc) >= 30:
                dist_fc = _dist(fc)
                # 为 from_similar_valuation 分布添加 warning（如果 n < 200）
                if dist_fc.get("n", 0) < 200:
                    dist_fc["warning"] = "样本不足，谨慎参考"
                d["from_similar_valuation"] = dist_fc
        out[str(h)] = d

    result = {
        "current_valuation_pct": round(cur_pct, 4) if cur_pct is not None else None,
        "horizons_note": "键为交易日：20≈1月 / 60≈3月 / 120≈6月 / 250≈1年",
        "horizons": out,
        "note": ("历史滚动前瞻收益分布，非预测非承诺。**看中位(median)别看均值(mean)**——均值被牛市尾部拉高。"
                 "`from_similar_valuation` 是'从当前估值分位买入'的历史分布，更贴合现在；样本偏牛市，"
                 "当前分位高则实际应更保守。决策与风险自负。"),
    }
    # 为顶层添加 age_warning（如果成立不足3年）
    if n < 756:
        result["age_warning"] = "成立不足3年，全部前瞻打折看待"
    return result


def simulate_paths(prices: pd.DataFrame, horizon_days: int, n_paths: int = 1000,
                   block: int = 20, conditional_pct=None, seed: int = 20260710):
    """块状自助抽样模拟未来逐日路径（保留波动聚集），供扇形图与短期波动锥共用。
    返回逐日百分位；估值条件化样本不足自动降级并如实标注；历史太短诚实弃权。"""
    s = prices["value"].astype(float).reset_index(drop=True)
    if len(s) < 120:
        return None
    rets = (s / s.shift(1) - 1.0).dropna().reset_index(drop=True).to_numpy()
    if len(rets) <= block:
        return None
    degraded = False
    starts = None
    if conditional_pct is not None:
        win = 252 * 3
        trail = s.rolling(win, min_periods=252).apply(lambda x: (x <= x[-1]).mean(), raw=True)
        band_idx = trail[(trail >= conditional_pct - 0.15) & (trail <= conditional_pct + 0.15)].index
        cand = [i - 1 for i in band_idx if 1 <= i <= len(rets) - block]
        if len(cand) >= 250:
            starts = cand
        else:
            degraded = True
    if starts is None:
        starts = list(range(0, len(rets) - block))
    rng = np.random.default_rng(seed)
    n_blocks = horizon_days // block + 1
    paths = np.empty((n_paths, horizon_days))
    for p in range(n_paths):
        idx = rng.choice(starts, size=n_blocks)
        chunk = np.concatenate([rets[i:i + block] for i in idx])[:horizon_days]
        paths[p] = np.cumprod(1.0 + chunk) - 1.0
    q = {k: np.percentile(paths, v, axis=0) for k, v in
         (("p10", 10), ("p25", 25), ("p50", 50), ("p75", 75), ("p90", 90))}
    out = {"days": list(range(1, horizon_days + 1)),
           **{k: [round(float(x), 4) for x in arr] for k, arr in q.items()},
           "prob_positive_terminal": round(float((paths[:, -1] > 0).mean()), 4),
           "n_paths": n_paths,
           "conditional": conditional_pct is not None and not degraded,
           "degraded_to_unconditional": degraded,
           "note": "历史统计推演，非预测承诺"}
    if len(s) < 500:
        out["warning"] = "样本不足，仅供参考"
    return out
