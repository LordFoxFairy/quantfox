"""C1: 批量风险指标（screen 慢通道加速）。

只拉净值序列算 夏普/卡玛/最大回撤/年化波动/估值分位 五列，跳过 profile/持仓/评级
（那些是 fund-screener 精筛阶段的事）。并发 + 单只失败重试1次 + 失败标记，不中断整批。
"""
from __future__ import annotations

import concurrent.futures as cf
import threading
from typing import Optional

from .data.prices import load_prices
from .data.resolve import resolve
from .evidence import compute_flags
from .metrics import compute_metrics
from .percentile import price_percentile

DEFAULT_MAX_WORKERS = 4  # akshare 限流保守
DEFAULT_RETRIES = 1
TRADING_DAYS_PER_YEAR = 252

_warmup_lock = threading.Lock()
_warmed_up = False


def _warmup_js_engine() -> None:
    """规避 akshare 并发 native crash：`fund_open_fund_info_em` 内部用
    `py_mini_racer.MiniRacer()` 解密净值 JSON。实测（真实网络冒烟）多线程首次并发构造
    MiniRacer 会触发 `Check failed: !pool->IsInitialized()` 直接进程 abort——不是 Python
    异常，重试/except 完全防不住。在起线程池前主线程单线程预热一次，让该库的全局初始化
    只发生一次，后续并发构造就安全了（预热失败也不阻断，最坏退化回原风险）。"""
    global _warmed_up
    if _warmed_up:
        return
    with _warmup_lock:
        if _warmed_up:
            return
        try:
            import py_mini_racer

            py_mini_racer.MiniRacer()
        except Exception:  # noqa - 预热失败不阻断批量
            pass
        _warmed_up = True


def _history_years(df) -> Optional[float]:
    if df is None or len(df) == 0:
        return None
    return len(df) / TRADING_DAYS_PER_YEAR


def _compute_one(code: str) -> dict:
    """单只基金：只拉净值，算五列 + C2 flags。fund_type 未知（本函数不拉 profile），
    因此 bond_equity_risk 不判（compute_flags 输入缺失时不误报）。"""
    asset = resolve(code)
    prices = load_prices(asset)
    met = compute_metrics(prices)
    pct = price_percentile(prices, years=3)
    history_years = _history_years(prices)
    flags = compute_flags(met, None, history_years)
    v = prices["value"].astype(float)
    tail = v.tail(TRADING_DAYS_PER_YEAR)
    dist = round(1.0 - float(tail.iloc[-1]) / float(tail.max()), 4) if len(tail) else None
    ma_ok = bool(v.tail(20).mean() > v.tail(60).mean()) if len(v) >= 60 else None
    return {
        "code": asset.symbol,
        "name": asset.name,
        "sharpe": met.get("sharpe"),
        "calmar": met.get("calmar"),
        "max_drawdown": met.get("max_drawdown"),
        "ann_vol": met.get("ann_vol"),
        "price_pct": pct.get("price_pct"),
        "dist_from_52w_high": dist,
        "ma20_above_ma60": ma_ok,
        "flags": flags,
        "error": None,
    }


def _compute_with_retry(code: str, retries: int = DEFAULT_RETRIES) -> dict:
    last_exc: Optional[BaseException] = None
    for _ in range(retries + 1):
        try:
            return _compute_one(code)
        except Exception as e:  # noqa - 单只失败不能中断整批
            last_exc = e
    return {"code": code, "error": str(last_exc)}


def metrics_batch(
    codes: list[str],
    max_workers: int = DEFAULT_MAX_WORKERS,
    retries: int = DEFAULT_RETRIES,
) -> list[dict]:
    """并发批量算五列风险指标 + flags。

    单只失败重试 `retries` 次仍失败 → 输出 {"code":..., "error":...}，不中断整批。
    返回顺序与输入 `codes` 一致，与线程完成先后无关。
    """
    _warmup_js_engine()
    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_compute_with_retry, code, retries) for code in codes]
        return [f.result() for f in futures]
