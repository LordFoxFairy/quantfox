import pandas as pd

from .resolve import Asset

# 列名映射（实测见 docs/akshare-interfaces.md）
_FUND_DATE_COLS = ["净值日期", "date"]
_FUND_VALUE_COLS = ["单位净值", "value"]
_GOLD_DATE_COLS = ["date", "日期"]
_GOLD_VALUE_COLS = ["close", "收盘价", "收盘"]


def _pick(df: pd.DataFrame, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    raise KeyError(f"未找到列，候选={candidates}，实际={list(df.columns)}")


def _normalize(df: pd.DataFrame, date_cols, value_cols) -> pd.DataFrame:
    d, v = _pick(df, date_cols), _pick(df, value_cols)
    out = df[[d, v]].rename(columns={d: "date", v: "value"}).copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out["value"] = out["value"].astype(float)
    out = out.dropna().sort_values("date").reset_index(drop=True)
    return out[["date", "value"]]


def _default_fetcher(asset: Asset) -> pd.DataFrame:
    import akshare as ak

    if asset.type == "otc_fund":
        return ak.fund_open_fund_info_em(symbol=asset.symbol, indicator="单位净值走势")
    return ak.spot_hist_sge(symbol=asset.symbol)


def load_prices(asset: Asset, fetcher=None) -> pd.DataFrame:
    fetcher = fetcher or _default_fetcher
    raw = fetcher(asset)
    if asset.type == "otc_fund":
        return _normalize(raw, _FUND_DATE_COLS, _FUND_VALUE_COLS)
    return _normalize(raw, _GOLD_DATE_COLS, _GOLD_VALUE_COLS)
