"""风险 / 绩效指标。仅需收盘价（value 列），场外基金与黄金均可算。

约定：日频；年化因子 √252；无风险利率 rf 默认 2%/年（日 rf_d = 0.02/252）。
数据不足（<30 个交易日）时相关字段返回 None，避免噪音。
"""
import pandas as pd

ANN = 252
RF_ANNUAL = 0.02


def _f(x):
    return None if x is None or pd.isna(x) else float(x)


def _ret(s: pd.Series, n: int):
    if len(s) <= n:
        return None
    return _f(s.iloc[-1] / s.iloc[-1 - n] - 1.0)


def _ytd(df: pd.DataFrame):
    dates = pd.to_datetime(df["date"])
    year = dates.iloc[-1].year
    mask = dates.dt.year == year
    sub = df.loc[mask, "value"].reset_index(drop=True)
    if len(sub) < 2:
        return None
    return _f(sub.iloc[-1] / sub.iloc[0] - 1.0)


def compute_metrics(df: pd.DataFrame, rf: float = RF_ANNUAL) -> dict:
    s = df["value"].reset_index(drop=True).astype(float)
    n = len(s)
    returns = {
        "1w": _ret(s, 5), "1m": _ret(s, 20), "3m": _ret(s, 60),
        "6m": _ret(s, 120), "1y": _ret(s, 250), "ytd": _ytd(df),
    }
    if n < 30:
        empty = dict.fromkeys(
            ["cagr", "ann_vol", "max_drawdown", "sharpe", "sortino", "calmar",
             "var95", "cvar95", "downside_dev", "win_rate", "skew", "kurtosis"], None
        )
        return {"returns": returns, **empty, "note": "样本不足30日，风险指标不可靠"}

    r = s.pct_change().dropna()
    rf_d = rf / ANN
    mean_d, std_d = r.mean(), r.std()

    # 年化收益（CAGR），按实际交易日数折算
    cagr = _f((s.iloc[-1] / s.iloc[0]) ** (ANN / (n - 1)) - 1.0)
    ann_vol = _f(std_d * (ANN ** 0.5))

    # 最大回撤
    max_dd = _f((s / s.cummax() - 1.0).min())

    # 夏普
    sharpe = _f((mean_d - rf_d) / std_d * (ANN ** 0.5)) if std_d else None

    # 下行标准差（MAR=0）与索提诺
    downside = r.clip(upper=0.0)
    dd_daily = float((downside.pow(2).mean()) ** 0.5)
    downside_dev = _f(dd_daily * (ANN ** 0.5))
    sortino = _f((mean_d - rf_d) / dd_daily * (ANN ** 0.5)) if dd_daily else None

    # 卡玛（年化收益 / 最大回撤）
    calmar = _f(cagr / abs(max_dd)) if (cagr is not None and max_dd not in (None, 0.0)) else None

    # VaR / CVaR（历史法，95%，日频，负数=潜在单日亏损）
    var95 = _f(r.quantile(0.05))
    tail = r[r <= (var95 if var95 is not None else r.quantile(0.05))]
    cvar95 = _f(tail.mean()) if len(tail) else None

    return {
        "returns": returns,
        "cagr": cagr,
        "ann_vol": ann_vol,
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "var95": var95,
        "cvar95": cvar95,
        "downside_dev": downside_dev,
        "win_rate": _f((r > 0).mean()),
        "skew": _f(r.skew()),
        "kurtosis": _f(r.kurt()),
        "note": "rf=2%,年化√252,VaR/CVaR为日频历史法95%",
    }
