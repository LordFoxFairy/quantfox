import datetime as _dt
import json
from pathlib import Path

import typer

from .config import data_dir, ledger_path, reports_dir
from .data.fund_profile import load_profile
from .data.prices import load_prices
from .data.resolve import resolve
from .evidence import build_evidence
from .indicators import compute_indicators
from .metrics import compute_metrics
from .prompts import framework_version
from .storage import Ledger

app = typer.Typer(help="场外基金与黄金的量化证据卡 + Claude 决策助手", add_completion=False)

SIGNAL_NUMERIC = {"强买": 2, "买": 1, "观望": 0, "减": -1, "回避": -2}


def _prices_for(asset):
    return load_prices(asset)


def _profile_for(asset):
    return load_profile(asset)


def _ledger():
    return Ledger(ledger_path())


def _empty_prices():
    import pandas as pd

    return pd.DataFrame({"date": [], "value": []})


def _parse_horizons(raw: str) -> list[int]:
    try:
        values = [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError as e:
        raise typer.BadParameter("horizons 必须是逗号分隔的正整数") from e
    if not values or any(x <= 0 for x in values):
        raise typer.BadParameter("horizons 必须至少包含一个正整数")
    return values


def _validate_signal(signal: str, signal_numeric: int):
    expected = SIGNAL_NUMERIC.get(signal)
    if expected is None:
        raise typer.BadParameter(f"signal 必须是 {list(SIGNAL_NUMERIC)}")
    if signal_numeric != expected:
        raise typer.BadParameter(f"signal_numeric 与 signal 不一致：{signal} 应为 {expected}")


def _validate_evidence_snapshot(evidence_json: str, symbol: str):
    try:
        evidence = json.loads(evidence_json)
    except json.JSONDecodeError as e:
        raise typer.BadParameter("evidence_json 必须是合法 JSON") from e
    if not isinstance(evidence, dict) or not evidence:
        raise typer.BadParameter("evidence_json/evidence_file 必须提供证据卡快照")
    if not evidence.get("schema_version"):
        raise typer.BadParameter("evidence 快照缺少 schema_version")
    asset = evidence.get("asset") or {}
    if asset.get("symbol") and str(asset.get("symbol")) != str(symbol):
        raise typer.BadParameter("evidence 快照的 asset.symbol 与 --symbol 不一致")
    price = evidence.get("price") or {}
    if price.get("latest") is None or not price.get("latest_date"):
        raise typer.BadParameter("evidence 快照缺少 price.latest/latest_date")


@app.command()
def evidence(query: str, format: str = typer.Option("json", help="json|markdown")):
    """产出完整证据卡（Skill 主命令）。"""
    asset = resolve(query)
    try:
        prices = _prices_for(asset)
    except Exception as e:  # noqa
        prices = _empty_prices()
        typer.echo(f"# 取价失败: {e}", err=True)
    try:
        profile = _profile_for(asset)
    except Exception:
        profile = {"applicable": asset.type == "otc_fund"}
    tr = _ledger().track_record_for(asset.symbol)
    card = build_evidence(asset, prices=prices, profile=profile, track_record=tr)
    typer.echo(card.to_markdown() if format == "markdown" else card.to_json())


@app.command()
def fetch(query: str):
    """只取原始净值/价格（调试）。"""
    asset = resolve(query)
    typer.echo(_prices_for(asset).tail(10).to_string())


@app.command()
def indicators(query: str):
    """只算技术指标（调试）。"""
    asset = resolve(query)
    typer.echo(json.dumps(compute_indicators(_prices_for(asset)), ensure_ascii=False, indent=2))


@app.command()
def metrics(query: str):
    """只算风险绩效指标（夏普/索提诺/卡玛/VaR 等，调试）。"""
    asset = resolve(query)
    typer.echo(json.dumps(compute_metrics(_prices_for(asset)), ensure_ascii=False, indent=2))


@app.command("metrics-batch")
def metrics_batch_cmd(
    codes: list[str] = typer.Argument(..., help="6 位基金代码，空格分隔，支持多只"),
    max_workers: int = typer.Option(4, help="并发线程数（akshare 限流保守，默认4）"),
    retries: int = typer.Option(1, help="单只失败重试次数"),
):
    """C1：批量算风险指标（夏普/卡玛/最大回撤/年化波动/估值分位），只拉净值不拉 profile/持仓/评级，
    并发+重试+失败标记，用于 fund-screener 对 top-N 候选做快速初筛。同时附 C2 假稳 flags。"""
    from .metrics_batch import metrics_batch as run_metrics_batch

    typer.echo(json.dumps(
        run_metrics_batch(codes, max_workers=max_workers, retries=retries),
        ensure_ascii=False, indent=2,
    ))


@app.command()
def profile(query: str):
    """基金基本面：经理/持仓/评级（黄金不适用，调试）。"""
    asset = resolve(query)
    typer.echo(json.dumps(_profile_for(asset), ensure_ascii=False, indent=2))


@app.command()
def forecast(query: str,
             short: int = typer.Option(None, "--short", help="短期波动锥：未来 N 个交易日逐日区间（N≤10）")):
    """前瞻收益分布（非点预测）；--short N 给逐日波动锥（区间不是方向）。"""
    from .forecast import forecast as run_fc
    from .forecast import simulate_paths
    from .percentile import price_percentile

    asset = resolve(query)
    prices = _prices_for(asset)
    if short is not None:
        if not 1 <= short <= 10:
            raise typer.BadParameter("--short 取 1..10 个交易日")
        pct = price_percentile(prices, 3).get("price_pct")
        cond = pct if pct is not None and pct > 0.85 else None
        cone = simulate_paths(prices, short, conditional_pct=cond)
        typer.echo(json.dumps({"symbol": asset.symbol, "current_valuation_pct": pct,
                               "cone": cone,
                               "note": "逐日区间（p10-p90），不是方向预测；历史统计推演，非预测承诺"},
                              ensure_ascii=False, indent=2))
        return
    typer.echo(json.dumps(run_fc(prices), ensure_ascii=False, indent=2))


@app.command("next-confirm")
def next_confirm(at: str = typer.Option(None, "--at", help='下单时刻 "YYYY-MM-DD HH:MM"，缺省=现在')):
    """现在（或指定时刻）下单，按 15:00 cutoff + 交易日历推场外基金净值确认日。"""
    from .calendar_cn import nav_date_for_order, trade_dates

    order_at = _dt.datetime.strptime(at, "%Y-%m-%d %H:%M") if at else _dt.datetime.now()
    try:
        nav_date = nav_date_for_order(order_at, trade_dates())
    except RuntimeError as e:
        raise typer.BadParameter(str(e)) from e
    typer.echo(json.dumps({"order_at": order_at.strftime("%Y-%m-%d %H:%M"), "nav_date": nav_date,
                           "note": "15:00 前按当日净值确认，之后顺延下一交易日（场外基金）"},
                          ensure_ascii=False))


@app.command("market-valuation")
def market_valuation():
    """全 A 股整体估值分位（宏观贵不贵锚，供股票/指数基金参考）。"""
    from .data.valuation import market_valuation as mv

    typer.echo(json.dumps(mv(), ensure_ascii=False, indent=2))


def _intraday_estimate(asset):
    """取一只标的的盘中估算（黄金用实时价；基金用官方盘中估算，降级到自算前十大重仓）。
    被 `intraday` 命令与 `patrol --intraday` 共用。"""
    from .intraday import estimate_fund_intraday, gold_intraday

    if asset.type == "gold":
        try:
            import akshare as ak

            return gold_intraday(ak.spot_quotations_sge(symbol=asset.symbol))
        except Exception as e:  # noqa
            return {"available": False, "error": str(e), "note": "盘中黄金行情暂不可用"}

    from .intraday import official_fund_estimate

    out = {"available": False}
    try:  # 主源：数据商官方盘中估算（全持仓，最准）
        import akshare as ak

        out = official_fund_estimate(ak.fund_value_estimation_em(symbol="全部"), asset.symbol)
    except Exception:  # noqa
        out = {"available": False}
    if not out.get("available"):  # 降级：自算前十大重仓
        top = (_profile_for(asset).get("holdings") or {}).get("top", [])
        try:
            from .intraday import _default_stock_quotes

            quotes = _default_stock_quotes([h["code"] for h in top if h.get("code")])
        except Exception:  # noqa
            quotes = {}
        out = estimate_fund_intraday(top, quotes)
    return out


@app.command()
def intraday(query: str):
    """盘中异动预警（非盯盘）：黄金用实时价；基金用前十大重仓实时估算今日大致涨跌。"""
    asset = resolve(query)
    typer.echo(json.dumps(_intraday_estimate(asset), ensure_ascii=False, indent=2))


@app.command()
def screen(type: str = typer.Option("股票型", help="基金类型：全部/股票型/混合型/债券型/指数型/QDII/FOF"),
           top: int = typer.Option(30, help="返回前 N 名（已去重、按主题分散）"),
           style: str = typer.Option("balanced", help="风格：balanced/steady/momentum/pullback"),
           per_theme: int = typer.Option(2, help="每个主题最多几只（强制分散）"),
           exclude_overheated: bool = typer.Option(False, "--exclude-overheated", help="直接剔除过热(山顶)的")):
    """全市场多因子深筛：赢家+动能不过热+回调不追高+A/C去重+主题限流。供精筛。"""
    from .data.universe import load_universe
    from .screen import screen as run_screen

    df = load_universe(type)
    result = run_screen(df, top=top, style=style, per_theme=per_theme, exclude_overheated=exclude_overheated)
    themes = {}
    for r in result:
        themes[r.get("theme")] = themes.get(r.get("theme"), 0) + 1
    typer.echo(json.dumps({
        "type": type, "style": style, "universe_size": len(df), "returned": len(result),
        "theme_spread": themes,
        "caveats": [
            "已做：赢家(1/2/3年靠前) + 动能不过热(剔抛物线) + 回调不追高 + A/C去重 + 每主题≤%d只。" % per_theme,
            "overheated=true 的是站在山顶/超买的，别追；这仍是候选池不是推荐。",
            "须再精筛：逐只 evidence 看估值分位/RSI/回撤/持仓 + WebSearch 舆情。幸存者偏差仍在，过去≠未来。",
        ],
        "candidates": result,
    }, ensure_ascii=False, indent=2))


@app.command("screen-report")
def screen_report(type: str = typer.Option("股票型", help="基金类型"),
                  style: str = typer.Option("balanced", help="balanced/steady/momentum/pullback"),
                  top: int = typer.Option(50, help="前 N 名（k≈50 初筛）"),
                  per_theme: int = typer.Option(3, help="每主题最多几只"),
                  exclude_overheated: bool = typer.Option(False, "--exclude-overheated"),
                  out: str = typer.Option(None, help="输出 HTML 路径"),
                  pdf: bool = typer.Option(True, "--pdf/--no-pdf", help="导出 PDF（默认开，邮箱能看）")):
    """全市场深筛 → 初筛报告（含大盘估值+主题分布+Top-k表，HTML+PDF 可邮件）。"""
    from .data.universe import load_universe
    from .screen import screen as run_screen
    from .screen_report import build_screen_report

    df = load_universe(type)
    cands = run_screen(df, top=top, style=style, per_theme=per_theme, exclude_overheated=exclude_overheated)
    themes = {}
    for c in cands:
        themes[c.get("theme")] = themes.get(c.get("theme"), 0) + 1
    mv = {}
    try:
        from .data.valuation import market_valuation as _mv
        mv = _mv()
    except Exception:  # noqa
        mv = {}
    meta = {"title": f"全市场深筛报告 · {type}",
            "subtitle": f"风格 {style} · 全市场 {len(df)} 只 · Top {len(cands)}（已去重、按主题分散）",
            "theme_spread": themes, "market_valuation": mv, "generated_at": _dt.date.today().isoformat()}
    html = build_screen_report(cands, meta)
    if out:
        path = Path(out)
    else:
        path = reports_dir() / f"screen_{type}_{_dt.date.today().isoformat()}.html"
    path.write_text(html, encoding="utf-8")
    result = {"html": str(path), "count": len(cands)}
    if pdf:
        from .report import html_to_pdf

        pdf_path = path.with_suffix(".pdf")
        html_to_pdf(path, pdf_path)
        result["pdf"] = str(pdf_path)  # 邮件附这个
    typer.echo(json.dumps(result, ensure_ascii=False))


@app.command("gold-report")
def gold_report_cmd(
    top: int = typer.Option(10, help="每榜 Top N"),
    email: bool = typer.Option(False, "--email", help="生成后用已配置邮箱发送 PDF"),
    out: str = typer.Option(None, help="输出目录（默认 data_dir/reports/gold）"),
):
    """全景淘金周报：五榜（潜力/高收益/稳健/回调捡漏/防守）+ 前瞻分布扇形图 + 上期回看 + 事件日历。
    自包含 HTML + PDF；--email 直接发送 PDF 附件。"""
    from .calendar_cn import trade_dates
    from .data.universe import load_universe
    from .data.valuation import market_valuation as run_market_valuation
    from .gold_report_render import assemble, build_gold_html
    from .metrics_batch import metrics_batch as run_metrics_batch
    from .report import html_to_pdf
    from .screen import screen as run_screen

    types = ["股票型", "混合型", "债券型", "指数型", "QDII"]
    universes = {t: load_universe(t) for t in types}

    def screen_fn(df):
        return run_screen(df, top=max(top, 30))

    def metrics_fn(codes):
        return run_metrics_batch(codes)

    def prices_fn(code):
        return load_prices(resolve(code))

    led = _ledger()

    def holdings_fn():
        from .forecast import simulate_paths
        from .percentile import price_percentile

        rows = []
        for h in led.list_holdings():
            if h["status"] != "holding":
                continue
            symbol = h["symbol"]
            try:
                prices = prices_fn(symbol)
                latest_nav = float(prices["value"].iloc[-1])
            except Exception:  # noqa - 单只取价失败不阻断整节
                rows.append({"code": symbol, "name": f"{symbol}（取价失败）", "pnl_pct": None,
                            "last_reconcile_verdict": None, "cone_p50_5d": None})
                continue
            pos = led.position(symbol, latest_nav=latest_nav)
            pnl_pct = pos.get("pnl_pct") if pos else None
            rec = led.latest_reconciliation(symbol)
            verdict = rec.get("verdict") if rec else None
            price_pct = price_percentile(prices, 3).get("price_pct")
            cond = price_pct if (price_pct or 0) > 0.85 else None
            cone = simulate_paths(prices, 5, conditional_pct=cond)
            rows.append({"code": symbol, "name": symbol, "pnl_pct": pnl_pct,
                        "last_reconcile_verdict": verdict,
                        "cone_p50_5d": cone.get("p50") if cone else None})
        return rows

    today = _dt.date.today().isoformat()
    try:
        dates = trade_dates()
    except Exception as e:  # noqa - 日历不可用不阻断周报，健康检查会保守判定
        typer.echo(f"# 交易日历不可用，健康检查将保守判定: {e}", err=True)
        dates = [today]

    payload = assemble(universes, prices_fn, metrics_fn, screen_fn, led, today, dates, top=top,
                       holdings_fn=holdings_fn)
    try:
        payload["meta"]["market_valuation"] = run_market_valuation()
    except Exception:  # noqa - 大盘估值仅头部展示，取数失败不阻断周报
        payload["meta"]["market_valuation"] = {"available": False, "note": "取数失败"}

    html = build_gold_html(payload)
    out_dir = Path(out) if out else (data_dir() / "reports" / "gold")
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"gold_{today}.html"
    pdf_path = out_dir / f"gold_{today}.pdf"
    html_path.write_text(html, encoding="utf-8")
    html_to_pdf(html_path, pdf_path)

    result = {"html": str(html_path), "pdf": str(pdf_path), "top": top, "health": payload["health"]["line"]}
    if email:
        from .notify import notify_send

        mm_dd = _dt.date.today().strftime("%m-%d")
        result["emailed"] = notify_send(
            subject=f"[quantfox周报] {mm_dd} 五类Top10 + 预测曲线", attach=str(pdf_path))
    typer.echo(json.dumps(result, ensure_ascii=False))


@app.command()
def report(query: str,
           analysis_file: str = typer.Option(None, help="CC 判断的 JSON（verdict/dimensions/commentary_html/risks_html）"),
           out: str = typer.Option(None, help="输出 HTML 路径"),
           pdf: bool = typer.Option(False, "--pdf", help="同时导出 PDF（邮件/QQ 邮箱能看，静态图不依赖 JS）")):
    """渲染自包含可视化 HTML 报告（ECharts K线+指标+回撤+持仓）。打印文件路径。"""
    from .report import build_report

    analysis = {}
    if analysis_file:
        analysis = json.loads(Path(analysis_file).read_text(encoding="utf-8"))
    html = build_report(query, analysis)
    asset = resolve(query)
    if out:
        path = Path(out)
    else:
        path = reports_dir() / f"{asset.symbol}_{_dt.date.today().isoformat()}.html"
    path.write_text(html, encoding="utf-8")
    result = {"html": str(path)}
    if pdf:
        from .report import html_to_pdf

        pdf_path = path.with_suffix(".pdf")
        html_to_pdf(path, pdf_path)
        result["pdf"] = str(pdf_path)  # 邮件附这个，QQ 邮箱能看
    typer.echo(json.dumps(result, ensure_ascii=False))


@app.command("log-signal")
def log_signal(
    symbol: str = typer.Option(..., help="标的代码，如 501018 或 Au99.99"),
    signal: str = typer.Option(..., help="信号档位：强买/买/观望/减/回避"),
    signal_numeric: int = typer.Option(..., help="信号数值：2/1/0/-1/-2"),
    confidence: float = typer.Option(..., help="置信度 0-1"),
    price_ref: float = typer.Option(..., help="证据卡最新价"),
    ts: str = typer.Option(..., help="预测日期 YYYY-MM-DD"),
    type: str = typer.Option("otc_fund", help="otc_fund 或 gold"),
    horizons: str = typer.Option("20,60,120,250", help="评估周期（交易日）；基金中长期，默认 1月/3月/半年/1年"),
    rationale: str = typer.Option("", help="一句话理由"),
    evidence_json: str = typer.Option("{}", help="证据卡 JSON 快照（内联）"),
    evidence_file: str = typer.Option(None, help="证据卡 JSON 文件路径（优先，用于冻结当时证据）"),
):
    """把本次信号 + 当时证据快照存进预测账本。"""
    from .evidence import SCHEMA_VERSION

    if not 0.0 <= confidence <= 1.0:
        raise typer.BadParameter(f"confidence 必须是 0-1（不是 0-100）；收到 {confidence}")
    _validate_signal(signal, signal_numeric)
    if evidence_file:
        evidence_json = Path(evidence_file).read_text(encoding="utf-8")
    _validate_evidence_snapshot(evidence_json, symbol)
    parsed_horizons = _parse_horizons(horizons)
    pid = _ledger().log_signal(
        symbol=symbol, type=type, signal=signal, signal_numeric=signal_numeric,
        confidence=confidence, horizons=parsed_horizons,
        price_ref=price_ref, evidence_json=evidence_json, rationale=rationale,
        framework_version=framework_version(), schema_version=SCHEMA_VERSION, ts=ts,
    )
    typer.echo(json.dumps({"prediction_id": pid}))


mandate_app = typer.Typer(help="个人投资档案（个性化决策地基）：本金/目标/风险上限")
app.add_typer(mandate_app, name="mandate")


@mandate_app.command("set")
def mandate_set(total_wealth: float = typer.Option(None, help="全部可计量财富（元）"),
                deployable: float = typer.Option(None, help="本次可投入资金（元）"),
                cash_reserve: float = typer.Option(None, help="现金底线（元）"),
                target_date: str = typer.Option(None, help="目标日期 YYYY-MM-DD"),
                target_return: float = typer.Option(None, help="目标净收益，小数（8% 填 0.08）"),
                max_loss: float = typer.Option(None, help="最大可亏金额（元）"),
                max_single_weight: float = typer.Option(None, help="单标的上限，占可投比例 (0,1]"),
                max_theme_weight: float = typer.Option(None, help="单主题上限，占可投比例 (0,1]"),
                exclude: str = typer.Option(None, help="排除标的，逗号分隔代码"),
                notes: str = typer.Option("", help="备注")):
    """写入/更新档案（覆盖式，旧档案自动备份 .bak）。字段全可选，缺什么少个性化什么。"""
    from .mandate import SCHEMA_VERSION, derived, save_mandate

    m = {"schema_version": SCHEMA_VERSION, "mandate_as_of": _dt.date.today().isoformat(),
         "currency": "CNY", "total_wealth": total_wealth, "deployable_capital": deployable,
         "minimum_cash_reserve": cash_reserve, "target_date": target_date,
         "target_net_return": target_return, "maximum_loss_amount": max_loss,
         "maximum_single_instrument_weight": max_single_weight,
         "maximum_theme_weight": max_theme_weight,
         "excluded_instruments": [x.strip() for x in exclude.split(",") if x.strip()] if exclude else [],
         "notes": notes}
    m = {k: v for k, v in m.items() if v not in (None, [], "")}
    m["schema_version"] = SCHEMA_VERSION
    try:
        p = save_mandate(m)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    typer.echo(json.dumps({"saved": str(p), "mandate": m, "derived": derived(m)},
                          ensure_ascii=False, indent=2))


@mandate_app.command("show")
def mandate_show():
    """显示档案 + 派生量（单标的金额上限等）。无档案时提示如何建立。"""
    from .mandate import derived, load_mandate, mandate_path

    m = load_mandate()
    if m is None:
        typer.echo(json.dumps({"configured": False, "path": str(mandate_path()),
                               "note": "尚无档案：quantfox mandate set --deployable 60000 --max-single-weight 0.2 ..."},
                              ensure_ascii=False))
        return
    typer.echo(json.dumps({"configured": True, "mandate": m, "derived": derived(m)},
                          ensure_ascii=False, indent=2))


email_app = typer.Typer(help="邮件推送（配置你自己的邮箱后，可把报告/提醒发给任意邮箱）")
app.add_typer(email_app, name="email")


@email_app.command("config")
def email_config(smtp_host: str = typer.Option(..., help="如 smtp.gmail.com / smtp.163.com"),
                 smtp_port: int = typer.Option(465, help="SSL 常用 465"),
                 username: str = typer.Option(..., help="你的邮箱账号"),
                 password: str = typer.Option(..., help="授权码/应用专用密码（不是登录密码）"),
                 from_addr: str = typer.Option(..., help="发件邮箱"),
                 to: str = typer.Option(None, help="默认收件邮箱（提醒/报告发给谁；不填则默认发给自己）"),
                 use_ssl: bool = typer.Option(True, help="SSL(465) 用 True；STARTTLS(587) 用 False")):
    """配置你自己的发件邮箱（存本地、不进仓库、权限600）。"""
    from .notify import save_email_config

    p = save_email_config({"smtp_host": smtp_host, "smtp_port": smtp_port, "username": username,
                           "password": password, "from_addr": from_addr,
                           "notify_to": to or from_addr, "use_ssl": use_ssl})
    typer.echo(json.dumps({"saved": str(p), "notify_to": to or from_addr,
                           "note": "密码仅存本地，未打印"}, ensure_ascii=False))


@email_app.command("show")
def email_show():
    """查看当前邮箱配置（密码脱敏），方便管理。"""
    from .notify import email_config_path, load_email_config

    cfg = load_email_config()
    if not cfg:
        typer.echo(json.dumps({"configured": False, "path": str(email_config_path()),
                               "note": "尚未配置，先运行 quantfox email config ..."}, ensure_ascii=False))
        return
    masked = {**cfg, "password": "******"}
    typer.echo(json.dumps({"configured": True, "path": str(email_config_path()), "config": masked},
                          ensure_ascii=False, indent=2))


@email_app.command("send")
def email_send(to: str = typer.Option(None, help="收件邮箱（不填=用配置里的默认收件人）"),
               subject: str = typer.Option(..., help="标题"),
               body: str = typer.Option(None, help="正文（或用 --body-file）"),
               body_file: str = typer.Option(None, help="正文文件"),
               attach: str = typer.Option(None, help="附件路径（如报告 PDF）"),
               html: bool = typer.Option(False, help="正文按 HTML 发送")):
    """发送邮件（收件人默认用配置里的 notify_to，绝不从别处猜）。"""
    from .notify import send_email

    text = Path(body_file).read_text(encoding="utf-8") if body_file else (body or "")
    typer.echo(json.dumps(send_email(to, subject, text, attach=attach, html=html or bool(body_file)),
                          ensure_ascii=False))


@email_app.command("test")
def email_test(to: str = typer.Option(None, help="收件邮箱（不填=默认收件人）")):
    """发一封测试邮件，验证配置。"""
    from .notify import send_email

    typer.echo(json.dumps(send_email(to, "quantfox 测试邮件", "配置成功，可以收到 quantfox 的提醒了。"),
                          ensure_ascii=False))


@app.command()
def backtest(query: str,
             rule: str = typer.Option("valuation", help="机械规则：valuation/trend/combo"),
             horizon: int = typer.Option(20, help="持有期（交易日）")):
    """历史回测（机械规则基线，非 LLM）：point-in-time、扣成本、对比基率与买入持有。"""
    from .backtest import backtest as run_bt

    asset = resolve(query)
    prices = _prices_for(asset)
    typer.echo(json.dumps(run_bt(prices, rule=rule, horizon=horizon, asset_type=asset.type),
                          ensure_ascii=False, indent=2))


@app.command()
def outcomes(query: str, prediction_id: int):
    """为某条历史预测按真实价格算收益。"""
    asset = resolve(query)
    res = _ledger().compute_outcomes(prediction_id, _prices_for(asset))
    typer.echo(json.dumps(res, ensure_ascii=False, indent=2))


@app.command()
def review(
    query: str = typer.Argument(None),
    all: bool = typer.Option(False, "--all"),
    since: str = typer.Option(None, "--since"),
):
    """查看战绩（单标的或全局）。"""
    led = _ledger()
    if all or query is None:
        typer.echo(json.dumps(led.review(since_version=since), ensure_ascii=False, indent=2))
    else:
        asset = resolve(query)
        typer.echo(json.dumps(led.review(symbol=asset.symbol, since_version=since), ensure_ascii=False, indent=2))


@app.command()
def calibration(query: str = typer.Argument(None), all: bool = typer.Option(False, "--all")):
    """信心校准表：按当时信心分桶看真实命中率（说 80% 把握时是否真 80% 对）。"""
    led = _ledger()
    symbol = None if (all or query is None) else resolve(query).symbol
    typer.echo(json.dumps(led.calibration(symbol=symbol), ensure_ascii=False, indent=2))


watch_app = typer.Typer(help="监控清单（opt-in）：观测找买点 / 持有看离场，两态")
app.add_typer(watch_app, name="watch")


@watch_app.command("add")
def watch_add(symbol: str,
              target_price: float = typer.Option(None, help="目标买入价（到价提醒）"),
              note: str = typer.Option("", help="备注")):
    """把一只标的加入【观测中】（还没买，等买点）。"""
    asset = resolve(symbol)
    _ledger().add_watching(asset.symbol, asset.type, target_price, note)
    typer.echo(json.dumps({"watching": asset.symbol}, ensure_ascii=False))


@watch_app.command("buy")
def watch_buy(symbol: str,
              amount: float = typer.Option(None, help="买入金额（元）——按金额记一笔"),
              nav: float = typer.Option(None, help="确认净值（已知就直接给，跳过自动推算）"),
              entry_price: float = typer.Option(None, help="已知加权成本净值时用（单笔/直填成本）"),
              entry_date: str = typer.Option(None, help="下单日期 YYYY-MM-DD，默认今天"),
              order_time: str = typer.Option(None, help="下单时间 HH:MM（判断 15:00 cutoff；默认当前时间）"),
              confirm_date: str = typer.Option(None, help="手动指定净值确认日（日历不可用时兜底）")):
    """记一笔买入：--amount 自动按 15:00 cutoff 推确认日取净值；净值未出记 pending 待补。"""
    asset = resolve(symbol)
    entry_date = entry_date or _dt.date.today().isoformat()
    led = _ledger()
    if amount is not None:
        if nav is not None:  # 用户直接报 App 确认净值（最可信，优先），确认日仍按 cutoff+日历推
            if confirm_date is None:
                from .calendar_cn import nav_date_for_order, trade_dates

                t = _dt.time.fromisoformat(order_time) if order_time else _dt.datetime.now().time()
                try:
                    confirm_date = nav_date_for_order(
                        _dt.datetime.combine(_dt.date.fromisoformat(entry_date), t), trade_dates())
                except RuntimeError as e:
                    raise typer.BadParameter(f"{e}（--nav 已给，但确认日推算失败：请补 --confirm-date）") from e
            shares = led.add_lot(asset.symbol, asset.type, amount, nav, entry_date,
                                 confirm_date=confirm_date)
            typer.echo(json.dumps({"holding": asset.symbol,
                                   "lot": {"amount": amount, "nav": nav, "shares": shares,
                                           "confirm_date": confirm_date},
                                   "position": led.position(asset.symbol)}, ensure_ascii=False))
            return
        if confirm_date is None:  # 自动推净值确认日（15:00 cutoff + 交易日历）
            from .calendar_cn import nav_date_for_order, trade_dates

            t = _dt.time.fromisoformat(order_time) if order_time else _dt.datetime.now().time()
            try:
                confirm_date = nav_date_for_order(
                    _dt.datetime.combine(_dt.date.fromisoformat(entry_date), t), trade_dates())
            except RuntimeError as e:
                raise typer.BadParameter(str(e)) from e
        found = None
        try:
            prices = _prices_for(asset)
            hit = prices[prices["date"].astype(str).str[:10] == confirm_date]
            if len(hit):
                found = float(hit["value"].iloc[-1])
        except Exception as e:  # noqa
            typer.echo(f"# 取价失败: {e}", err=True)
        if found is not None:
            shares = led.add_lot(asset.symbol, asset.type, amount, found, entry_date,
                                 confirm_date=confirm_date)
            typer.echo(json.dumps({"holding": asset.symbol,
                                   "lot": {"amount": amount, "nav": found, "shares": shares,
                                           "confirm_date": confirm_date},
                                   "position": led.position(asset.symbol)}, ensure_ascii=False))
        else:
            led.add_lot(asset.symbol, asset.type, amount, None, entry_date, confirm_date=confirm_date)
            typer.echo(json.dumps({"holding": asset.symbol, "pending": True,
                                   "confirm_date": confirm_date,
                                   "note": f"确认日 {confirm_date} 净值未公布；出值后跑 "
                                           f"quantfox watch confirm {asset.symbol} 自动补记"},
                                  ensure_ascii=False))
    elif entry_price is not None:
        led.mark_bought(asset.symbol, asset.type, entry_price, entry_date)
        typer.echo(json.dumps({"holding": asset.symbol, "entry_price": entry_price,
                               "entry_date": entry_date}, ensure_ascii=False))
    else:
        raise typer.BadParameter("给 --amount（自动推确认日/净值，或配 --nav 直填），或 --entry-price")


@watch_app.command("confirm")
def watch_confirm(symbol: str):
    """补记 pending lots：确认日净值公布后自动回填份额与成本。"""
    asset = resolve(symbol)
    led = _ledger()
    pend = led.pending_lots(asset.symbol)
    if not pend:
        typer.echo(json.dumps({"symbol": asset.symbol, "filled": [], "note": "无 pending 笔"},
                              ensure_ascii=False))
        return
    prices = _prices_for(asset)
    dates = prices["date"].astype(str).str[:10]
    filled, still = [], []
    for lot in pend:
        hit = prices[dates == lot["confirm_date"]]
        if len(hit):
            shares = led.fill_lot(lot["id"], float(hit["value"].iloc[-1]))
            filled.append({"id": lot["id"], "confirm_date": lot["confirm_date"], "shares": shares})
        else:
            still.append({"id": lot["id"], "confirm_date": lot["confirm_date"], "note": "净值仍未出"})
    typer.echo(json.dumps({"symbol": asset.symbol, "filled": filled, "pending": still,
                           "position": led.position(asset.symbol)}, ensure_ascii=False, indent=2))


@watch_app.command("expect")
def watch_expect(symbol: str = typer.Argument(None)):
    """当日预期收益（落库留痕）：按最新净值与已确认份额算预期，写入 reconciliations。"""
    led = _ledger()
    if symbol:
        symbols = [resolve(symbol).symbol]
    else:
        symbols = [h["symbol"] for h in led.list_holdings() if h["status"] == "holding"]
    if not symbols:
        typer.echo(json.dumps({"note": "无持仓分笔，先 quantfox watch buy 记账"}, ensure_ascii=False))
        return
    out = []
    for sym in symbols:
        try:
            prices = _prices_for(resolve(sym))
        except Exception as e:  # noqa
            out.append({"symbol": sym, "error": f"取价失败: {e}"})
            continue
        exp = led.daily_expectation(sym, prices)
        if exp is None:
            out.append({"symbol": sym, "note": "无已确认分笔或净值不足两天，算不了预期"})
            continue
        led.add_reconciliation(symbol=sym, trade_date=exp["trade_date"],
                               expected_daily_pnl=exp["expected_daily_pnl"],
                               expected_total_pnl=exp["expected_total_pnl"], verdict="pending")
        out.append({**exp, "note": "已落库；拿到 App 实际数后跑 watch reconcile 比对"})
    typer.echo(json.dumps(out, ensure_ascii=False, indent=2))


@watch_app.command("reconcile")
def watch_reconcile(symbol: str,
                    app_profit: float = typer.Option(..., "--app-profit", help="App 显示的当日收益（元，亏为负）"),
                    date: str = typer.Option(None, help="净值日 YYYY-MM-DD，默认最新")):
    """与 App 对账：比对预期与实际当日收益，判定 ok/rounding/mismatch 并落库。"""
    from .storage import classify_delta

    asset = resolve(symbol)
    led = _ledger()
    prices = _prices_for(asset)
    exp = led.daily_expectation(asset.symbol, prices)
    if exp is None:
        typer.echo(json.dumps({"symbol": asset.symbol, "error": "无已确认分笔或净值不足，先记账"},
                              ensure_ascii=False))
        raise typer.Exit(1)
    if date and date != exp["trade_date"]:
        rows = [r for r in led.reconciliations_for(asset.symbol, trade_date=date)
                if r["expected_daily_pnl"] is not None]
        if not rows:
            typer.echo(json.dumps({"symbol": asset.symbol, "error": f"{date} 无预期记录，只能对最新净值日 {exp['trade_date']}"},
                                  ensure_ascii=False))
            raise typer.Exit(1)
        exp = {"symbol": asset.symbol, "trade_date": date,
               "expected_daily_pnl": rows[-1]["expected_daily_pnl"],
               "expected_total_pnl": rows[-1]["expected_total_pnl"]}
    delta = round(app_profit - exp["expected_daily_pnl"], 2)
    verdict = classify_delta(delta)
    note = "" if verdict == "ok" else (
        "四舍五入级差异，可接受" if verdict == "rounding"
        else "对不上：排查确认日(T/T+1)、份额、费率口径；把 App 成本净值报给我重新对齐")
    led.add_reconciliation(symbol=asset.symbol, trade_date=exp["trade_date"],
                           expected_daily_pnl=exp["expected_daily_pnl"], app_daily_pnl=app_profit,
                           delta=delta, expected_total_pnl=exp.get("expected_total_pnl"),
                           verdict=verdict, note=note)
    typer.echo(json.dumps({"symbol": asset.symbol, "trade_date": exp["trade_date"],
                           "expected": exp["expected_daily_pnl"], "app": app_profit,
                           "delta": delta, "verdict": verdict, "note": note},
                          ensure_ascii=False, indent=2))


@watch_app.command("position")
def watch_position(symbol: str):
    """查看某只持仓：分笔明细 + 加权成本 + 现值 + 浮盈亏。"""
    asset = resolve(symbol)
    led = _ledger()
    pos = led.position(asset.symbol)
    if pos is None:
        typer.echo(json.dumps({"symbol": asset.symbol, "note": "无分笔记录（用 watch buy --amount --nav 记账）"},
                              ensure_ascii=False))
        return
    try:
        latest = float(_prices_for(asset)["value"].iloc[-1])
        pos = led.position(asset.symbol, latest_nav=latest)
    except Exception:  # noqa
        pass
    rec = led.latest_reconciliation(asset.symbol)
    if rec:
        pos["last_reconcile"] = {"trade_date": rec["trade_date"], "verdict": rec["verdict"],
                                 "delta": rec["delta"]}
    typer.echo(json.dumps(pos, ensure_ascii=False, indent=2))


@watch_app.command("list")
def watch_list():
    """列出监控清单（含状态）。"""
    typer.echo(json.dumps(_ledger().list_holdings(), ensure_ascii=False, indent=2))


@watch_app.command("remove")
def watch_remove(symbol: str):
    """从清单移除（如已卖出）。"""
    n = _ledger().remove_holding(resolve(symbol).symbol)
    typer.echo(json.dumps({"removed": n}, ensure_ascii=False))


def _gather_watch():
    from .monitor import check_candidate, check_holding

    led = _ledger()
    watching, holding = [], []
    for h in led.list_holdings():
        asset = resolve(h["symbol"])
        try:
            prices = _prices_for(asset)
            if h["status"] == "holding":
                r = check_holding(prices, h["entry_price"], h["entry_date"], asset.type)
            else:
                r = check_candidate(prices, h.get("target_price"), asset.type)
        except Exception as e:  # noqa
            r = {"status": "取价失败", "error": str(e)}
        (holding if h["status"] == "holding" else watching).append({"symbol": h["symbol"], **r})
    return watching, holding


@watch_app.command("check")
def watch_check():
    """快扫清单：观测的找买点、持有的看离场，分组输出。"""
    watching, holding = _gather_watch()
    typer.echo(json.dumps({
        "watching": {"n": len(watching),
                     "buy_opportunity": [o["symbol"] for o in watching if o.get("status") == "可关注买点"],
                     "items": watching},
        "holding": {"n": len(holding),
                    "need_exit": [o["symbol"] for o in holding if o.get("status") == "需离场"],
                    "early_warning": [o["symbol"] for o in holding if o.get("status") == "留意"],
                    "items": holding},
    }, ensure_ascii=False, indent=2))


@watch_app.command("digest")
def watch_digest():
    """生成一封巡检摘要文本（报平安也生成）——供定时邮件用。"""
    from .monitor import format_digest

    watching, holding = _gather_watch()
    typer.echo(format_digest(watching, holding))


schedule_app = typer.Typer(help="本地定时（macOS launchd）：周报/巡检自动跑")
app.add_typer(schedule_app, name="schedule")


@schedule_app.command("install")
def schedule_install(intraday: bool = typer.Option(False, "--intraday", help="加装盘中 14:30 巡检")):
    """安装 launchd 定时：周五21:30 周报 + 工作日21:35 巡检。Mac 睡眠会错过，唤醒后补跑。"""
    from .schedule_mac import install

    try:
        paths = install(intraday=intraday)
    except RuntimeError as e:
        raise typer.BadParameter(str(e)) from e
    typer.echo(json.dumps({"installed": [str(p) for p in paths]}, ensure_ascii=False, indent=2))


@schedule_app.command("uninstall")
def schedule_uninstall():
    """卸载全部 quantfox 定时任务。"""
    from .schedule_mac import uninstall

    typer.echo(json.dumps({"removed": [str(p) for p in uninstall()]}, ensure_ascii=False))


@schedule_app.command("status")
def schedule_status():
    """查看定时任务安装/加载状态与最近日志行。"""
    from .schedule_mac import status

    typer.echo(json.dumps(status(), ensure_ascii=False, indent=2))


def _patrol_intraday_pct(symbol, asset_type):
    """把 _intraday_estimate 的取数结果统一成一个"涨跌幅（小数）"给 patrol.run_intraday_patrol 用。"""
    out = _intraday_estimate(resolve(symbol))
    if not out.get("available"):
        return None
    if asset_type == "gold":
        pct = out.get("intraday_change_pct")
    else:
        pct = out.get("est_change_pct")
        if pct is None:
            pct = out.get("est_full_if_representative_pct")
        if pct is None:
            pct = out.get("est_from_top_holdings_pct")
    return None if pct is None else pct / 100.0


@app.command()
def patrol(email: bool = typer.Option(False, "--email", help="有新增信号才发邮件"),
           intraday: bool = typer.Option(False, "--intraday", help="盘中异动预警，非日常全量巡检"),
           llm: bool = typer.Option(False, "--llm", help="预留：LLM 深分析（P3 未实现）")):
    """持仓巡检：对 watch 清单每只算客观信号，去重后追加进 alerts；有新增才发邮件。
    周五自动附周度波动锥提示；--intraday 走盘中异动预警（更粗阈值、不落对账）；
    --llm 是 P3 预留参数位，当前未实现。"""
    if llm:
        typer.echo(json.dumps({"error": "llm 深分析未实现，预留参数位（P3）"}, ensure_ascii=False))
        return

    from .patrol import run_intraday_patrol, run_patrol

    led = _ledger()
    today_d = _dt.date.today()
    today = today_d.isoformat()

    if intraday:
        holdings = [h for h in led.list_holdings() if h["status"] == "holding"]
        result = run_intraday_patrol(led, holdings, _patrol_intraday_pct, today)
        if email and result["new_alerts"]:
            from .notify import notify_send

            mm_dd = today_d.strftime("%m-%d")
            body = "\n".join(f"· {a['symbol']}：{a['message']}" for a in result["new_alerts"])
            notify_send(f"[quantfox盘中] {mm_dd} {len(result['new_alerts'])}条异动", body)
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return

    from .calendar_cn import trade_dates

    try:
        dates = trade_dates()
    except Exception as e:  # noqa - 日历不可用不阻断巡检，健康检查会保守判定
        typer.echo(f"# 交易日历不可用，健康检查将保守判定: {e}", err=True)
        dates = [today]

    result = run_patrol(led, resolve, _prices_for, dates, today, weekly_cone=today_d.weekday() == 4)
    if email and result["email_body"] is not None:
        from .notify import notify_send

        mm_dd = today_d.strftime("%m-%d")
        notify_send(f"[quantfox巡检] {mm_dd} {len(result['new_alerts'])}条新信号", result["email_body"])
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
