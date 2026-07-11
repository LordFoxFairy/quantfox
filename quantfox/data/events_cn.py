"""下周宏观事件（尽力而为）：多源依序尝试，当日缓存；全源失败一律返回 None——绝不编数据。

次源探测记录：曾用真实网络探测 akshare 中可能的第二宏观日历接口。
ak.macro_info_ws（华尔街见闻-日历-宏观，按单日 date 查询）实测可用——
逐日拉取 [today, today+7] 共 8 天拼出与主源等价的 date+event 列表，故予以接入。
"""
import datetime as _dt
import json
from pathlib import Path


def _source_baidu():
    """主源：百度经济数据日历（ak.news_economic_baidu）。"""
    import akshare as ak
    import pandas as pd

    df = ak.news_economic_baidu()
    col_date = "日期" if "日期" in df.columns else df.columns[0]
    col_name = "事件" if "事件" in df.columns else df.columns[1]
    today = _dt.date.today()
    end = today + _dt.timedelta(days=7)
    out = []
    for _, r in df.iterrows():
        d = pd.to_datetime(r[col_date]).date()
        if today <= d <= end:
            out.append({"date": d.isoformat(), "event": str(r[col_name])})
    return out or None


def _source_secondary():
    """次源：华尔街见闻宏观日历（ak.macro_info_ws），逐日探测拼出下周窗口。"""
    import akshare as ak
    import pandas as pd

    today = _dt.date.today()
    end = today + _dt.timedelta(days=7)
    out = []
    seen = set()
    for i in range(8):
        d = today + _dt.timedelta(days=i)
        df = ak.macro_info_ws(date=d.strftime("%Y%m%d"))
        if df is None or df.empty:
            continue
        col_time = "时间" if "时间" in df.columns else df.columns[0]
        col_name = "事件" if "事件" in df.columns else df.columns[1]
        for _, r in df.iterrows():
            ev_date = pd.to_datetime(r[col_time]).date()
            if today <= ev_date <= end:
                key = (ev_date.isoformat(), str(r[col_name]))
                if key not in seen:
                    seen.add(key)
                    out.append({"date": ev_date.isoformat(), "event": str(r[col_name])})
    return out or None


def next_week_events(sources=None, cache_path=None, today=None):
    """依序尝试多源，首个成功非空即用；当日缓存命中直接返回、不触网；全源失败返回 None。

    - sources: list[callable]，各自返回 list 或 None，允许抛异常（视为该源失败，尝试下一个）。
      默认 [_source_baidu, _source_secondary]。
    - cache_path: 缓存文件路径，默认 data_dir()/events_cache.json。
    - today: 注入的当日日期字符串（ISO），默认 date.today().isoformat()。
    """
    from ..config import data_dir

    if sources is None:
        sources = [_source_baidu, _source_secondary]
    if today is None:
        today = _dt.date.today().isoformat()
    cache_path = Path(cache_path) if cache_path is not None else data_dir() / "events_cache.json"

    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("date") == today:
                return cached.get("events")
        except Exception:  # noqa - 缓存损坏当作未命中，继续走源
            pass

    for source in sources:
        try:
            events = source()
        except Exception:  # noqa - 单源异常按失败处理，尝试下一源
            events = None
        if events:
            cache_path.write_text(
                json.dumps({"date": today, "events": events}, ensure_ascii=False),
                encoding="utf-8",
            )
            return events

    return None
