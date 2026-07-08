import pandas as pd
from typer.testing import CliRunner

import money.cli as cli
from money.cli import app

runner = CliRunner()


def test_evidence_gold_markdown(monkeypatch, tmp_path):
    monkeypatch.setenv("MONEY_HOME", str(tmp_path))
    df = pd.DataFrame({
        "date": pd.date_range("2022-01-01", periods=400).strftime("%Y-%m-%d"),
        "value": [float(i) for i in range(1, 401)],
    })
    monkeypatch.setattr(cli, "_prices_for", lambda asset: df)
    monkeypatch.setattr(cli, "_profile_for", lambda asset: {"applicable": False})
    result = runner.invoke(app, ["evidence", "gold", "--format", "markdown"])
    assert result.exit_code == 0
    assert "证据卡" in result.stdout


def test_resolve_error_exit_code():
    result = runner.invoke(app, ["evidence", "banana"])
    assert result.exit_code != 0
