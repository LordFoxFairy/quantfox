import json

import pandas as pd
from typer.testing import CliRunner

import quantfox.calendar_cn as cal
import quantfox.cli as cli
from quantfox.data.resolve import resolve
from quantfox.patrol import run_intraday_patrol, run_patrol
from quantfox.storage import Ledger

runner = CliRunner()


def _prices(vals, start="2023-01-02"):
    dates = pd.date_range(start, periods=len(vals), freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in vals]})


# ---------- 1) exit_signal: 首触发进 new_alerts / 同状态第二轮去重 / 回升后 clear ----------

def test_exit_signal_lifecycle_triggers_dedups_then_clears(tmp_path):
    led = Ledger(tmp_path / "t.db")
    led.mark_bought("000001", "otc_fund", 100.0, "2023-01-02")

    up = [100 + i for i in range(150)]
    down = [249 - i for i in range(120)]  # 自峰值回撤 >15% → 需离场
    dip_prices = _prices(up + down)
    dip_dates = [str(d)[:10] for d in dip_prices["date"]]

    r1 = run_patrol(led, resolve, lambda a: dip_prices, dip_dates, dip_dates[-1])
    exits1 = [a for a in r1["new_alerts"] if a["kind"] == "exit_signal"]
    assert len(exits1) == 1 and exits1[0]["state"] == "triggered"

    r2 = run_patrol(led, resolve, lambda a: dip_prices, dip_dates, dip_dates[-1])
    exits2 = [a for a in r2["new_alerts"] if a["kind"] == "exit_signal"]
    assert exits2 == []  # 同一状态第二轮不重复告警

    recovered = up + [249 - i for i in range(60)] + [190 + i for i in range(200)]
    rec_prices = _prices(recovered)
    rec_dates = [str(d)[:10] for d in rec_prices["date"]]
    r3 = run_patrol(led, resolve, lambda a: rec_prices, rec_dates, rec_dates[-1])
    exits3 = [a for a in r3["new_alerts"] if a["kind"] == "exit_signal"]
    assert len(exits3) == 1 and exits3[0]["state"] == "clear"


# ---------- 2) 取价异常 → data_failure + health.failed + email 含"失败" ----------

def test_data_failure_marks_health_and_email_mentions_failure(tmp_path):
    led = Ledger(tmp_path / "t.db")
    led.mark_bought("000001", "otc_fund", 1.0, "2023-01-02")

    def boom(asset):
        raise RuntimeError("网络超时")

    r = run_patrol(led, resolve, boom, ["2026-07-10"], "2026-07-10")
    fails = [a for a in r["new_alerts"] if a["kind"] == "data_failure"]
    assert len(fails) == 1 and fails[0]["state"] == "triggered"
    assert r["health"]["failed"] == 1
    assert r["email_body"] is not None
    assert "失败" in r["email_body"]


# ---------- 3) pending lot 确认日净值已出 → 自动补记进 filled，加权成本更新 ----------

def test_pending_lot_auto_fills_and_updates_weighted_cost(tmp_path):
    led = Ledger(tmp_path / "t.db")
    led.add_lot("002611", "otc_fund", 8000, 2.8357, "2026-07-07", confirm_date="2026-07-07")
    led.add_lot("002611", "otc_fund", 12000, None, "2026-07-08", confirm_date="2026-07-09")
    before_cost = led.position("002611")["weighted_cost"]
    assert before_cost == 2.8357

    prices = pd.DataFrame({"date": ["2026-07-07", "2026-07-08", "2026-07-09"],
                           "value": [2.8357, 2.8313, 2.8219]})
    dates = ["2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09"]
    r = run_patrol(led, resolve, lambda a: prices, dates, "2026-07-09")

    assert len(r["filled"]) == 1
    assert r["filled"][0]["confirm_date"] == "2026-07-09"
    assert led.pending_lots("002611") == []
    after_cost = led.position("002611")["weighted_cost"]
    assert after_cost != before_cost


# ---------- 4) pending lot 净值未出且已过确认日≥2交易日 → pending_confirm triggered ----------

def test_pending_confirm_triggers_after_grace_days(tmp_path):
    led = Ledger(tmp_path / "t.db")
    led.add_lot("002611", "otc_fund", 8000, 2.8357, "2026-07-07", confirm_date="2026-07-07")
    led.add_lot("002611", "otc_fund", 12000, None, "2026-07-08", confirm_date="2026-07-09")
    prices = pd.DataFrame({"date": ["2026-07-07", "2026-07-08"], "value": [2.8357, 2.8313]})
    dates = ["2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10", "2026-07-13"]

    r = run_patrol(led, resolve, lambda a: prices, dates, "2026-07-13")
    pc = [a for a in r["new_alerts"] if a["kind"] == "pending_confirm"]
    assert len(pc) == 1 and pc[0]["state"] == "triggered"
    assert r["filled"] == []


# ---------- 5) latest_reconciliation verdict==mismatch → reconcile_mismatch triggered ----------

def test_reconcile_mismatch_triggers(tmp_path):
    led = Ledger(tmp_path / "t.db")
    led.mark_bought("000001", "otc_fund", 1.0, "2023-01-02")
    led.add_reconciliation(symbol="000001", trade_date="2026-07-09", expected_daily_pnl=10.0,
                           app_daily_pnl=50.0, delta=40.0, verdict="mismatch")
    prices = _prices([1.0 + i * 0.0005 for i in range(30)])
    dates = [str(d)[:10] for d in prices["date"]]

    r = run_patrol(led, resolve, lambda a: prices, dates, dates[-1])
    rm = [a for a in r["new_alerts"] if a["kind"] == "reconcile_mismatch"]
    assert len(rm) == 1 and rm[0]["state"] == "triggered"


