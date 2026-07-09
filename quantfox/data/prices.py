import pandas as pd

from .resolve import Asset

# 列名映射（实测见 docs/akshare-interfaces.md）
_FUND_DATE_COLS = ["净值日期", "date"]
_FUND_VALUE_COLS = ["累计净值", "复权单位净值", "单位净值", "value"]
_GOLD_DATE_COLS = ["date", "日期"]
_GOLD_CLOSE_COLS = ["close", "收盘价", "收盘"]
_GOLD_OPEN_COLS = ["open", "开盘价", "开盘"]
_GOLD_HIGH_COLS = ["high", "最高价", "最高"]
_GOLD_LOW_COLS = ["low", "最低价", "最低"]


def _pick(df: pd.DataFrame, candidates, required=True):
    for c in candidates:
        if c in df.columns:
            return c
    if required:
        raise KeyError(f"未找到列，候选={candidates}，实际={list(df.columns)}")
    return None


def _normalize_dates(values) -> pd.Series:
    s = pd.Series(values)
    raw = s.dropna()
    if raw.empty:
        return pd.to_datetime(s, errors="coerce").dt.strftime("%Y-%m-%d")

    as_text = raw.astype(str).str.strip()
    if as_text.str.fullmatch(r"\d{8}").all():
        parsed = pd.to_datetime(s.astype(str).str.strip(), format="%Y%m%d", errors="coerce")
    elif as_text.str.fullmatch(r"\d{13}").all():
        parsed = pd.to_datetime(pd.to_numeric(s, errors="coerce"), unit="ms", errors="coerce")
    elif as_text.str.fullmatch(r"\d{10}").all():
        parsed = pd.to_datetime(pd.to_numeric(s, errors="coerce"), unit="s", errors="coerce")
    else:
        parsed = pd.to_datetime(s, errors="coerce")
    return parsed.dt.strftime("%Y-%m-%d")


def _normalize_close_only(df: pd.DataFrame, date_cols, value_cols) -> pd.DataFrame:
    d, v = _pick(df, date_cols), _pick(df, value_cols)
    out = df[[d, v]].rename(columns={d: "date", v: "value"}).copy()
    out["date"] = _normalize_dates(out["date"])
    out["value"] = out["value"].astype(float)
    out = out.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)
    return out[["date", "value"]]


def _normalize_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    d = _pick(df, _GOLD_DATE_COLS)
    c = _pick(df, _GOLD_CLOSE_COLS)
    o = _pick(df, _GOLD_OPEN_COLS, required=False)
    h = _pick(df, _GOLD_HIGH_COLS, required=False)
    low = _pick(df, _GOLD_LOW_COLS, required=False)
    cols = {d: "date", c: "value"}
    keep = [d, c]
    for src, dst in ((o, "open"), (h, "high"), (low, "low")):
        if src:
            cols[src] = dst
            keep.append(src)
    out = df[keep].rename(columns=cols).copy()
    out["date"] = _normalize_dates(out["date"])
    for col in ("value", "open", "high", "low"):
        if col in out.columns:
            out[col] = out[col].astype(float)
    out = out.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)
    ordered = ["date", "value"] + [c for c in ("open", "high", "low") if c in out.columns]
    return out[ordered]


def _default_fetcher(asset: Asset) -> pd.DataFrame:
    import akshare as ak

    if asset.type == "otc_fund":
        try:
            return ak.fund_open_fund_info_em(symbol=asset.symbol, indicator="累计净值走势")
        except Exception:  # noqa
            return ak.fund_open_fund_info_em(symbol=asset.symbol, indicator="单位净值走势")
    return ak.spot_hist_sge(symbol=asset.symbol)


def load_prices(asset: Asset, fetcher=None) -> pd.DataFrame:
    """返回 date, value(收盘/净值)；黄金额外带 open/high/low（用于 ATR/KDJ 等）。"""
    fetcher = fetcher or _default_fetcher
    raw = fetcher(asset)
    if asset.type == "otc_fund":
        return _normalize_close_only(raw, _FUND_DATE_COLS, _FUND_VALUE_COLS)
    return _normalize_ohlc(raw)


def has_ohlc(df: pd.DataFrame) -> bool:
    return all(c in df.columns for c in ("high", "low"))
