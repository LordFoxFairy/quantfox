import pandas as pd

from quantfox.health import check_freshness, health_item, summarize_health

DATES = ["2026-07-08", "2026-07-09", "2026-07-10", "2026-07-13"]


def _prices(last_date):
    return pd.DataFrame({"date": ["2026-07-08", last_date], "value": [1.0, 1.01]})


def test_fresh_when_nav_at_latest_trade_date():
    item = check_freshness("000001", _prices("2026-07-10"), DATES, today="2026-07-10")
    assert item["status"] == "ok"


def test_stale_when_nav_older_than_latest_trade_date():
    item = check_freshness("000001", _prices("2026-07-09"), DATES, today="2026-07-10")
    assert item["status"] == "stale" and item["as_of"] == "2026-07-09"


def test_weekend_not_stale():
    # 周六跑：最近交易日仍是周五，周五净值=新鲜
    item = check_freshness("000001", _prices("2026-07-10"), DATES, today="2026-07-11")
    assert item["status"] == "ok"


def test_summarize_never_healthy_with_failures():
    items = [health_item("a", "ok"), health_item("b", "failed", note="取价失败"),
             health_item("c", "stale", as_of="2026-07-09")]
    s = summarize_health(items)
    assert s["healthy"] is False and s["ok"] == 1 and s["failed"] == 1 and s["stale"] == 1
    assert len(s["detail"]) == 2 and "1 只失败" in s["line"] and "1 只 stale" in s["line"]


def test_all_ok_healthy():
    s = summarize_health([health_item("a", "ok"), health_item("b", "ok")])
    assert s["healthy"] is True and "全部 2 只数据新鲜" in s["line"]
