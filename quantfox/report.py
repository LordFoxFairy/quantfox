"""把证据卡数据 + CC 的判断，渲染成一份自包含可视化 HTML 报告（ECharts）。

引擎负责：图表数据、布局、指标卡（确定性）。
CC 负责：verdict/评分/深度解读/风险（判断），以 analysis dict 传入。
"""
import json
from pathlib import Path

import pandas as pd

from .data.fund_profile import load_profile
from .data.prices import has_ohlc, load_prices
from .data.resolve import Asset, resolve
from .metrics import compute_metrics
from .percentile import price_percentile

_TEMPLATE = Path(__file__).resolve().parent.parent / "skills" / "fund-analyze" / "assets" / "report_template.html"
_SHOW = 250  # 图表展示最近 N 个交易日


def _tone(x, good_positive=True):
    if x is None:
        return "flat"
    if good_positive:
        return "pos" if x >= 0 else "neg"
    return "neg" if x >= 0 else "pos"


def _pct(x):
    return "—" if x is None else f"{x * 100:.2f}%"


def _num(x, nd=2):
    return "—" if x is None else f"{x:.{nd}f}"


def _series_or_none(s: pd.Series):
    return [None if pd.isna(v) else round(float(v), 4) for v in s]


def build_report_data(asset: Asset, prices: pd.DataFrame, profile: dict, analysis: dict) -> dict:
    df = prices.tail(_SHOW).reset_index(drop=True)
    dates = list(df["date"])
    close = df["value"]
    met = compute_metrics(prices)
    pct = price_percentile(prices, years=3)

    price_block = {"dates": dates, "ma20": None, "ma60": None}
    if has_ohlc(prices):
        price_block["kline"] = [
            [round(float(r["open"]), 4), round(float(r["value"]), 4),
             round(float(r["low"]), 4), round(float(r["high"]), 4)]
            for _, r in df.iterrows()
        ]
    else:
        price_block["nav"] = _series_or_none(close)
    full_close = prices["value"].reset_index(drop=True)
    price_block["ma20"] = _series_or_none(full_close.rolling(20).mean().tail(_SHOW))
    price_block["ma60"] = _series_or_none(full_close.rolling(60).mean().tail(_SHOW))

    dd = (close / close.cummax() - 1.0)
    drawdown = _series_or_none(dd)

    holdings = []
    if profile.get("applicable"):
        for h in (profile.get("holdings") or {}).get("top", [])[:10]:
            if h.get("pct"):
                holdings.append({"name": h["name"], "pct": round(h["pct"], 2)})

    ret = met.get("returns", {})
    cards = [
        {"label": "最新价/净值", "value": _num(float(close.iloc[-1]), 4), "tone": "flat"},
        {"label": "近1年", "value": _pct(ret.get("1y")), "tone": _tone(ret.get("1y"))},
        {"label": "今年来", "value": _pct(ret.get("ytd")), "tone": _tone(ret.get("ytd"))},
        {"label": "最大回撤", "value": _pct(met.get("max_drawdown")), "tone": "neg"},
        {"label": "年化波动", "value": _pct(met.get("ann_vol")), "tone": "flat"},
        {"label": "夏普", "value": _num(met.get("sharpe")), "tone": _tone(met.get("sharpe"))},
        {"label": "卡玛", "value": _num(met.get("calmar")), "tone": _tone(met.get("calmar"))},
        {"label": "历史分位", "value": _pct(pct.get("price_pct")), "tone": _tone(pct.get("price_pct"), good_positive=False)},
    ]

    verdict = analysis.get("verdict") or {"label": "观望", "klass": "hold", "score": 50}
    return {
        "title": analysis.get("title") or f"{asset.name or asset.symbol} 分析报告",
        "subtitle": analysis.get("subtitle") or f"{asset.symbol} · {asset.type}",
        "verdict": verdict,
        "dimensions": analysis.get("dimensions") or [],
        "price": price_block,
        "drawdown": drawdown,
        "holdings": holdings,
        "metrics": cards,
        "commentary_html": analysis.get("commentary_html") or "<p>（无解读）</p>",
        "risks_html": analysis.get("risks_html") or "（无）",
        "footer": analysis.get("footer") or "数据来源 akshare · 本报告基于公开数据，非投资建议，不保证盈利，决策与风险自负。",
    }


def render_html(data: dict) -> str:
    tpl = _TEMPLATE.read_text(encoding="utf-8")
    return tpl.replace("__REPORT_JSON__", json.dumps(data, ensure_ascii=False)).replace("__TITLE__", data["title"])


def build_report(query: str, analysis: dict | None = None) -> str:
    asset = resolve(query)
    prices = load_prices(asset)
    profile = load_profile(asset)
    data = build_report_data(asset, prices, profile, analysis or {})
    return render_html(data)
