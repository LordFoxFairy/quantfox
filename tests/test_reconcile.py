import pandas as pd

from quantfox.storage import Ledger, classify_delta

PRICES = pd.DataFrame({
    "date": ["2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10"],
    "value": [2.8357, 2.8313, 2.8219, 2.8190],
})


def _ledger_002611(tmp_path):
    led = Ledger(tmp_path / "t.db")
    led.add_lot("002611", "otc_fund", 8000, 2.8357, "2026-07-07", confirm_date="2026-07-07")
    led.add_lot("002611", "otc_fund", 12000, 2.8219, "2026-07-08", confirm_date="2026-07-09")
    return led


def test_daily_expectation_matches_app(tmp_path):
    led = _ledger_002611(tmp_path)
    exp = led.daily_expectation("002611", PRICES)
    assert exp["trade_date"] == "2026-07-10" and exp["prev_date"] == "2026-07-09"
    # 7/10 两笔都已确认（7/7、7/9 均 < 7/10）
    assert abs(exp["expected_daily_pnl"] - (-20.51)) < 0.05
    # 累计 = 份额×nav_t − 投入
    assert abs(exp["expected_total_pnl"] - (-59.45)) < 0.5


def test_confirm_day_shares_not_counted(tmp_path):
    led = _ledger_002611(tmp_path)
    # 只看到 7/9 为止的净值：第二笔当日刚确认，不计当日盈亏 → 只算第一笔
    exp = led.daily_expectation("002611", PRICES.iloc[:3])
    shares_1w = round(8000 / 2.8357, 4)
    assert abs(exp["expected_daily_pnl"] - round(shares_1w * (2.8219 - 2.8313), 2)) < 0.02
    assert exp["shares_counted"] == shares_1w


def test_expectation_none_without_lots_or_prices(tmp_path):
    led = Ledger(tmp_path / "t.db")
    assert led.daily_expectation("002611", PRICES) is None  # 无 lots
    led.add_lot("002611", "otc_fund", 8000, 2.8357, "2026-07-07")
    assert led.daily_expectation("002611", PRICES.iloc[:1]) is None  # 不足两天净值


def test_reconciliation_append_and_latest(tmp_path):
    led = _ledger_002611(tmp_path)
    led.add_reconciliation(symbol="002611", trade_date="2026-07-10",
                           expected_daily_pnl=-20.51, expected_total_pnl=-59.45, verdict="pending")
    led.add_reconciliation(symbol="002611", trade_date="2026-07-10",
                           expected_daily_pnl=-20.51, app_daily_pnl=-20.47,
                           delta=0.04, verdict="ok")
    rows = led.reconciliations_for("002611", trade_date="2026-07-10")
    assert len(rows) == 2  # append-only：两条都在
    assert led.latest_reconciliation("002611")["verdict"] == "ok"


def test_classify_delta_bands():
    assert classify_delta(0.04) == "ok"
    assert classify_delta(-0.05) == "ok"
    assert classify_delta(0.3) == "rounding"
    assert classify_delta(-2.0) == "mismatch"
