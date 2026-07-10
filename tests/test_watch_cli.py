import json

import pandas as pd
from typer.testing import CliRunner

import quantfox.calendar_cn as cal
import quantfox.cli as cli

runner = CliRunner()

PRICES = pd.DataFrame({"date": ["2026-07-08", "2026-07-09"], "value": [2.8313, 2.8219]})
DATES = ["2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10", "2026-07-13"]


def _setup(monkeypatch, tmp_path, prices=PRICES):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    monkeypatch.setattr(cli, "_prices_for", lambda asset: prices)
    monkeypatch.setattr(cal, "trade_dates", lambda fetcher=None: DATES)


def test_buy_auto_confirm_before_cutoff(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    res = runner.invoke(cli.app, ["watch", "buy", "002611", "--amount", "8000",
                                  "--entry-date", "2026-07-08", "--order-time", "10:00"])
    assert res.exit_code == 0, res.output
    out = json.loads(res.output)
    assert out["lot"]["confirm_date"] == "2026-07-08"
    assert out["lot"]["nav"] == 2.8313


def test_buy_after_cutoff_records_pending(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    res = runner.invoke(cli.app, ["watch", "buy", "002611", "--amount", "12000",
                                  "--entry-date", "2026-07-09", "--order-time", "15:30"])
    assert res.exit_code == 0, res.output
    out = json.loads(res.output)
    assert out["pending"] is True and out["confirm_date"] == "2026-07-10"
    assert "watch confirm" in out["note"]


def test_watch_confirm_backfills_when_nav_published(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    runner.invoke(cli.app, ["watch", "buy", "002611", "--amount", "12000",
                            "--entry-date", "2026-07-09", "--order-time", "15:30"])
    richer = pd.DataFrame({"date": ["2026-07-08", "2026-07-09", "2026-07-10"],
                           "value": [2.8313, 2.8219, 2.8190]})
    monkeypatch.setattr(cli, "_prices_for", lambda asset: richer)
    res = runner.invoke(cli.app, ["watch", "confirm", "002611"])
    assert res.exit_code == 0, res.output
    out = json.loads(res.output)
    assert len(out["filled"]) == 1 and out["pending"] == []
    assert abs(out["position"]["weighted_cost"] - 2.8190) < 1e-6


def test_buy_with_nav_skips_calendar(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)

    def boom(fetcher=None):
        raise AssertionError("calendar should not be consulted when --nav is given")

    monkeypatch.setattr(cal, "trade_dates", boom)
    res = runner.invoke(cli.app, ["watch", "buy", "002611", "--amount", "8000",
                                  "--nav", "2.8357", "--entry-date", "2026-07-07"])
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["lot"]["nav"] == 2.8357
