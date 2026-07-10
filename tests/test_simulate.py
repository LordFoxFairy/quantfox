import numpy as np
import pandas as pd

from quantfox.forecast import simulate_paths


def _prices(n, trend=0.0003, vol=0.01, seed=7):
    rng = np.random.default_rng(seed)
    rets = rng.normal(trend, vol, n)
    vals = 2.0 * np.cumprod(1 + rets)
    dates = pd.date_range("2018-01-01", periods=n, freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "value": vals})


def test_reproducible_with_seed():
    p = _prices(1500)
    a = simulate_paths(p, 20)
    b = simulate_paths(p, 20)
    assert a["p50"] == b["p50"] and a["p10"] == b["p10"]


def test_shape_and_monotone_quantiles():
    out = simulate_paths(_prices(1500), 10, n_paths=200)
    assert out["days"] == list(range(1, 11))
    assert len(out["p50"]) == 10 and out["n_paths"] == 200
    for i in range(10):
        assert out["p10"][i] <= out["p25"][i] <= out["p50"][i] <= out["p75"][i] <= out["p90"][i]
    assert out["note"] == "历史统计推演，非预测承诺"


def test_conditional_degrades_when_sparse():
    out = simulate_paths(_prices(600), 10, n_paths=100, conditional_pct=0.99)
    assert out["degraded_to_unconditional"] is True and out["conditional"] is False


def test_conditional_used_when_enough():
    out = simulate_paths(_prices(3000), 10, n_paths=100, conditional_pct=0.5)
    assert out["conditional"] is True and out["degraded_to_unconditional"] is False


def test_short_history_abstains():
    assert simulate_paths(_prices(100), 10) is None
    out = simulate_paths(_prices(300), 10, n_paths=50)
    assert "warning" in out  # <500 行样本不足警告


def test_cli_forecast_short(monkeypatch, tmp_path):
    import json

    from typer.testing import CliRunner

    import quantfox.cli as cli

    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    monkeypatch.setattr(cli, "_prices_for", lambda a: _prices(1500))
    res = CliRunner().invoke(cli.app, ["forecast", "002611", "--short", "5"])
    assert res.exit_code == 0, res.output
    out = json.loads(res.output)
    assert len(out["cone"]["p50"]) == 5 and "非预测承诺" in out["cone"]["note"]