# ---------- 6) 无新告警 → email_body is None; CLI 不发邮件 ----------

_STABLE_VALS = [100, 100.05, 99.98, 100.02, 100.1, 100.05, 99.95, 100.08, 100.03, 100.06]


def test_no_new_alerts_email_body_is_none(tmp_path):
    led = Ledger(tmp_path / "t.db")
    led.mark_bought("000001", "otc_fund", 100.0, "2023-01-02")
    # 短序列（<20 天）：估值分位/MA20/MA60/RSI/MACD 都算不了，不会误触发任何 kind
    prices = _prices(_STABLE_VALS)
    dates = [str(d)[:10] for d in prices["date"]]

    r = run_patrol(led, resolve, lambda a: prices, dates, dates[-1])
    assert r["new_alerts"] == []
    assert r["email_body"] is None


def test_cli_patrol_no_new_alerts_skips_email(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    prices = _prices(_STABLE_VALS)
    dates = [str(d)[:10] for d in prices["date"]]

    monkeypatch.setattr(cli, "_prices_for", lambda asset: prices)
    monkeypatch.setattr(cal, "trade_dates", lambda fetcher=None: dates)
    called = []
    monkeypatch.setattr("quantfox.notify.notify_send", lambda *a, **kw: called.append((a, kw)))

    led = cli._ledger()
    led.mark_bought("000001", "otc_fund", 100.0, dates[0])

    res = runner.invoke(cli.app, ["patrol", "--email"])
    assert res.exit_code == 0, res.output
    out = json.loads(res.output)
    assert out["email_body"] is None
    assert called == []  # 无新告警绝不能发邮件


# ---------- 7) weekly_cone=True 且下行序列 → cone_notes 非空 ----------

def test_weekly_cone_notes_for_declining_series(tmp_path):
    led = Ledger(tmp_path / "t.db")
    vals = [200 - i * 0.5 for i in range(300)]
    prices = _prices(vals)
    dates = [str(d)[:10] for d in prices["date"]]
    led.mark_bought("000001", "otc_fund", vals[0], dates[0])

    r = run_patrol(led, resolve, lambda a: prices, dates, dates[-1], weekly_cone=True)
    assert len(r["cone_notes"]) == 1
    assert r["cone_notes"][0]["symbol"] == "000001"
    assert r["cone_notes"][0]["p50_5d"] < -0.01
    assert r["email_body"] is not None
    assert "波动锥" in r["email_body"]


# ---------- 8a) --intraday 超阈值触发一次、同日第二次沉默 ----------

def test_intraday_patrol_triggers_once_then_silent_same_day(tmp_path):
    led = Ledger(tmp_path / "t.db")
    holdings = [{"symbol": "000001", "type": "otc_fund"}]

    r1 = run_intraday_patrol(led, holdings, lambda s, t: 0.03, "2026-07-10")
    assert len(r1["new_alerts"]) == 1
    assert r1["new_alerts"][0]["state"] == "intraday-2026-07-10-up"
    assert r1["new_alerts"][0]["kind"] == "early_warning"

    r2 = run_intraday_patrol(led, holdings, lambda s, t: 0.03, "2026-07-10")
    assert r2["new_alerts"] == []  # 同日同方向第二次沉默


def test_intraday_patrol_gold_threshold_differs_from_fund(tmp_path):
    led = Ledger(tmp_path / "t.db")
    # 黄金阈值 1.5%：1.6% 触发，基金阈值 2%：1.6% 不触发
    fund_r = run_intraday_patrol(led, [{"symbol": "000001", "type": "otc_fund"}],
                                 lambda s, t: 0.016, "2026-07-10")
    assert fund_r["new_alerts"] == []
    gold_r = run_intraday_patrol(led, [{"symbol": "Au99.99", "type": "gold"}],
                                 lambda s, t: 0.016, "2026-07-10")
    assert len(gold_r["new_alerts"]) == 1


def test_intraday_patrol_unavailable_estimate_is_silent(tmp_path):
    led = Ledger(tmp_path / "t.db")
    r = run_intraday_patrol(led, [{"symbol": "000001", "type": "otc_fund"}],
                            lambda s, t: None, "2026-07-10")
    assert r["new_alerts"] == []


# ---------- 8b) --llm 输出未实现 JSON ----------

def test_cli_llm_flag_echoes_not_implemented(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    res = runner.invoke(cli.app, ["patrol", "--llm"])
    assert res.exit_code == 0, res.output
    out = json.loads(res.output)
    assert out == {"error": "llm 深分析未实现，预留参数位（P3）"}


def test_cli_intraday_flag_uses_intraday_patrol(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    led = cli._ledger()
    led.mark_bought("000001", "otc_fund", 1.0, "2023-01-02")
    monkeypatch.setattr(cli, "_patrol_intraday_pct", lambda symbol, atype: 0.03)

    res = runner.invoke(cli.app, ["patrol", "--intraday"])
    assert res.exit_code == 0, res.output
    out = json.loads(res.output)
    assert len(out["new_alerts"]) == 1
    assert out["new_alerts"][0]["kind"] == "early_warning"
