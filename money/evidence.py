import json
from typing import Literal, Optional

import pandas as pd
from pydantic import BaseModel

from .data.resolve import Asset
from .indicators import compute_indicators
from .percentile import price_percentile


class PriceBlock(BaseModel):
    latest: Optional[float] = None
    latest_date: Optional[str] = None
    returns: dict = {}
    max_drawdown_1y: Optional[float] = None
    volatility_1y: Optional[float] = None


class DataQuality(BaseModel):
    price: Literal["ok", "stale", "partial", "missing"] = "missing"
    news: Literal["ok", "sparse", "missing"] = "missing"
    notes: list[str] = []


class EvidenceCard(BaseModel):
    schema_version: str = "1.0"
    asset: Asset
    price: PriceBlock = PriceBlock()
    indicators: dict = {}
    percentile: dict = {}
    news: list[dict] = []
    track_record: Optional[dict] = None
    data_quality: DataQuality = DataQuality()

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        p = self.price
        lines = [
            f"# 证据卡：{self.asset.name or self.asset.symbol} ({self.asset.symbol})",
            f"- 类型：{self.asset.type}  最新：{p.latest}（{p.latest_date}）",
            f"- 收益 1w/1m/3m/1y：{p.returns}",
            f"- 最大回撤1y：{p.max_drawdown_1y}  年化波动：{p.volatility_1y}",
            f"- 均线：{self.indicators.get('ma')}",
            f"- MACD：{self.indicators.get('macd')}  RSI14：{self.indicators.get('rsi14')}",
            f"- 布林：{self.indicators.get('boll')}  历史分位：{self.percentile}",
            f"- 舆情条数：{len(self.news)}  战绩：{self.track_record}",
            f"- 数据质量：price={self.data_quality.price} news={self.data_quality.news} {self.data_quality.notes}",
        ]
        return "\n".join(lines)


def build_evidence(
    asset: Asset,
    *,
    prices: pd.DataFrame,
    news: list[dict],
    track_record: Optional[dict],
) -> EvidenceCard:
    notes: list[str] = []
    if prices is None or len(prices) == 0:
        price = PriceBlock()
        indicators: dict = {}
        pct: dict = {}
        pq = "missing"
        notes.append("无价格数据")
    else:
        ind = compute_indicators(prices)
        price = PriceBlock(
            latest=float(prices["value"].iloc[-1]),
            latest_date=str(prices["date"].iloc[-1]),
            returns=ind["returns"],
            max_drawdown_1y=ind["max_drawdown_1y"],
            volatility_1y=ind["volatility_1y"],
        )
        indicators = {k: ind[k] for k in ("ma", "macd", "rsi14", "boll")}
        pct = price_percentile(prices, years=3)
        pq = "ok" if len(prices) >= 252 else "partial"
        if pq == "partial":
            notes.append("价格数据不足一年，指标置信度下调")
    nq = "ok" if len(news) >= 3 else ("sparse" if news else "missing")
    return EvidenceCard(
        asset=asset,
        price=price,
        indicators=indicators,
        percentile=pct,
        news=news,
        track_record=track_record,
        data_quality=DataQuality(price=pq, news=nq, notes=notes),
    )
