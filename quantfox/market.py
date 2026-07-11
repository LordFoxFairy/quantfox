"""A 股市场层：指数估值分位 + 动量 + 市场宽度 + 行业轮动 → 一句话市场判断（regime_line）。

`build_market_view` 全部逻辑吃注入的 fetchers（零网络、可测）；生产 fetchers 见
`default_fetchers()`，CLI 用它接线真实 akshare 接口。任一子块取数失败/数据不足
→ 该块弃权并记入 health，不拿假数据填充（DataHealth-lite，框架 v15 铁律）。
"""
import datetime as _dt

from .health import health_item, summarize_health

# 指数清单：语义固定，生产接线时按所选 akshare 接口的代码格式各自适配（见 default_fetchers）。
INDICES = [
    ("000300", "沪深300"),
    ("000905", "中证500"),
    ("399006", "创业板指"),
    ("000688", "科创50"),
    ("000922", "中证红利"),
]

PE_MIN_POINTS = 1000  # 近10年分位；<1000点视为序列过短，该指数估值弃权
PE_WINDOW_POINTS = 2500  # 近10年 ≈ 2500 个交易日；超长历史序列须先截窗再算分位
MOM_SHORT = 20
MOM_LONG = 60


def _pe_percentile(pe_values):
    """近10年分位：先截尾部 PE_WINDOW_POINTS 窗口再 (pe <= latest).mean()；
    序列 < PE_MIN_POINTS 视为过短，弃权返回 None（唯一的过短守卫，调用方不再重复判）。"""
    if pe_values is None or len(pe_values) < PE_MIN_POINTS:
        return None
    window = pe_values.tail(PE_WINDOW_POINTS)
    latest = window.iloc[-1]
    return float((window <= latest).mean())


def _tail_return(values, n):
    if values is None or len(values) <= n:
        return None
    return float(values.iloc[-1] / values.iloc[-1 - n] - 1)


def _index_block(code, name, fetchers, health_items):
    entry = {"code": code, "name": name, "pe_percentile_10y": None,
             "r_20": None, "r_60": None, "ma20_gt_ma60": None}
    hist_ok = pe_ok = False

    try:
        hist = fetchers["index_hist"](code)
    except Exception as e:  # noqa
        hist = None
        health_items.append(health_item(name, "failed", note=f"日线不可用：{e}"))
    if hist is not None and len(hist) > 0:
        hist_ok = True
        values = hist["value"]
        entry["r_20"] = _tail_return(values, MOM_SHORT)
        entry["r_60"] = _tail_return(values, MOM_LONG)
        if len(values) >= MOM_LONG:
            ma20 = values.tail(MOM_SHORT).mean()
            ma60 = values.tail(MOM_LONG).mean()
            entry["ma20_gt_ma60"] = bool(ma20 > ma60)
    elif hist is not None:
        health_items.append(health_item(name, "failed", note="日线为空"))

    try:
        pe_df = fetchers["index_pe"](code)
    except Exception as e:  # noqa
        pe_df = None
        health_items.append(health_item(name, "failed", note=f"估值弃权：PE不可用（{e}）"))
    if pe_df is not None:
        entry["pe_percentile_10y"] = _pe_percentile(pe_df["value"])
        if entry["pe_percentile_10y"] is None:
            health_items.append(health_item(
                name, "failed", note=f"估值弃权：PE序列仅{len(pe_df)}点（<{PE_MIN_POINTS}）"))
        else:
            pe_ok = True

    if hist_ok and pe_ok:  # 双块全成功才记 ok；部分失败只留失败明细，不假绿
        health_items.append(health_item(name, "ok", as_of=str(hist["date"].iloc[-1])[:10]))
    return entry


def _breadth_block(fetchers, health_items):
    try:
        breadth = fetchers["breadth"]()
    except Exception:  # noqa
        breadth = None
    if breadth is None:
        health_items.append(health_item("breadth", "failed", note="宽度不可用"))
    else:
        health_items.append(health_item("breadth", "ok"))
    return breadth


def _sector_block(fetchers, health_items):
    try:
        sectors = fetchers["sector_momentum"]()
    except Exception:  # noqa
        sectors = None
    if not sectors:
        health_items.append(health_item("sectors", "failed", note="行业轮动不可用"))
        return {"top": [], "bottom": []}
    health_items.append(health_item("sectors", "ok"))
    ranked_desc = sorted(sectors, key=lambda s: s.get("r_1m") if s.get("r_1m") is not None else float("-inf"),
                          reverse=True)
    ranked_asc = sorted(sectors, key=lambda s: s.get("r_1m") if s.get("r_1m") is not None else float("inf"))
    return {"top": ranked_desc[:5], "bottom": ranked_asc[:5]}


def _valuation_label(indices):
    valid = [e["pe_percentile_10y"] for e in indices if e["pe_percentile_10y"] is not None]
    if not valid:
        return "估值不可用"
    avg = sum(valid) / len(valid)
    if avg > 0.7:
        return "整体估值偏贵"
    if avg < 0.4:
        return "整体估值偏便宜"
    return "整体估值中位"


def _momentum_label(indices):
    """多数判定只在"动量可用"的指数里做——取数失败(None)是弃权不是看空。"""
    available = [e for e in indices if e["ma20_gt_ma60"] is not None]
    if not available:
        return "动量不可用"
    up = sum(1 for e in available if e["ma20_gt_ma60"])
    return "趋势偏多" if up > len(available) / 2 else "趋势偏弱"


