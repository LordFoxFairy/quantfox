import datetime as _dt
import json
from typing import Literal, Optional

import pandas as pd
from pydantic import BaseModel

from .data.prices import has_ohlc
from .data.resolve import Asset
from .indicators import compute_indicators
from .metrics import compute_metrics
from .percentile import price_percentile


SCHEMA_VERSION = "2.1"

TRADING_DAYS_PER_YEAR = 252

# C2 假稳检测阈值（spec §2 C2 / §4 实证反例：014502 净值异常平滑、610108 债基踩雷）
NAV_SPIKE_MAX_DD = 0.03      # |max_drawdown| < 3%
NAV_SPIKE_MIN_VOL = 0.08     # 且 ann_vol > 8% → 回撤/波动不匹配，净值可疑
BOND_EQUITY_DD = -0.10       # 名为债基但 max_drawdown < -10%
SHORT_HISTORY_YEARS = 3.0    # 净值历史 < 3 年


def compute_flags(
    metrics: dict, fund_type: Optional[str], history_years: Optional[float]
) -> list[str]:
    """假稳/风险错配检测。输入缺失时对应 flag 不判，不误报。"""
    flags: list[str] = []
    max_dd = metrics.get("max_drawdown")
    ann_vol = metrics.get("ann_vol")

    if max_dd is not None and ann_vol is not None:
        if abs(max_dd) < NAV_SPIKE_MAX_DD and ann_vol > NAV_SPIKE_MIN_VOL:
            flags.append("nav_spike_suspect")

    if fund_type and "债" in fund_type and max_dd is not None and max_dd < BOND_EQUITY_DD:
        flags.append("bond_equity_risk")

    if history_years is not None and history_years < SHORT_HISTORY_YEARS:
        flags.append("short_history")

    return flags


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
    flags: list[str] = []  # C2 假稳/风险错配检测：nav_spike_suspect / bond_equity_risk / short_history

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
    today: Optional[_dt.date] = None,
) -> EvidenceCard:
    today = today or _dt.date.today()
    notes: list[str] = []
    returns: dict = {}
    metrics: dict = {}
    indicators: dict = {}
    pct: dict = {}
    ohlc = "unavailable"
    history_years: Optional[float] = None

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
        history_years = len(prices) / TRADING_DAYS_PER_YEAR
        pq = "ok" if len(prices) >= 252 else "partial"
        if pq == "partial":
            notes.append("价格数据不足一年，指标与风险绩效置信度下调")
        # 新鲜度：基金每交易日更新，>10 自然日没更新可疑（停牌/停更/接口滞后）
        try:
            last = _dt.date.fromisoformat(str(prices["date"].iloc[-1]))
            stale_days = (today - last).days
            if stale_days > 10:
                pq = "stale"
                notes.append(f"最新净值已 {stale_days} 天未更新，可能停牌/停更，买卖前务必核实")
        except (ValueError, TypeError):
            pass
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

    fund_type = (profile.get("basic") or {}).get("type") if profile.get("applicable") else None
    flags = compute_flags(metrics, fund_type, history_years)

    return EvidenceCard(
        asset=asset, price=price, returns=returns, metrics=metrics,
        profile=profile, indicators=indicators, percentile=pct,
        track_record=track_record,
        data_quality=DataQuality(price=pq, ohlc=ohlc, profile=pfq, notes=notes),
        flags=flags,
    )
