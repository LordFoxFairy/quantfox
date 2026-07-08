import pandas as pd


def _f(x):
    return None if x is None or pd.isna(x) else float(x)


def _ret(s: pd.Series, n: int):
    if len(s) <= n:
        return None
    return _f(s.iloc[-1] / s.iloc[-1 - n] - 1.0)


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _rsi(s: pd.Series, length: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # Wilder 平滑
    avg_gain = gain.ewm(alpha=1.0 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, adjust=False).mean()
    total = avg_gain + avg_loss
    # 等价于 100 - 100/(1+rs)，但无除零：全程上涨→100，全程下跌→0，纯平盘→NaN
    return 100.0 * avg_gain / total.replace(0.0, float("nan"))


def compute_indicators(df: pd.DataFrame) -> dict:
    s = df["value"].reset_index(drop=True).astype(float)
    n = len(s)

    def ma(w):
        return _f(s.rolling(w).mean().iloc[-1]) if n >= w else None

    ma5, ma10, ma20, ma60 = ma(5), ma(10), ma(20), ma(60)
    if None not in (ma5, ma10, ma20, ma60):
        if ma5 >= ma10 >= ma20 >= ma60:
            alignment = "多头"
        elif ma5 <= ma10 <= ma20 <= ma60:
            alignment = "空头"
        else:
            alignment = "纠缠"
    else:
        alignment = "纠缠"

    if n >= 35:
        dif_s = _ema(s, 12) - _ema(s, 26)
        dea_s = _ema(dif_s, 9)
        hist_s = dif_s - dea_s
        dif, dea, hist = _f(dif_s.iloc[-1]), _f(dea_s.iloc[-1]), _f(hist_s.iloc[-1])
        prev_hist = _f(hist_s.iloc[-2]) if len(hist_s) >= 2 else None
        state = "—"
        if prev_hist is not None and hist is not None:
            if prev_hist <= 0 < hist:
                state = "金叉"
            elif prev_hist >= 0 > hist:
                state = "死叉"
    else:
        dif = dea = hist = None
        state = "—"

    rsi = _f(_rsi(s, 14).iloc[-1]) if n >= 15 else None

    if n >= 20:
        mid = s.rolling(20).mean()
        std = s.rolling(20).std()
        lower = _f((mid - 2 * std).iloc[-1])
        upper = _f((mid + 2 * std).iloc[-1])
        last = _f(s.iloc[-1])
        width = _f(upper - lower) if None not in (upper, lower) else None
        if None not in (lower, upper, last):
            span = (upper - lower) or 1.0
            r = (last - lower) / span
            pos = "上轨附近" if r >= 0.8 else ("下轨附近" if r <= 0.2 else "中轨")
        else:
            pos = "中轨"
    else:
        pos, width = "中轨", None

    dd = None
    if n >= 60:
        window = s.iloc[-252:] if n >= 252 else s
        dd = _f((window / window.cummax() - 1.0).min())

    vol = None
    if n >= 30:
        window = s.iloc[-252:] if n >= 252 else s
        vol = _f(window.pct_change().std() * (252 ** 0.5))

    return {
        "ma": {"ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60, "alignment": alignment},
        "macd": {"dif": dif, "dea": dea, "hist": hist, "state": state},
        "rsi14": rsi,
        "boll": {"pos": pos, "width": width},
        "returns": {"1w": _ret(s, 5), "1m": _ret(s, 20), "3m": _ret(s, 60), "1y": _ret(s, 250)},
        "max_drawdown_1y": dd,
        "volatility_1y": vol,
    }