def build_market_view(fetchers: dict) -> dict:
    health_items = []
    indices = [_index_block(code, name, fetchers, health_items) for code, name in INDICES]
    breadth = _breadth_block(fetchers, health_items)
    sectors = _sector_block(fetchers, health_items)

    segments = [_valuation_label(indices), _momentum_label(indices)]
    if sectors["top"]:
        names = "/".join(s.get("name") or s.get("code") or "?" for s in sectors["top"][:2])
        segments.append(f"热点：{names}")
    regime_line = " · ".join(segments)

    return {
        "indices": indices,
        "breadth": breadth,
        "sectors": sectors,
        "health": summarize_health(health_items),
        "regime_line": regime_line,
    }


# ---- 生产 fetchers（真实 akshare 接线，CLI 专用；实测记录见 .superpowers/sdd/p3a-task-4-report.md）----

# stock_index_pe_lg（乐咕乐股）仅覆盖固定 12 个指数名，实测 INDICES 里只有这两个命中；
# 其余三只（创业板指/科创50/中证红利）该接口无对应序列，估值块按设计弃权。
_PE_SYMBOL_MAP = {"000300": "沪深300", "000905": "中证500"}

# stock_zh_index_daily（新浪）symbol 前缀：399 开头深证系用 sz，其余沪证系用 sh。
_SINA_PREFIX = {"000300": "sh", "000905": "sh", "399006": "sz", "000688": "sh", "000922": "sh"}

# 实测 sh000922（中证红利）新浪日线已断更（最新仅到 2019-01-30）；超过此天数视为源已死，
# 弃权而不是拿陈旧数据冒充"动量"。
_STALE_DAYS = 15


def _default_index_hist(code):
    import akshare as ak
    import pandas as pd

    prefix = _SINA_PREFIX.get(code)
    if prefix is None:
        raise RuntimeError("接口不可用：无该指数的日线代码映射")
    try:
        df = ak.stock_zh_index_daily(symbol=f"{prefix}{code}")
    except Exception as e:
        raise RuntimeError("接口不可用") from e
    if df is None or len(df) == 0:
        raise RuntimeError("接口不可用：日线为空")
    raw_last = df["date"].iloc[-1]
    if hasattr(raw_last, "isoformat") and not hasattr(raw_last, "date"):
        last_date = raw_last  # datetime.date
    else:
        try:  # fail closed：日期解析不了就不假装新鲜
            last_date = pd.to_datetime(str(raw_last)).date()
        except Exception as e:
            raise RuntimeError("接口不可用：无法判定数据新鲜度") from e
    if (_dt.date.today() - last_date).days > _STALE_DAYS:
        raise RuntimeError(f"接口不可用：数据源已断更（最新 {last_date}）")
    return pd.DataFrame({"date": df["date"].astype(str), "value": df["close"].astype(float)})


def _default_index_pe(code):
    import akshare as ak
    import pandas as pd

    name = _PE_SYMBOL_MAP.get(code)
    if name is None:
        raise RuntimeError("接口不可用：该指数无 legulegu PE 序列")
    try:
        df = ak.stock_index_pe_lg(symbol=name)
    except Exception as e:
        raise RuntimeError("接口不可用") from e
    return pd.DataFrame({"date": df["日期"].astype(str), "value": df["滚动市盈率"].astype(float)})


def _default_breadth():
    """站上 MA60 比例：真实计算需给全市场每只股票取日线各自算 MA60（约5000次请求），
    单次 CLI 调用成本过高；且 stock_zh_a_spot_em 本环境实测常 RemoteDisconnected
    （docs/HANDOFF-2026-07-10.md §4）。宁弃权不拿假数据充数。"""
    raise RuntimeError("接口不可用：全市场 MA60 宽度计算成本过高，暂弃权")


def _default_sector_momentum():
    import contextlib
    import io

    import akshare as ak

    try:
        names_df = ak.stock_board_industry_name_ths()
    except Exception as e:
        raise RuntimeError("接口不可用") from e
    end = _dt.date.today()
    start = end - _dt.timedelta(days=150)
    out = []
    # ak.stock_board_industry_index_ths 每次调用内部起一个 tqdm 进度条（leave=False）；
    # 全行业板块循环下来能刷屏近百条，且 akshare 的 get_tqdm() 不认 TQDM_DISABLE 环境变量
    # （实测：tqdm/akshare 源码均未读取该变量）。静默 stderr 是唯一简单可行的办法，
    # 不影响真正的异常传播（异常走 raise，不走 stderr 打印）。
    with contextlib.redirect_stderr(io.StringIO()):
        for _, row in names_df.iterrows():
            code, name = row.get("code"), row.get("name")
            if not name:
                continue
            try:
                hist = ak.stock_board_industry_index_ths(
                    symbol=name, start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"))
            except Exception:  # noqa - 单个板块限流/失败不阻断其余板块
                continue
            close = hist["收盘价"]
            if len(close) < 22:
                continue
            r_1m = float(close.iloc[-1] / close.iloc[-22] - 1)
            r_3m = float(close.iloc[-1] / close.iloc[-64] - 1) if len(close) >= 64 else None
            out.append({"code": code, "name": name, "r_1m": r_1m, "r_3m": r_3m})
    if not out:
        raise RuntimeError("接口不可用：全部行业板块取数失败")
    return out


def default_fetchers() -> dict:
    """生产 fetchers：CLI `quantfox market` 用它接线真实 akshare 接口。"""
    return {
        "index_hist": _default_index_hist,
        "index_pe": _default_index_pe,
        "breadth": _default_breadth,
        "sector_momentum": _default_sector_momentum,
    }
