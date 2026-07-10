import datetime as dt
import json

import pytest

from quantfox.calendar_cn import nav_date_for_order, trade_dates

# 2026-07 前后：7/6(一)~7/10(五) 是交易日，7/11-12 周末，7/13(一) 交易日
DATES = ["2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10", "2026-07-13"]


def test_before_cutoff_same_day():
    at = dt.datetime(2026, 7, 7, 10, 30)
    assert nav_date_for_order(at, DATES) == "2026-07-07"


def test_after_cutoff_next_trade_day():
    at = dt.datetime(2026, 7, 8, 15, 1)
    assert nav_date_for_order(at, DATES) == "2026-07-09"


def test_weekend_rolls_to_monday():
    at = dt.datetime(2026, 7, 11, 9, 0)  # 周六
    assert nav_date_for_order(at, DATES) == "2026-07-13"


def test_friday_after_cutoff_rolls_to_monday():
    at = dt.datetime(2026, 7, 10, 16, 0)
    assert nav_date_for_order(at, DATES) == "2026-07-13"


def test_calendar_out_of_range_raises():
    with pytest.raises(RuntimeError):
        nav_date_for_order(dt.datetime(2026, 7, 13, 16, 0), DATES)


def test_trade_dates_caches(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    calls = {"n": 0}

    def fake_fetch():
        calls["n"] += 1
        return DATES

    assert trade_dates(fetcher=fake_fetch) == DATES
    assert trade_dates(fetcher=fake_fetch) == DATES  # 第二次走缓存
    assert calls["n"] == 1
    cached = json.loads((tmp_path / "trade_calendar.json").read_text(encoding="utf-8"))
    assert cached["dates"] == DATES


def test_fetch_fail_uses_stale_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    (tmp_path / "trade_calendar.json").write_text(
        json.dumps({"fetched_at": "2020-01-01", "dates": DATES}), encoding="utf-8")

    def boom():
        raise ConnectionError("network down")

    assert trade_dates(fetcher=boom) == DATES  # 过期缓存 + 拉取失败 → 用旧缓存


def test_no_cache_and_fetch_fail_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))

    def boom():
        raise ConnectionError("network down")

    with pytest.raises(RuntimeError, match="confirm-date"):
        trade_dates(fetcher=boom)
