import json
from typing import Literal, Optional

import pandas as pd
from pydantic import BaseModel

from .data.prices import has_ohlc
from .data.resolve import Asset
from .indicators import compute_indicators
from .metrics import compute_metrics
from .percentile import price_percentile


SCHEMA_VERSION = "2.0"


class PriceBlock(BaseModel):
    latest: Optional[float] = None
    latest_date: Optional[str] = None


class DataQuality(BaseModel):
    price: Literal["ok", "stale", "partial", "missing"] = "missing"
    ohlc: Literal["available", "unavailable"] = "unavailable"
    profile: Literal["ok", "partial", "n/a"] = "n/a"
    notes: list[str] = []


class EvidenceCard(BaseModel):
    """证据卡。专业主料：profile(基本面) + metrics(风险绩效)；technical 指标为辅助。
    舆情不放这里——由 CC agent 自己用 WebSearch 搜最新的并鉴别。"""

    schema_version: str = SCHEMA_VERSION
    asset: Asset
    price: PriceBlock = PriceBlock()
    returns: dict = {}
    metrics: dict = {}
    profile: dict = {}
    indicators: dict = {}  # 辅助：技术指标
    percentile: dict = {}
    track_record: Optional[dict] = None
    data_quality: DataQuality = DataQuality()

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        m, ind, pf = self.metrics, self.indicators, self.profile
        lines = [f"# 证据卡：{self.asset.name or self.asset.symbol} ({self.asset.symbol})",
                 f"- 类型：{self.asset.type}  最新：{self.price.latest}（{self.price.latest_date}）"]
        if pf.get("applicable"):
            b = pf.get("basic") or {}
            h = pf.get("holdings") or {}
            r = pf.get("rating") or {}
            lines += [
                f"- 【基本面】{b.get('company')} · 经理 {b.get('manager')} · {b.get('type')} · 成立 {b.get('inception')} · 规模 {b.get('scale')}",
                f"- 【评级】晨星 {r.get('morningstar')} · 手续费 {r.get('fee')}",
                f"- 【重仓】前十占比 {h.get('top10_concentration')}%：" +
                "，".join(f"{x['name']}({x['pct']}%)" for x in (h.get('top') or [])[:5]),
            ]
        lines += [
            f"- 【收益】1w/1m/3m/6m/1y/YTD：{self.returns}",
            f"- 【绩效】CAGR={m.get('cagr')} 夏普={m.get('sharpe')} 索提诺={m.get('sortino')} 卡玛={m.get('calmar')}",
            f"- 【风险】最大回撤={m.get('max_drawdown')} 年化波动={m.get('ann_vol')} VaR95={m.get('var95')} 胜率={m.get('win_rate')}",
            f"- 【估值】历史分位：{self.percentile}  价格位置：{ind.get('price_levels')}",
            f"- 【技术(辅助)】均线={ind.get('ma', {}).get('alignment')} MACD={ind.get('macd', {}).get('state')} "
            f"RSI={ind.get('rsi')} OHLC类={ind.get('ohlc', {}).get('available')}",
            f"- 战绩：{self.track_record}",
            f"- 数据质量：price={self.data_quality.price} ohlc={self.data_quality.ohlc} "
            f"profile={self.data_quality.profile} {self.data_quality.notes}",
        ]
        return "\n".join(lines)


def build_evidence(
    asset: Asset,
    *,
    prices: pd.DataFrame,
    profile: dict,
    track_record: Optional[dict],
) -> EvidenceCard:
    notes: list[str] = []
    returns: dict = {}
    metrics: dict = {}
    indicators: dict = {}
    pct: dict = {}
    ohlc = "unavailable"

    if prices is None or len(prices) == 0:
        price = PriceBlock()
        pq = "missing"
        notes.append("无价格数据")
    else:
        met = compute_metrics(prices)
        returns = met.pop("returns", {})
        metrics = met
        indicators = compute_indicators(prices)
        pct = price_percentile(prices, years=3)
        price = PriceBlock(
            latest=float(prices["value"].iloc[-1]),
            latest_date=str(prices["date"].iloc[-1]),
        )
        pq = "ok" if len(prices) >= 252 else "partial"
        if pq == "partial":
            notes.append("价格数据不足一年，指标与风险绩效置信度下调")
        ohlc = "available" if has_ohlc(prices) else "unavailable"
        if ohlc == "unavailable":
            notes.append("场外基金仅净值：ATR/KDJ/CCI/Williams%R/ADX 不可用")

    profile = profile or {}
    if not profile.get("applicable"):
        pfq = "n/a"
    elif profile.get("basic") and profile.get("holdings", {}).get("top"):
        pfq = "ok"
    else:
        pfq = "partial"
        notes.append("部分基本面/持仓数据缺失")

    return EvidenceCard(
        asset=asset, price=price, returns=returns, metrics=metrics,
        profile=profile, indicators=indicators, percentile=pct,
        track_record=track_record,
        data_quality=DataQuality(price=pq, ohlc=ohlc, profile=pfq, notes=notes),
    )
