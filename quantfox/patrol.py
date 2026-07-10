"""持仓巡检：每天跑一遍 watch 清单，客观信号去重后追加进 alerts 表，
只在"有新增信号"时组一封邮件（无新增只打印摘要，不打扰）。

全部依赖注入（led/resolve_fn/prices_fn/trade_dates_list 皆由调用方传入），本模块
自身不触网、不读时钟——CLI 层负责接线真实依赖（resolve/_prices_for/calendar_cn.trade_dates/
date.today()）。

告警状态机（六个 kind，全部走同一套"状态变了才追加"去重）：
  data_failure      取价异常 triggered；本次取价成功 clear
  exit_signal       check_holding status=="需离场" triggered；不再是则 clear
  early_warning     check_holding status=="留意" triggered（--intraday 模式复用同一 kind，
                     state 换成 f"intraday-{today}-{up|down}" 以按日按方向去重）
  valuation_high    price_pct > 0.85 triggered；回落则 clear
  pending_confirm   存在净值超 2 个交易日未出的 pending lot triggered；无则 clear
  reconcile_mismatch  latest_reconciliation verdict=="mismatch" triggered；否则 clear

首次出现且 state=="clear" 不落库（不报"从未发生过的恢复"）。
"""
from .forecast import simulate_paths
from .health import check_freshness, health_item, summarize_health
from .monitor import check_holding
from .percentile import price_percentile

VALUATION_HIGH_PATROL = 0.85
PENDING_CONFIRM_GRACE_DAYS = 2
CONE_HORIZON_DAYS = 5
CONE_DOWN_THRESHOLD = -0.01
FUND_INTRADAY_THRESHOLD = 0.02
GOLD_INTRADAY_THRESHOLD = 0.015

KIND_LABELS = {
    "data_failure": "取价失败",
    "exit_signal": "需离场",
    "early_warning": "留意/盘中异动",
    "valuation_high": "估值高位",
    "pending_confirm": "净值迟迟未出",
    "reconcile_mismatch": "对账不符",
}


def _emit(led, new_alerts, symbol, kind, state, message=""):
    """状态较上次记录变了才落库 + 计入本轮新增；首次出现且 state=='clear' 不记。"""
    prev = led.latest_alert(symbol, kind)
    if prev is None and state == "clear":
        return
    if prev is not None and prev["state"] == state:
        return
    led.add_alert(symbol, kind, state, message)
    new_alerts.append({"symbol": symbol, "kind": kind, "state": state, "message": message})


def _fill_pending_lots(led, symbol, prices, trade_dates_list, today, filled):
    """确认日净值已出的 pending lot 自动补记进 filled；仍未出且已过确认日 >=2 个交易日的
    返回 True（触发 pending_confirm）。"""
    dates = prices["date"].astype(str).str[:10]
    triggered = False
    for lot in led.pending_lots(symbol):
        hit = prices[dates == lot["confirm_date"]]
        if len(hit):
            shares = led.fill_lot(lot["id"], float(hit["value"].iloc[-1]))
            filled.append({"symbol": symbol, "lot_id": lot["id"],
                           "confirm_date": lot["confirm_date"], "shares": shares})
            continue
        elapsed = len([d for d in trade_dates_list if lot["confirm_date"] < d <= today])
        if elapsed >= PENDING_CONFIRM_GRACE_DAYS:
            triggered = True
    return triggered


def _build_email(health, new_alerts, expect, cone_notes):
    lines = [health["line"], "", f"【新增信号】共 {len(new_alerts)} 条"]
    for a in new_alerts:
        label = KIND_LABELS.get(a["kind"], a["kind"])
        msg = f"（{a['message']}）" if a.get("message") else ""
        lines.append(f"· {a['symbol']} {label}：{a['state']}{msg}")
    if expect:
        lines.append("")
        lines.append("【当日预期】")
        for e in expect:
            lines.append(f"· {e['symbol']}：预期当日 {e['expected_daily_pnl']:+.2f} 元，"
                         f"累计 {e['expected_total_pnl']:+.2f} 元")
    if cone_notes:
        lines.append("")
        lines.append("【周度波动锥提示】")
        for c in cone_notes:
            lines.append(f"· {c['note']}")
    lines.append("")
    lines.append("—— 非投资建议；买卖请自行在支付宝手动操作，决策与风险自负。")
    return "\n".join(lines)


