import pandas as pd

from quantfox.monitor import check_candidate, check_holding, format_digest
from quantfox.storage import Ledger


def test_digest_all_normal_reports_peace():
    txt = format_digest([], [{"symbol": "000001", "status": "正常持有",
                              "return_since_entry": 0.05, "exit_flags": [], "early_warnings": []}])
    assert "一切正常" in txt
    assert "000001" in txt and "+5.0%" in txt
    assert "非投资建议" in txt


def test_digest_with_triggers():
    watching = [{"symbol": "161725", "status": "可关注买点", "entry_signals": ["估值低位"]}]
    holding = [{"symbol": "000001", "status": "需离场", "return_since_entry": -0.18,
                "exit_flags": ["浮亏 -18%"], "early_warnings": []}]
    txt = format_digest(watching, holding)
    assert "1 个买点" in txt and "1 个需离场" in txt
    assert "-18.0%" in txt


def _prices(vals):
    dates = pd.date_range("2023-01-02", periods=len(vals), freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in vals]})


def test_healthy_holding_no_exit():
    # 买入后稳步上涨 → 无确认离场信号（估值高位可能给"留意"提前预警，但不该"需离场"）
    df = _prices([100 + i * 0.1 for i in range(300)])
    r = check_holding(df, entry_price=100.0, entry_date="2023-01-02")
    assert r["exit_flags"] == []
    assert r["status"] in ("正常持有", "留意")
    assert r["return_since_entry"] > 0


def test_high_valuation_is_early_warning_not_exit():
    # 单调上涨到历史高位：提前预警(留意)，但没跌，不该"需离场"
    df = _prices([100 + i for i in range(300)])
    r = check_holding(df, entry_price=100.0, entry_date="2023-01-02")
    assert r["exit_flags"] == []
    assert r["status"] == "留意"
    assert any("高位" in w for w in r["early_warnings"])


def test_drawdown_triggers_exit():
    # 涨到高点再跌回 → 自高点回撤触发确认离场
    up = [100 + i for i in range(150)]
    down = [249 - i for i in range(120)]
    df = _prices(up + down)
    r = check_holding(df, entry_price=100.0, entry_date="2023-01-02")
    assert r["status"] == "需离场"
    assert any("回撤" in f or "熔断" in f for f in r["exit_flags"])


def test_candidate_low_valuation_is_buy_opportunity():
    # 先高后低：最新在近3年低位 → 出买点线索
    df = _prices([200 - i * 0.1 for i in range(800)])  # 单调下跌，最新最低
    r = check_candidate(df, target_price=None)
    assert r["status"] == "可关注买点"
    assert any("低位" in s for s in r["entry_signals"])


def test_candidate_target_price_hit():
    df = _prices([100 + (i % 5) for i in range(300)])  # 在 100-104 徘徊
    r = check_candidate(df, target_price=110.0)  # 现价 < 110
    assert any("目标买入价" in s for s in r["entry_signals"])


def test_holdings_two_states(tmp_path):
    led = Ledger(tmp_path / "t.db")
    led.add_watching("000001", "otc_fund", target_price=1.2, note="观测")
    led.add_watching("Au99.99", "gold")
    rows = {r["symbol"]: r for r in led.list_holdings()}
    assert rows["000001"]["status"] == "watching"
    assert rows["000001"]["entry_price"] is None
    # 观测 → 买入 转态
    led.mark_bought("000001", "otc_fund", 1.15, "2026-03-01")
    rows = {r["symbol"]: r for r in led.list_holdings()}
    assert rows["000001"]["status"] == "holding"
    assert rows["000001"]["entry_price"] == 1.15
    # 直接新增持仓（未曾观测）
    led.mark_bought("161725", "otc_fund", 0.9, "2026-03-02")
    assert {r["symbol"] for r in led.list_holdings()} == {"000001", "Au99.99", "161725"}
    assert led.remove_holding("Au99.99") == 1
