"""中国交易日历 + 场外基金 15:00 cutoff 推净值确认日。
数据源 akshare tool_trade_date_hist_sina，本地缓存 30 天；
拉取失败用旧缓存并警告；无缓存直接报错要求 --confirm-date，绝不静默猜。"""
import datetime as _dt
import json
import sys
from pathlib import Path

from .config import data_dir

CACHE_MAX_AGE_DAYS = 30
CUTOFF = _dt.time(15, 0)


def _cache_path() -> Path:
    return data_dir() / "trade_calendar.json"


def _fetch_dates() -> list:
    import akshare as ak

    df = ak.tool_trade_date_hist_sina()
    return sorted(str(x)[:10] for x in df["trade_date"])


def trade_dates(fetcher=None) -> list:
    p = _cache_path()
    cached = None
    if p.exists():
        cached = json.loads(p.read_text(encoding="utf-8"))
        age = (_dt.date.today() - _dt.date.fromisoformat(cached["fetched_at"][:10])).days
        if age <= CACHE_MAX_AGE_DAYS:
            return cached["dates"]
    try:
        dates = (fetcher or _fetch_dates)()
        p.write_text(json.dumps({"fetched_at": _dt.date.today().isoformat(), "dates": dates},
                                ensure_ascii=False), encoding="utf-8")
        return dates
    except Exception as e:  # noqa
        if cached:
            print(f"# 交易日历刷新失败，用旧缓存({cached['fetched_at']}): {e}", file=sys.stderr)
            return cached["dates"]
        raise RuntimeError("交易日历不可用且无缓存：请用 --confirm-date 手动指定净值确认日") from e


def nav_date_for_order(order_at: _dt.datetime, dates: list) -> str:
    """15:00 前 + 当天是交易日 → 按当日净值；否则顺延到下一交易日。"""
    d = order_at.date().isoformat()
    if d in dates and order_at.time() < CUTOFF:
        return d
    later = [x for x in dates if x > d]
    if not later:
        raise RuntimeError(f"交易日历不含 {d} 之后的日期：刷新日历或用 --confirm-date 手动指定")
    return later[0]
