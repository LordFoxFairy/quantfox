"""DataHealth-lite：数据健康如实呈现。存在 failed/stale 时 healthy=False，
任何摘要/报告头部必须显示明细行——禁止"一切正常"式假绿（框架 v15 铁律）。"""


def health_item(symbol, status, as_of=None, note=""):
    return {"symbol": symbol, "status": status, "as_of": as_of, "note": note}


def check_freshness(symbol, prices, trade_dates_list, today):
    """最新净值日 < 最近一个交易日(≤today) 即 stale。

    trade_dates_list 须为升序 ISO 日期（calendar_cn.trade_dates 已保证）。
    """
    if prices is None or len(prices) == 0:
        return health_item(symbol, "failed", note="无净值数据")
    last_nav = str(prices["date"].iloc[-1])[:10]
    past = [d for d in trade_dates_list if d <= today]
    if not past:
        return health_item(symbol, "stale", as_of=last_nav, note="日历不含今日前交易日，无法判定新鲜度")
    latest_trade = past[-1]
    if last_nav < latest_trade:
        return health_item(symbol, "stale", as_of=last_nav, note=f"最近交易日 {latest_trade} 净值未出")
    return health_item(symbol, "ok", as_of=last_nav)


def summarize_health(items):
    ok = [x for x in items if x["status"] == "ok"]
    stale = [x for x in items if x["status"] == "stale"]
    failed = [x for x in items if x["status"] == "failed"]
    healthy = not stale and not failed
    if healthy:
        line = f"数据健康：全部 {len(ok)} 只数据新鲜"
    else:
        parts = [f"{len(ok)} 只新鲜"]
        if stale:
            parts.append(f"{len(stale)} 只 stale（用旧净值，已列明）")
        if failed:
            parts.append(f"{len(failed)} 只失败")
        line = "数据健康：" + "、".join(parts)
    return {"ok": len(ok), "stale": len(stale), "failed": len(failed),
            "healthy": healthy, "detail": stale + failed, "line": line}
