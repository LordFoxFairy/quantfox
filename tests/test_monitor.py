import pandas as pd

from quantfox.monitor import check_holding
from quantfox.storage import Ledger


def _prices(vals):
    dates = pd.date_range("2023-01-02", periods=len(vals), freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in vals]})


def test_healthy_holding_no_flags():
    # 买入后稳步上涨 → 正常持有
    df = _prices([100 + i * 0.1 for i in range(300)])
    r = check_holding(df, entry_price=100.0, entry_date="2023-01-02")
    assert r["status"] == "正常持有"
    assert r["flags"] == []
    assert r["return_since_entry"] > 0


def test_drawdown_triggers_flag():
    # 涨到 130 再跌回 100 → 自高点回撤 -23%，触发
    up = [100 + i for i in range(150)]        # 100→249
    down = [249 - i for i in range(120)]      # 回落
    df = _prices(up + down)
    r = check_holding(df, entry_price=100.0, entry_date="2023-01-02")
    assert r["status"] == "需关注"
    assert any("回撤" in f or "熔断" in f for f in r["flags"])


def test_holdings_store_roundtrip(tmp_path):
    led = Ledger(tmp_path / "t.db")
    led.add_holding("000001", "otc_fund", 1.5, "2026-01-01", note="半导体")
    led.add_holding("Au99.99", "gold", 900.0, "2026-02-01")
    rows = led.list_holdings()
    assert {r["symbol"] for r in rows} == {"000001", "Au99.99"}
    assert led.remove_holding("000001") == 1
    assert {r["symbol"] for r in led.list_holdings()} == {"Au99.99"}
