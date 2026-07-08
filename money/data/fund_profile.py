"""专业基金基本面：基本信息 / 持仓 / 评级 / 同类业绩。

这是引擎真正的护城河——CC agent 自己拿不到的数据。仅适用于场外基金；
黄金无基金经理/持仓/评级，返回 applicable=False。
依赖注入 fetchers 便于离线测试。
"""
import pandas as pd

from .resolve import Asset


def _default_fetchers():
    import datetime as _dt

    import akshare as ak

    year = str(_dt.date.today().year)

    def holdings(code):
        for y in (year, str(int(year) - 1)):
            try:
                df = ak.fund_portfolio_hold_em(symbol=code, date=y)
                if df is not None and len(df):
                    return df
            except Exception:  # noqa
                continue
        return pd.DataFrame()

    return {
        "basic": lambda code: ak.fund_individual_basic_info_xq(symbol=code),
        "holdings": holdings,
        "rating": lambda code: ak.fund_rating_all(),
    }


def _num(x):
    try:
        return None if pd.isna(x) else float(x)
    except Exception:  # noqa
        return None


def _parse_basic(df: pd.DataFrame) -> dict:
    d = {str(k): (None if pd.isna(v) else str(v)) for k, v in zip(df["item"], df["value"])}

    def pick(*keys):
        for k in keys:
            for item, val in d.items():
                if k in item and val:
                    return val
        return None

    return {
        "name": pick("基金名称", "基金简称"),
        "full_name": pick("基金全称"),
        "type": pick("基金类型", "类型"),
        "inception": pick("成立时间", "成立日期"),
        "scale": pick("最新规模", "基金规模", "规模"),
        "company": pick("基金公司", "管理人"),
        "manager": pick("基金经理"),
        "raw": d,
    }


def _top_holdings(df: pd.DataFrame, n: int = 10) -> dict:
    if df is None or not len(df):
        return {"as_of": None, "top": []}
    df = df.sort_values("占净值比例", ascending=False).head(n)
    as_of = str(df.iloc[0]["季度"]) if "季度" in df.columns else None
    top = [
        {"code": str(r["股票代码"]), "name": str(r["股票名称"]), "pct": _num(r["占净值比例"])}
        for _, r in df.iterrows()
    ]
    conc = _num(df["占净值比例"].sum())
    return {"as_of": as_of, "top10_concentration": conc, "top": top}


def _rating_for(df: pd.DataFrame, code: str):
    if df is None or "代码" not in df.columns:
        return None
    row = df[df["代码"].astype(str) == code]
    if row.empty:
        return None
    r = row.iloc[0]
    return {
        "stars5_count": _num(r.get("5星评级家数")),
        "morningstar": _num(r.get("晨星评级")),
        "shanghai": _num(r.get("上海证券")),
        "jian": _num(r.get("济安金信")),
        "fee": None if pd.isna(r.get("手续费")) else str(r.get("手续费")),
        "type": None if pd.isna(r.get("类型")) else str(r.get("类型")),
        "company": None if pd.isna(r.get("基金公司")) else str(r.get("基金公司")),
    }


def load_profile(asset: Asset, fetchers=None) -> dict:
    if asset.type != "otc_fund":
        return {"applicable": False, "note": "黄金无基金经理/持仓/评级，看宏观与价格"}
    fetchers = fetchers or _default_fetchers()
    out = {"applicable": True}
    try:
        out["basic"] = _parse_basic(fetchers["basic"](asset.symbol))
    except Exception as e:  # noqa
        out["basic"] = None
        out["basic_error"] = str(e)
    try:
        out["holdings"] = _top_holdings(fetchers["holdings"](asset.symbol))
    except Exception:  # noqa
        out["holdings"] = {"as_of": None, "top": []}
    try:
        out["rating"] = _rating_for(fetchers["rating"](asset.symbol), asset.symbol)
    except Exception:  # noqa
        out["rating"] = None
    return out
