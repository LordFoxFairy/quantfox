"""全景淘金周报渲染：五榜 + 扇形图(前瞻分布) + 战绩回看 + 事件日历。

assemble() 全依赖注入（universes/prices_fn/metrics_fn/screen_fn 均由调用方传入），
本模块自身不触网、不拉真实数据——CLI 层负责接线真实依赖。
build_gold_html() 走 screen_report.py 的静态服务端渲染（表格/文案）+ report.py 的
ECharts JSON 内联（扇形图/迷你线）双套路：表格/警示/水印可离线读、可转 PDF；
图表数据以 JSON 注入，交给客户端 ECharts 画。
"""
import concurrent.futures as cf
import datetime as _dt
import html as _html
import json
from pathlib import Path

from .data.events_cn import next_week_events
from .forecast import simulate_paths
from .gold_report import build_boards, select_pool
from .health import check_freshness, summarize_health

_ASSETS = Path(__file__).resolve().parent / "assets"
_TEMPLATE = _ASSETS / "gold_report_template.html"
_ECHARTS = _ASSETS / "echarts.min.js"
_CDN = '<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>'

_BOARD_ORDER = ["potential", "high_return", "steady", "pullback", "defensive"]
_BOARD_LABELS = {"potential": "潜力榜", "high_return": "高收益榜", "steady": "稳健榜",
                  "pullback": "回调捡漏榜", "defensive": "防守榜"}
_BOARD_NOTES = {
    "potential": "多周期一致 + 动能不过热（screen 深筛出的候选）",
    "high_return": "⚠️ 裸收益榜：追高与回撤风险自负——只按近1年收益排序，不代表可持续",
    "steady": "夏普/卡玛双指标非支配集（Pareto 前沿），风险调整后表现稳健",
    "pullback": "卡玛>0.5 且距52周高点回撤>15% 的捡漏候选，非抄底信号",
    "defensive": "债券型防守，按年化波动升序；假稳(flags)不剔除但沉底标红",
}
_FAN_TOP_N = 3
_MAX_WORKERS = 4
_RETRIES = 1
_HIST_DAYS = 250

_HEADERS = ["#", "代码", "名称", "类型", "近1年", "夏普", "卡玛", "估值分位", "距52周高", "flags", "徽标"]


def _echarts_script() -> str:
    """有本地 echarts 就内联（单文件离线可转发）；否则回退 CDN。"""
    if _ECHARTS.exists():
        return "<script>" + _ECHARTS.read_text(encoding="utf-8") + "</script>"
    return _CDN


# ---------- 取数 / 健康 ----------

def _fetch_with_retry(prices_fn, code, retries=_RETRIES):
    for _ in range(retries + 1):
        try:
            p = prices_fn(code)
            if p is not None and len(p):
                return p
        except Exception:  # noqa - 单只失败不能中断整批
            pass
    return None


def _fetch_all(codes, prices_fn, max_workers=_MAX_WORKERS):
    out = {}
    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_fetch_with_retry, prices_fn, c): c for c in codes}
        for f in cf.as_completed(futs):
            out[futs[f]] = f.result()
    return out


def _nav_now_for(code, prices_by_code, prices_fn):
    p = prices_by_code.get(code)
    if p is None:
        p = _fetch_with_retry(prices_fn, code, retries=0)
    if p is None or not len(p):
        return None
    return float(p["value"].iloc[-1])


# ---------- 图表数据 ----------

def _hist_series(prices, n=_HIST_DAYS):
    tail = prices.tail(n)
    return {"dates": list(tail["date"].astype(str)),
            "nav": [round(float(v), 4) for v in tail["value"]]}


def _fan_entry(code, name, prices, price_pct):
    cond = price_pct if (price_pct or 0) > 0.85 else None
    sim = simulate_paths(prices, _HIST_DAYS, conditional_pct=cond)
    if sim is None:
        return None
    entry = {"code": code, "name": name, "sim": sim}
    entry.update(_hist_series(prices))
    return entry


