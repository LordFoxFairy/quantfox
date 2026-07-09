"""全市场基金榜单取数（粗筛用）。一次拿某类基金的多周期收益，不逐只抓净值——稳、快。"""
import pandas as pd

from .resolve import Asset  # noqa: F401  (保持包结构一致)

# akshare fund_open_fund_rank_em 返回列 → 干净键（实测见 docs/akshare-interfaces.md）
_RET_COLS = {
    "近1周": "r_1w", "近1月": "r_1m", "近3月": "r_3m", "近6月": "r_6m",
    "近1年": "r_1y", "近2年": "r_2y", "近3年": "r_3y", "今年来": "ytd",
}
FUND_TYPES = ["全部", "股票型", "混合型", "债券型", "指数型", "QDII", "FOF"]


def _fee_to_float(x):
    if pd.isna(x):
        return None
    s = str(x).strip().replace("%", "")
    try:
        return round(float(s) / 100.0, 6)
    except ValueError:
        return None


def _default_fetcher(fund_type: str) -> pd.DataFrame:
    import akshare as ak

    return ak.fund_open_fund_rank_em(symbol=fund_type)


def load_universe(fund_type: str = "股票型", fetcher=None) -> pd.DataFrame:
    fetcher = fetcher or _default_fetcher
    raw = fetcher(fund_type)
    out = pd.DataFrame({
        "code": raw["基金代码"].astype(str),
        "name": raw["基金简称"].astype(str),
    })
    for zh, key in _RET_COLS.items():
        out[key] = pd.to_numeric(raw[zh], errors="coerce") if zh in raw.columns else None
    out["fee"] = raw["手续费"].map(_fee_to_float) if "手续费" in raw.columns else None
    return out