def run_patrol(led, resolve_fn, prices_fn, trade_dates_list, today, weekly_cone=False) -> dict:
    """跑一遍 led.list_holdings()：取价 → 健康度 → pending lot 自动补记 → 各 kind 去重告警 →
    holding 的落 daily_expectation 对账 → weekly_cone 时附周度波动锥提示。
    返回 {new_alerts, health, expect, filled, cone_notes, email_body}；无新增信号 email_body 为 None。
    """
    new_alerts, health_items, expect, filled, cone_notes = [], [], [], [], []

    for h in led.list_holdings():
        symbol, status = h["symbol"], h["status"]
        try:
            asset = resolve_fn(symbol)
            prices = prices_fn(asset)
        except Exception as e:  # noqa - 单只失败不能挡住整批
            health_items.append(health_item(symbol, "failed", note=str(e)))
            _emit(led, new_alerts, symbol, "data_failure", "triggered", str(e))
            continue
        _emit(led, new_alerts, symbol, "data_failure", "clear", "取价恢复正常")
        health_items.append(check_freshness(symbol, prices, trade_dates_list, today))

        pending_triggered = _fill_pending_lots(led, symbol, prices, trade_dates_list, today, filled)
        _emit(led, new_alerts, symbol, "pending_confirm",
              "triggered" if pending_triggered else "clear",
              "存在净值超 2 个交易日未出的分笔" if pending_triggered else "")

        pct = price_percentile(prices, 3).get("price_pct")
        val_triggered = pct is not None and pct > VALUATION_HIGH_PATROL
        _emit(led, new_alerts, symbol, "valuation_high",
              "triggered" if val_triggered else "clear",
              f"估值分位 {pct * 100:.0f}%，超过 85% 高位线" if val_triggered else "")

        if status == "holding" and h.get("entry_price") is not None:
            chk = check_holding(prices, h["entry_price"], h["entry_date"], h.get("type", "otc_fund"))
            exit_triggered = chk["status"] == "需离场"
            _emit(led, new_alerts, symbol, "exit_signal",
                  "triggered" if exit_triggered else "clear",
                  "、".join(chk["exit_flags"]) if exit_triggered else "不再需离场")
            warn_triggered = chk["status"] == "留意"
            _emit(led, new_alerts, symbol, "early_warning",
                  "triggered" if warn_triggered else "clear",
                  "、".join(chk["early_warnings"]) if warn_triggered else "不再留意")

        rec = led.latest_reconciliation(symbol)
        mismatch = bool(rec) and rec.get("verdict") == "mismatch"
        _emit(led, new_alerts, symbol, "reconcile_mismatch",
              "triggered" if mismatch else "clear",
              f"对账差额 {rec['delta']}" if mismatch else "")

        if status == "holding":
            exp = led.daily_expectation(symbol, prices)
            if exp is not None:
                led.add_reconciliation(symbol=symbol, trade_date=exp["trade_date"],
                                       expected_daily_pnl=exp["expected_daily_pnl"],
                                       expected_total_pnl=exp["expected_total_pnl"], verdict="pending")
                expect.append(exp)

            if weekly_cone:
                cond = pct if val_triggered else None
                cone = simulate_paths(prices, CONE_HORIZON_DAYS, conditional_pct=cond)
                if cone and cone.get("p50") and cone["p50"][-1] < CONE_DOWN_THRESHOLD:
                    cone_notes.append({
                        "symbol": symbol, "p50_5d": cone["p50"][-1],
                        "note": f"{symbol} 未来5日中位路径 {cone['p50'][-1] * 100:.1f}%，短期或承压",
                    })

    health = summarize_health(health_items)
    email_body = _build_email(health, new_alerts, expect, cone_notes) if new_alerts else None
    return {"new_alerts": new_alerts, "health": health, "expect": expect,
            "filled": filled, "cone_notes": cone_notes, "email_body": email_body}


def run_intraday_patrol(led, holdings, estimate_fn, today) -> dict:
    """盘中异动预警：holdings 为 [{symbol,type}]（通常只巡 status=='holding' 的）；
    estimate_fn(symbol, asset_type) -> float|None，涨跌幅（小数，非百分比，取不到给 None）。
    超阈值(基金 2%/黄金 1.5%)走 early_warning kind 同一套去重，state 按"日期+方向"编码，
    同日同方向第二次自动沉默；盘中不落 reconciliations。"""
    new_alerts = []
    for h in holdings:
        symbol, atype = h["symbol"], h.get("type", "otc_fund")
        try:
            chg = estimate_fn(symbol, atype)
        except Exception:  # noqa - 单只失败不能挡住整批
            continue
        if chg is None:
            continue
        threshold = GOLD_INTRADAY_THRESHOLD if atype == "gold" else FUND_INTRADAY_THRESHOLD
        if abs(chg) <= threshold:
            continue
        state = f"intraday-{today}-{'up' if chg > 0 else 'down'}"
        _emit(led, new_alerts, symbol, "early_warning", state,
              f"盘中估算 {chg * 100:+.2f}%，超阈值 {threshold * 100:.1f}%")
    return {"new_alerts": new_alerts}