def _mini_entry(code, name, prices):
    sim = simulate_paths(prices, 60, n_paths=300)
    if sim is None:
        return None
    return {"code": code, "name": name, "p50": sim["p50"]}


# ---------- assemble ----------

def assemble(universes, prices_fn, metrics_fn, screen_fn, led, today, trade_dates_list, top=10,
             events_fn=next_week_events) -> dict:
    """五榜 + 净值取数 + 健康 + 扇形/迷你图 + 榜单存档 + 上期回看 + 事件日历。

    全依赖注入（universes/prices_fn/metrics_fn/screen_fn/led/events_fn），本函数自身不触网；
    events_fn 默认接生产实现（next_week_events），测试注入 fake 即零网络。
    """
    stock_uni = universes.get("股票型")
    screen_rows = screen_fn(stock_uni) if stock_uni is not None and len(stock_uni) else []
    pool = select_pool(universes)
    pool_metrics = metrics_fn(pool)
    boards = build_boards(universes, pool_metrics, screen_rows, top=top)

    all_codes, seen = [], set()
    for board in _BOARD_ORDER:
        for r in boards.get(board, []):
            if r["code"] not in seen:
                seen.add(r["code"])
                all_codes.append(r["code"])
    prices_by_code = _fetch_all(all_codes, prices_fn)

    health_items = [check_freshness(c, prices_by_code.get(c), trade_dates_list, today) for c in all_codes]
    health = summarize_health(health_items)

    charts, summary = {}, {}
    for board in _BOARD_ORDER:
        rows = boards.get(board, [])
        fan, mini = [], []
        for i, r in enumerate(rows):
            code = r["code"]
            prices = prices_by_code.get(code)
            if prices is None:
                continue
            if i < _FAN_TOP_N:
                e = _fan_entry(code, r.get("name"), prices, r.get("price_pct"))
                if e:
                    fan.append(e)
            else:
                e = _mini_entry(code, r.get("name"), prices)
                if e:
                    mini.append(e)
        charts[board] = {"fan": fan, "mini": mini}
        summary[board] = {"count": len(rows), "top1": rows[0].get("name") if rows else None}
        for rank, r in enumerate(rows, 1):
            prices = prices_by_code.get(r["code"])
            nav = float(prices["value"].iloc[-1]) if prices is not None and len(prices) else None
            led.add_report_issue(today, board, rank, r["code"], r.get("name"), nav)

    events = events_fn()
    if events is None:
        health["line"] = health["line"] + "（事件日历不可用）"

    review = _build_review(led, today, prices_by_code, prices_fn)

    return {
        "boards": boards, "health": health, "summary": summary, "review": review,
        "charts": charts, "events": events,
        "meta": {"today": today, "top": top, "market_valuation": None,
                 "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat()},
    }


def _build_review(led, today, prices_by_code, prices_fn):
    prev_date = led.latest_issue_date(before=today)
    if not prev_date:
        return None
    issues = led.issues_for(prev_date)
    rows, board_returns = [], {}
    for iss in issues:
        nav_at_issue = iss.get("nav_at_issue")
        nav_now = _nav_now_for(iss["symbol"], prices_by_code, prices_fn)
        pct, note = None, ""
        if nav_at_issue is None or nav_now is None or not nav_at_issue:
            note = "无法回看"
        else:
            pct = round(nav_now / nav_at_issue - 1.0, 4)
        rows.append({"board": iss["board"], "rank": iss["rank"], "code": iss["symbol"],
                     "name": iss.get("name"), "nav_at_issue": nav_at_issue, "nav_now": nav_now,
                     "pct": pct, "note": note})
        if pct is not None:
            board_returns.setdefault(iss["board"], []).append(pct)
    board_avg = {b: round(sum(v) / len(v), 4) for b, v in board_returns.items()}
    return {"issue_date": prev_date, "rows": rows, "board_avg": board_avg}


# ---------- 渲染（静态表格 Python 端拼 + 图表 JSON 交给 ECharts） ----------

def _pct(x, nd=1):
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def _num(x, nd=2):
    return "—" if x is None else f"{x:.{nd}f}"


def _row_html(i, r):
    price_pct = r.get("price_pct")
    hi_val = price_pct is not None and price_pct > 0.85
    flags = r.get("flags") or []
    flags_html = ('<span class="flag">' + _html.escape("、".join(flags)) + "</span>") if flags else "—"
    badge = '<span class="badge">名实待核</span>' if r.get("name_theme_mismatch") else ""
    return (
        f'<tr>'
        f'<td>{i}</td>'
        f'<td class="l">{_html.escape(str(r.get("code", "")))}</td>'
        f'<td class="l">{_html.escape(str(r.get("name", "") or ""))}</td>'
        f'<td class="l">{_html.escape(str(r.get("fund_type", "") or ""))}</td>'
        f'<td>{_pct(r.get("r_1y"))}</td>'
        f'<td>{_num(r.get("sharpe"))}</td>'
        f'<td>{_num(r.get("calmar"))}</td>'
        f'<td class="{"hi" if hi_val else ""}">{_pct(price_pct) if price_pct is not None else "—"}</td>'
        f'<td>{_pct(r.get("dist_from_52w_high"))}</td>'
        f'<td>{flags_html}</td>'
        f'<td>{badge}</td></tr>'
    )


def _board_section_html(board, rows, charts_for_board):
    label = _BOARD_LABELS[board]
    note = _BOARD_NOTES[board]
    banner = f'<div class="banner {"warn" if board == "high_return" else ""}">{_html.escape(note)}</div>'
    head = "".join(f"<th{' class=l' if h in ('代码', '名称', '类型') else ''}>{h}</th>" for h in _HEADERS)
    body = "".join(_row_html(i, r) for i, r in enumerate(rows, 1)) or '<tr><td colspan="11">（暂无上榜）</td></tr>'
    fan_n = len(charts_for_board.get("fan", []))
    mini_n = len(charts_for_board.get("mini", []))
    fan_divs = "".join(f'<div class="chart sm" id="fan-{board}-{i}"></div>' for i in range(fan_n))
    mini_divs = "".join(f'<div class="chart mini" id="mini-{board}-{i}"></div>' for i in range(mini_n))
    charts_html = ""
    if fan_n:
        charts_html += f'<div class="chartgrid">{fan_divs}</div>'
    if mini_n:
        charts_html += f'<div class="minigrid">{mini_divs}</div>'
    return (
        f'<section class="board"><h2>{_html.escape(label)}</h2>{banner}'
        f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'
        f'{charts_html}</section>'
    )


def _summary_html(summary):
    parts = []
    for board in _BOARD_ORDER:
        s = summary.get(board) or {}
        top1 = s.get("top1") or "—"
        parts.append(f"{_BOARD_LABELS[board]} {s.get('count', 0)} 只（榜首：{_html.escape(str(top1))}）")
    return "金矿摘要：" + " · ".join(parts)


def _regime_html(mv):
    mv = mv or {}
    if not mv.get("available"):
        return "大盘估值：暂不可用"
    return (f'大盘估值：全A近10年 {mv.get("percentile_10y", 0) * 100:.0f}% 分位'
            f'（{_html.escape(str(mv.get("level", "")))}）')


def _events_html(events):
    """事件不可用（None）→ 整节省略，只靠 health line 注明——绝不渲染编造/占位内容。"""
    if events is None:
        return ""
    if not events:
        return '<div class="bar">下周事件日历：无重大事件</div>'
    items = "、".join(f'{e.get("date", "")} {_html.escape(str(e.get("event", "")))}' for e in events)
    return f'<div class="bar">{"下周事件日历：" + items}</div>'


def _review_html(review):
    if review is None:
        return '<section class="review"><h2>上期回看</h2><p class="muted">首期报告，暂无上期可回看。</p></section>'
    rows_html = []
    for r in review["rows"]:
        pct = r["pct"]
        cls = "" if pct is None else ("pos" if pct >= 0 else "neg")
        cell = _pct(pct) if pct is not None else (r.get("note") or "无法回看")
        rows_html.append(
            f'<tr><td class="l">{_html.escape(_BOARD_LABELS.get(r["board"], r["board"]))}</td>'
            f'<td>{r["rank"]}</td><td class="l">{_html.escape(str(r["code"]))}</td>'
            f'<td class="l">{_html.escape(str(r.get("name") or ""))}</td>'
            f'<td>{_num(r.get("nav_at_issue"), 4)}</td><td>{_num(r.get("nav_now"), 4)}</td>'
            f'<td class="{cls}">{cell}</td></tr>')
    avg_html = " · ".join(f"{_BOARD_LABELS.get(b, b)} 均 {_pct(v)}" for b, v in review["board_avg"].items()) or "—"
    return (
        f'<section class="review"><h2>上期回看（{_html.escape(review["issue_date"])} 上榜，落到今日）</h2>'
        f'<div class="bar">按榜平均：{avg_html}</div>'
        f'<table><thead><tr><th class="l">榜单</th><th>名次</th><th class="l">代码</th><th class="l">名称</th>'
        f'<th>上期净值</th><th>当前净值</th><th>涨跌</th></tr></thead>'
        f'<tbody>{"".join(rows_html) or "<tr><td colspan=7>（无记录）</td></tr>"}</tbody></table></section>'
    )


def _holdings_html(payload):
    """Task 7 才产出 holdings；本任务 payload 通常不含该键——直接省略整节。"""
    holdings = payload.get("holdings")
    if not holdings:
        return ""
    rows = "".join(
        f'<tr><td class="l">{_html.escape(str(h.get("code", "")))}</td>'
        f'<td class="l">{_html.escape(str(h.get("name", "") or ""))}</td>'
        f'<td>{_num(h.get("pnl_pct"), 2)}</td></tr>' for h in holdings)
    return (f'<section class="holdings"><h2>我的持仓</h2>'
            f'<table><thead><tr><th class="l">代码</th><th class="l">名称</th><th>浮盈亏</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></section>')


def build_gold_html(payload: dict) -> str:
    boards = payload.get("boards") or {}
    charts = payload.get("charts") or {}
    health = payload.get("health") or {}
    summary = payload.get("summary") or {}
    meta = payload.get("meta") or {}

    sections = "".join(
        _board_section_html(b, boards.get(b, []), charts.get(b, {})) for b in _BOARD_ORDER
    )
    header = (
        f'<div class="bar">{_regime_html(meta.get("market_valuation"))}</div>'
        f'<div class="bar">{_html.escape(health.get("line", ""))}</div>'
        f'<div class="bar">{_html.escape(_summary_html(summary))}</div>'
        f'{_events_html(payload.get("events"))}'
        f'<div class="disclaimer">深筛/回看均基于公开历史数据统计，<b>非投资建议</b>；'
        f'幸存者偏差：榜单只含仍存续的基金，已退市/清盘的产品不会出现在这里；'
        f'过去收益≠未来收益，前瞻分布是历史统计推演，非预测承诺；决策与风险自负。</div>'
    )

    tpl = _TEMPLATE.read_text(encoding="utf-8")
    return (
        tpl.replace("__ECHARTS_SCRIPT__", _echarts_script())
        .replace("__TITLE__", f'quantfox 全景淘金周报 · {_html.escape(str(meta.get("today", "")))}')
        .replace("__HEADER__", header)
        .replace("__BOARDS__", sections)
        .replace("__HOLDINGS__", _holdings_html(payload))
        .replace("__REVIEW__", _review_html(payload.get("review")))
        .replace("__GOLD_JSON__", json.dumps({"charts": charts, "boards": {
            b: [{"code": r["code"]} for r in boards.get(b, [])] for b in _BOARD_ORDER}},
            ensure_ascii=False).replace("</", "<\\/"))  # 防基金名等含 </script> 提前闭合脚本标签
    )
