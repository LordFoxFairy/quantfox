import datetime as _dt
import json
from pathlib import Path

import typer

from .config import data_dir, ledger_path
from .data.fund_profile import load_profile
from .data.prices import load_prices
from .data.resolve import resolve
from .evidence import build_evidence
from .indicators import compute_indicators
from .metrics import compute_metrics
from .prompts import framework_version
from .storage import Ledger

app = typer.Typer(help="场外基金与黄金的量化证据卡 + Claude 决策助手", add_completion=False)


def _prices_for(asset):
    return load_prices(asset)


def _profile_for(asset):
    return load_profile(asset)


def _ledger():
    return Ledger(ledger_path())


def _empty_prices():
    import pandas as pd

    return pd.DataFrame({"date": [], "value": []})


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


@app.command()
def profile(query: str):
    """基金基本面：经理/持仓/评级（黄金不适用，调试）。"""
    asset = resolve(query)
    typer.echo(json.dumps(_profile_for(asset), ensure_ascii=False, indent=2))


@app.command("market-valuation")
def market_valuation():
    """全 A 股整体估值分位（宏观贵不贵锚，供股票/指数基金参考）。"""
    from .data.valuation import market_valuation as mv

    typer.echo(json.dumps(mv(), ensure_ascii=False, indent=2))


@app.command()
def screen(type: str = typer.Option("股票型", help="基金类型：全部/股票型/混合型/债券型/指数型/QDII/FOF"),
           top: int = typer.Option(50, help="返回前 N 名"),
           consistent: bool = typer.Option(False, "--consistent", help="只要近1年&近3年都前25%的常青基金")):
    """全市场粗筛：长周期加权+一致性打分，出 Top-N 候选（供精筛）。"""
    from .data.universe import load_universe
    from .screen import screen as run_screen

    df = load_universe(type)
    result = run_screen(df, top=top, consistent_only=consistent)
    typer.echo(json.dumps({
        "type": type, "universe_size": len(df), "returned": len(result),
        "caveats": [
            "幸存者偏差：榜单只含仍存续的基金，清盘/合并的已消失，Top 全是幸存者，历史收益天然偏高。",
            "这是按历史收益排的候选池，不是推荐；须再精筛降温（估值/回撤/集中度/追热）。",
            "过去收益≠未来收益。",
        ],
        "candidates": result,
    }, ensure_ascii=False, indent=2))


@app.command()
def report(query: str,
           analysis_file: str = typer.Option(None, help="CC 判断的 JSON（verdict/dimensions/commentary_html/risks_html）"),
           out: str = typer.Option(None, help="输出 HTML 路径")):
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
        d = data_dir() / "reports"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{asset.symbol}_{_dt.date.today().isoformat()}.html"
    path.write_text(html, encoding="utf-8")
    typer.echo(str(path))


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
    if evidence_file:
        evidence_json = Path(evidence_file).read_text(encoding="utf-8")
    pid = _ledger().log_signal(
        symbol=symbol, type=type, signal=signal, signal_numeric=signal_numeric,
        confidence=confidence, horizons=[int(x) for x in horizons.split(",")],
        price_ref=price_ref, evidence_json=evidence_json, rationale=rationale,
        framework_version=framework_version(), schema_version=SCHEMA_VERSION, ts=ts,
    )
    typer.echo(json.dumps({"prediction_id": pid}))


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
              entry_price: float = typer.Option(..., help="买入价"),
              entry_date: str = typer.Option(..., help="买入日期 YYYY-MM-DD")):
    """标记为【已买入·持有中】（可对观测中的标的转态，或直接新增持仓）。"""
    asset = resolve(symbol)
    _ledger().mark_bought(asset.symbol, asset.type, entry_price, entry_date)
    typer.echo(json.dumps({"holding": asset.symbol}, ensure_ascii=False))


@watch_app.command("list")
def watch_list():
    """列出监控清单（含状态）。"""
    typer.echo(json.dumps(_ledger().list_holdings(), ensure_ascii=False, indent=2))


@watch_app.command("remove")
def watch_remove(symbol: str):
    """从清单移除（如已卖出）。"""
    n = _ledger().remove_holding(resolve(symbol).symbol)
    typer.echo(json.dumps({"removed": n}, ensure_ascii=False))


@watch_app.command("check")
def watch_check():
    """快扫清单：观测的找买点、持有的看离场，分组输出。"""
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
    buy_now = [o["symbol"] for o in watching if o.get("status") == "可关注买点"]
    need_exit = [o["symbol"] for o in holding if o.get("status") == "需离场"]
    early_warn = [o["symbol"] for o in holding if o.get("status") == "留意"]
    typer.echo(json.dumps({
        "watching": {"n": len(watching), "buy_opportunity": buy_now, "items": watching},
        "holding": {"n": len(holding), "need_exit": need_exit, "early_warning": early_warn, "items": holding},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
