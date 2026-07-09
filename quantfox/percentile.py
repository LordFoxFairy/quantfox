import pandas as pd


def price_percentile(df: pd.DataFrame, years: int = 3) -> dict:
    s = df["value"].reset_index(drop=True)
    win = 252 * years
    note = f"最新值在近 {years} 年内的百分位（point-in-time）"
    if len(s) < 252:
        return {"price_pct": None, "window_years": years, "note": "数据不足一年，无法计算"}
    window = s.iloc[-win:] if len(s) >= win else s
    latest = window.iloc[-1]
    pct = float((window <= latest).mean())
    return {"price_pct": pct, "window_years": years, "note": note}
