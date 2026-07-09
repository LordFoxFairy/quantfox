"""全 A 股整体估值分位（宏观"贵不贵"锚）。

用 akshare stock_a_ttm_lyr：全市场 TTM 市盈率 + 近10年历史分位。
适用于给股票/指数基金判断大盘估值环境——分位高=整体偏贵，追高需谨慎。
"""
import pandas as pd

_PCT_COL = "quantileInRecent10YearsMiddlePeTtm"
_PE_COL = "middlePETTM"


def _default_fetcher() -> pd.DataFrame:
    import akshare as ak

    return ak.stock_a_ttm_lyr()


def _level(pct):
    if pct is None:
        return "未知"
    if pct < 0.3:
        return "便宜"
    if pct < 0.6:
        return "中性"
    if pct < 0.8:
        return "偏贵"
    return "贵"


def market_valuation(fetcher=None) -> dict:
    fetcher = fetcher or _default_fetcher
    df = fetcher()
    row = df.dropna(subset=[_PCT_COL]).iloc[-1] if _PCT_COL in df.columns and df[_PCT_COL].notna().any() else None
    if row is None:
        return {"available": False, "note": "无估值分位数据"}
    pct = float(row[_PCT_COL])
    return {
        "available": True,
        "date": str(row["date"]),
        "pe_ttm": round(float(row[_PE_COL]), 2),
        "percentile_10y": round(pct, 4),
        "level": _level(pct),
        "note": "全A股TTM市盈率近10年分位；分位越高整体越贵，对股票/指数基金追高越需谨慎",
    }
