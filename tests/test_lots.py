from quantfox.storage import Ledger


def test_multi_lot_weighted_cost(tmp_path):
    led = Ledger(tmp_path / "t.db")
    # 7.7 买 8000 @2.8357，7.8 又买 12000 @2.8219（虚构示例金额，分批建仓）
    led.add_lot("002611", "otc_fund", 8000, 2.8357, "2026-07-07")
    led.add_lot("002611", "otc_fund", 12000, 2.8219, "2026-07-08")
    pos = led.position("002611")
    assert pos["total_amount"] == 20000
    # 份额 = 10000/2.8357 + 15000/2.8219
    assert abs(pos["total_shares"] - (round(10000 / 2.8357, 4) + round(15000 / 2.8219, 4))) < 0.01
    # 加权成本 = 总金额/总份额，落在两笔净值之间
    assert 2.82 < pos["weighted_cost"] < 2.836
    assert len(pos["lots"]) == 2  # 两笔明细都在，没被覆盖


def test_holdings_reflects_weighted_cost(tmp_path):
    led = Ledger(tmp_path / "t.db")
    led.add_lot("002611", "gold", 10000, 2.0, "2026-07-07")
    led.add_lot("002611", "gold", 10000, 3.0, "2026-07-08")
    h = {r["symbol"]: r for r in led.list_holdings()}["002611"]
    assert h["status"] == "holding"
    # 加权成本 = 20000 / (5000+3333.33) ≈ 2.4
    assert abs(h["entry_price"] - 2.4) < 0.01
    assert h["entry_date"] == "2026-07-07"  # 最早那笔


def test_position_pnl(tmp_path):
    led = Ledger(tmp_path / "t.db")
    led.add_lot("002611", "gold", 25000, 2.8274, "2026-07-07")
    pos = led.position("002611", latest_nav=2.40)
    assert pos["current_value"] < 25000
    assert pos["pnl"] < 0 and pos["pnl_pct"] < 0
