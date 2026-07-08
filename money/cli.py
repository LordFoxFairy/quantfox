import json

import typer

from .config import ledger_path
from .data.news import load_news
from .data.prices import load_prices
from .data.resolve import resolve
from .evidence import build_evidence
from .indicators import compute_indicators
from .prompts import framework_version
from .storage import Ledger

app = typer.Typer(help="场外基金与黄金的量化证据卡 + Claude 决策助手", add_completion=False)


def _prices_for(asset):
    return load_prices(asset)


def _news_for(asset):
    return load_news(asset)


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
        news = _news_for(asset)
    except Exception:
        news = []
    tr = _ledger().track_record_for(asset.symbol)
    card = build_evidence(asset, prices=prices, news=news, track_record=tr)
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
def news(query: str):
    """只收集舆情原始信息（调试）。"""
    asset = resolve(query)
    typer.echo(json.dumps(_news_for(asset), ensure_ascii=False, indent=2))


@app.command("log-signal")
def log_signal(
    symbol: str,
    signal: str,
    signal_numeric: int,
    confidence: float,
    price_ref: float,
    ts: str,
    type: str = "otc_fund",
    horizons: str = "5,20,60",
    rationale: str = "",
    evidence_json: str = "{}",
):
    """把本次信号 + 当时证据存进预测账本。"""
    pid = _ledger().log_signal(
        symbol=symbol, type=type, signal=signal, signal_numeric=signal_numeric,
        confidence=confidence, horizons=[int(x) for x in horizons.split(",")],
        price_ref=price_ref, evidence_json=evidence_json, rationale=rationale,
        framework_version=framework_version(), schema_version="1.0", ts=ts,
    )
    typer.echo(json.dumps({"prediction_id": pid}))


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


if __name__ == "__main__":
    app()
