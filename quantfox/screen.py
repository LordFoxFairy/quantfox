"""全市场粗筛打分：长周期加权 + 一致性，压制"只近期暴涨"的追热陷阱。

只用榜单里的多周期收益排名，不做净值级风险计算（那放精筛/fund-analyze）。
输出 Top-N 候选，供 CC 在短名单上精挑。
"""
import pandas as pd

# 权重：长周期更重，降低"近1周/近1月暴涨"造成的追热
_WEIGHTS = {"r_3m": 0.15, "r_6m": 0.25, "r_1y": 0.35, "r_3y": 0.25}


def score_universe(df: pd.DataFrame) -> pd.DataFrame:
    work = df.dropna(subset=["r_1y"]).copy()  # 至少要有近1年，太新的不纳入
    if work.empty:
        return work.assign(score=[], consistent=[])
    pct = {}
    for col in _WEIGHTS:
        if col in work.columns:
            r = pd.to_numeric(work[col], errors="coerce")
            # 太新没有近3年的，用 0.5 中性填充，不奖不罚
            pct[col] = r.rank(pct=True).fillna(0.5)
        else:
            pct[col] = pd.Series(0.5, index=work.index)
    work["score"] = round(
        100 * sum(_WEIGHTS[c] * pct[c] for c in _WEIGHTS), 2
    )
    # 一致性：近1年 与 近3年 都在前 25% → 稳健常青，而非昙花一现
    work["consistent"] = (pct["r_1y"] >= 0.75) & (pct["r_3y"] >= 0.75)
    return work.sort_values("score", ascending=False).reset_index(drop=True)


def screen(df: pd.DataFrame, top: int = 100, consistent_only: bool = False) -> list[dict]:
    ranked = score_universe(df)
    if consistent_only:
        ranked = ranked[ranked["consistent"]]
    cols = ["code", "name", "score", "consistent", "r_3m", "r_6m", "r_1y", "r_3y", "fee"]
    cols = [c for c in cols if c in ranked.columns]
    return ranked.head(top)[cols].to_dict(orient="records")
