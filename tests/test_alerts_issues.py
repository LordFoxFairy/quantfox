from quantfox.storage import Ledger


def test_alert_append_and_latest(tmp_path):
    led = Ledger(tmp_path / "t.db")
    assert led.latest_alert("002611", "exit_signal") is None
    led.add_alert("002611", "exit_signal", "triggered", "跌破 MA60")
    led.add_alert("002611", "exit_signal", "clear", "回到 MA60 上方")
    last = led.latest_alert("002611", "exit_signal")
    assert last["state"] == "clear"
    # 不同 kind 互不影响
    assert led.latest_alert("002611", "valuation_high") is None


def test_issue_roundtrip_and_latest_date(tmp_path):
    led = Ledger(tmp_path / "t.db")
    led.add_report_issue("2026-07-10", "steady", 1, "000001", "示例基金A", 1.5)
    led.add_report_issue("2026-07-10", "steady", 2, "000002", "示例基金B", 2.0)
    led.add_report_issue("2026-07-17", "steady", 1, "000003", "示例基金C", 3.0)
    rows = led.issues_for("2026-07-10")
    assert [r["symbol"] for r in rows] == ["000001", "000002"]
    assert led.latest_issue_date(before="2026-07-17") == "2026-07-10"
    assert led.latest_issue_date(before="2026-07-10") is None
