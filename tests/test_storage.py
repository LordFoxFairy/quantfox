import pandas as pd

from quantfox.storage import Ledger


def _prices(start_val, days):
    dates = pd.date_range("2023-01-01", periods=days, freq="D").strftime("%Y-%m-%d")
    vals = [start_val + i for i in range(days)]  # 每天 +1，上涨
    return pd.DataFrame({"date": dates, "value": [float(v) for v in vals]})


def test_log_and_track(tmp_path):
    led = Ledger(tmp_path / "t.db")
    pid = led.log_signal(
        symbol="501018", type="otc_fund", signal="买", signal_numeric=1,
        confidence=0.6, horizons=[5, 20], price_ref=100.0, evidence_json="{}",
        rationale="test", framework_version="1", schema_version="1.0",
        ts="2023-01-01",
    )
    assert pid > 0
    outs = led.compute_outcomes(pid, _prices(100.0, 40))
    o = outs[0]
    assert o["cost"] > 0                          # 买入扣了往返成本
    assert o["gross_return"] > o["realized_return"]  # 净收益 < 毛收益
    assert o["base_up"] == 1.0                    # 单调上涨→基准上涨基率100%
    tr = led.track_record_for("501018")
    assert tr["past_signals"] == 1
    assert 0.0 <= tr["hit_rate"] <= 1.0
    # 命中但没跑赢基率=只是跟涨，没本事（诚实去虚高）
    assert tr["edge_vs_baserate"] == 0.0


def test_calibration_buckets_by_confidence(tmp_path):
    led = Ledger(tmp_path / "t.db")
    # 高信心(0.9) 买入，价格上涨 → 命中
    pid = led.log_signal(
        symbol="A", type="otc_fund", signal="买", signal_numeric=1, confidence=0.9,
        horizons=[5], price_ref=100.0, evidence_json="{}", rationale="",
        framework_version="1", schema_version="1.0", ts="2023-01-01")
    led.compute_outcomes(pid, _prices(100.0, 40))
    cal = led.calibration("A")
    hi = [b for b in cal["buckets"] if b["range"] == "0.85-1.00"][0]
    assert hi["n"] == 1
    assert hi["hit_rate"] == 1.0
    assert hi["gap"] == round(0.9 - 1.0, 3)  # 略偏保守


def test_append_only_no_overwrite(tmp_path):
    led = Ledger(tmp_path / "t.db")
    a = led.log_signal(
        symbol="X", type="gold", signal="观望", signal_numeric=0, confidence=0.5,
        horizons=[5], price_ref=1.0, evidence_json="{}", rationale="",
        framework_version="1", schema_version="1.0", ts="2023-01-01",
    )
    b = led.log_signal(
        symbol="X", type="gold", signal="买", signal_numeric=1, confidence=0.5,
        horizons=[5], price_ref=1.0, evidence_json="{}", rationale="",
        framework_version="1", schema_version="1.0", ts="2023-01-02",
    )
    assert b == a + 1
