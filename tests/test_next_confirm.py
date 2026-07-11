import json

from typer.testing import CliRunner

import quantfox.calendar_cn as cal
import quantfox.cli as cli

runner = CliRunner()
DATES = ["2026-07-09", "2026-07-10", "2026-07-13"]


def _setup(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    monkeypatch.setattr(cal, "trade_dates", lambda fetcher=None: DATES)


def test_before_cutoff(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    res = runner.invoke(cli.app, ["next-confirm", "--at", "2026-07-10 10:00"])
    assert res.exit_code == 0, res.output
    out = json.loads(res.output)
    assert out["nav_date"] == "2026-07-10" and "15:00" in out["note"]


def test_after_cutoff_and_weekend(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    assert json.loads(runner.invoke(cli.app, ["next-confirm", "--at", "2026-07-10 16:00"]).output)["nav_date"] == "2026-07-13"
    assert json.loads(runner.invoke(cli.app, ["next-confirm", "--at", "2026-07-11 09:00"]).output)["nav_date"] == "2026-07-13"


def test_malformed_at(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    res = runner.invoke(cli.app, ["next-confirm", "--at", "2026-07-10"])
    assert res.exit_code != 0
    assert "YYYY-MM-DD HH:MM" in res.output


def test_calendar_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))

    def boom(fetcher=None):
        raise RuntimeError("交易日历不可用且无缓存：请用 --confirm-date 手动指定净值确认日")

    monkeypatch.setattr(cal, "trade_dates", boom)
    res = runner.invoke(cli.app, ["next-confirm", "--at", "2026-07-10 10:00"])
    assert res.exit_code != 0
