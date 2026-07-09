import pandas as pd
from typer.testing import CliRunner

import quantfox.cli as cli
from quantfox.cli import app

runner = CliRunner()


def test_evidence_gold_markdown(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
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


def _valid_evidence():
    return (
        '{"schema_version":"2.0","asset":{"symbol":"501018","type":"otc_fund"},'
        '"price":{"latest":1.23,"latest_date":"2024-01-02"}}'
    )


def test_log_signal_rejects_signal_numeric_mismatch(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    result = runner.invoke(app, [
        "log-signal",
        "--symbol", "501018",
        "--signal", "买",
        "--signal-numeric", "-1",
        "--confidence", "0.6",
        "--price-ref", "1.23",
        "--ts", "2024-01-03",
        "--evidence-json", _valid_evidence(),
    ])
    assert result.exit_code != 0
    assert "signal_numeric" in result.output


def test_log_signal_requires_evidence_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    result = runner.invoke(app, [
        "log-signal",
        "--symbol", "501018",
        "--signal", "观望",
        "--signal-numeric", "0",
        "--confidence", "0.6",
        "--price-ref", "1.23",
        "--ts", "2024-01-03",
    ])
    assert result.exit_code != 0
    assert "evidence" in result.output


def test_log_signal_accepts_valid_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    result = runner.invoke(app, [
        "log-signal",
        "--symbol", "501018",
        "--signal", "观望",
        "--signal-numeric", "0",
        "--confidence", "0.6",
        "--price-ref", "1.23",
        "--ts", "2024-01-03",
        "--evidence-json", _valid_evidence(),
    ])
    assert result.exit_code == 0
    assert "prediction_id" in result.output
