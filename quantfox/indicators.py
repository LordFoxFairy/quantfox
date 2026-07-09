"""技术指标。全部基于成熟库 `ta` 计算——加一个指标 = 加一行，不手撸公式。

- 仅需收盘价的指标（MA/EMA/MACD/RSI/ROC/MOM/BOLL/HV/价格位置）：基金与黄金都算。
- 需要最高最低价的指标（ATR/KDJ/CCI/Williams%R/ADX）：黄金（有 OHLC）才算；
  基金仅净值 → 返回 None，由 data_quality 标注不可用。
"""
import pandas as pd
import ta


def _f(x):
    return None if x is None or pd.isna(x) else float(x)


def _last(series):
    try:
        return _f(series.iloc[-1])
    except Exception:  # noqa
        return None


def _ma_block(s: pd.Series, n: int) -> dict:
    def ma(w):
        return _f(s.rolling(w).mean().iloc[-1]) if n >= w else None

    ma5, ma10, ma20, ma60 = ma(5), ma(10), ma(20), ma(60)
    core = [ma5, ma10, ma20, ma60]
    if None not in core:
        if ma5 >= ma10 >= ma20 >= ma60:
            alignment = "多头"
        elif ma5 <= ma10 <= ma20 <= ma60:
            alignment = "空头"
        else:
            alignment = "纠缠"
    else:
        alignment = "纠缠"
    return {"ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
            "ma120": ma(120), "ma250": ma(250), "alignment": alignment}


def _macd_block(s: pd.Series, n: int) -> dict:
    if n < 35:
        return {"dif": None, "dea": None, "hist": None, "state": "—"}
    m = ta.trend.MACD(s)
    hist_s = m.macd_diff()
    dif, dea, hist = _last(m.macd()), _last(m.macd_signal()), _last(hist_s)
    prev = _f(hist_s.iloc[-2]) if len(hist_s) >= 2 else None
    state = "—"
    if prev is not None and hist is not None:
        state = "金叉" if prev <= 0 < hist else ("死叉" if prev >= 0 > hist else "—")
    return {"dif": dif, "dea": dea, "hist": hist, "state": state}


def _boll_block(s: pd.Series, n: int) -> dict:
    if n < 20:
        return {"pos": "中轨", "upper": None, "mid": None, "lower": None, "bandwidth": None}
    b = ta.volatility.BollingerBands(s, window=20, window_dev=2)
    upper, mid, lower = _last(b.bollinger_hband()), _last(b.bollinger_mavg()), _last(b.bollinger_lband())
    last = _f(s.iloc[-1])
    bandwidth = _f((upper - lower) / mid) if (None not in (upper, lower, mid) and mid) else None
    if None not in (lower, upper, last):
        span = (upper - lower) or 1.0
        r = (last - lower) / span
        pos = "上轨附近" if r >= 0.8 else ("下轨附近" if r <= 0.2 else "中轨")
    else:
        pos = "中轨"
    return {"pos": pos, "upper": upper, "mid": mid, "lower": lower, "bandwidth": bandwidth}


def _hv(s: pd.Series, w: int):
    if len(s) < w + 1:
        return None
    return _f(s.pct_change().tail(w).std() * (252 ** 0.5))


def _price_levels(s: pd.Series) -> dict:
    win = s.tail(250)
    hi, lo, last = _f(win.max()), _f(win.min()), _f(s.iloc[-1])
    pos = _f((last - lo) / (hi - lo)) if (None not in (hi, lo, last) and hi != lo) else None
    return {"high_52w": hi, "low_52w": lo, "pct_position": pos}


def _ohlc_block(df: pd.DataFrame) -> dict:
    """需要最高最低价的指标；无 OHLC 返回全 None（基金只有净值）。"""
    if not all(c in df.columns for c in ("high", "low")):
        return {"available": False, "atr14": None, "kdj": None,
                "cci14": None, "wr14": None, "adx14": None}
    c = df["value"].astype(float).reset_index(drop=True)
    h = df["high"].astype(float).reset_index(drop=True)
    low = df["low"].astype(float).reset_index(drop=True)

    atr = _last(ta.volatility.AverageTrueRange(h, low, c, window=14).average_true_range())
    cci = _last(ta.trend.CCIIndicator(h, low, c, window=14).cci())
    wr = _last(ta.momentum.WilliamsRIndicator(h, low, c, lbp=14).williams_r())
    adx = _last(ta.trend.ADXIndicator(h, low, c, window=14).adx())
    stoch = ta.momentum.StochasticOscillator(h, low, c, window=9, smooth_window=3)
    k, d = _last(stoch.stoch()), _last(stoch.stoch_signal())
    kdj = {"k": k, "d": d, "j": _f(3 * k - 2 * d)} if None not in (k, d) else None
    return {"available": True, "atr14": atr, "kdj": kdj, "cci14": cci, "wr14": wr, "adx14": adx}


def compute_indicators(df: pd.DataFrame) -> dict:
    s = df["value"].reset_index(drop=True).astype(float)
    n = len(s)
    return {
        "ma": _ma_block(s, n),
        "ema": {"ema12": _last(ta.trend.EMAIndicator(s, window=12).ema_indicator()) if n >= 12 else None,
                "ema26": _last(ta.trend.EMAIndicator(s, window=26).ema_indicator()) if n >= 26 else None},
        "macd": _macd_block(s, n),
        "rsi": {"rsi6": _last(ta.momentum.RSIIndicator(s, window=6).rsi()) if n >= 7 else None,
                "rsi12": _last(ta.momentum.RSIIndicator(s, window=12).rsi()) if n >= 13 else None,
                "rsi24": _last(ta.momentum.RSIIndicator(s, window=24).rsi()) if n >= 25 else None},
        "roc12": _last(ta.momentum.ROCIndicator(s, window=12).roc()) if n >= 13 else None,
        "mom10": _f(s.iloc[-1] - s.iloc[-11]) if n >= 11 else None,
        "boll": _boll_block(s, n),
        "hv": {"hv20": _hv(s, 20), "hv60": _hv(s, 60)},
        "price_levels": _price_levels(s),
        "ohlc": _ohlc_block(df),
    }
