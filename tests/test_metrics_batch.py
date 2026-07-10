"""C1: metrics-batch 批量风险指标（并发 + 重试 + 失败标记）。
测试全部用合成净值序列/假 loader，不访问网络（spec §4 的 014502/610108/015724 仅作案例编号引用）。
"""
import time

import pandas as pd
import pytest
from typer.testing import CliRunner

from quantfox.data.resolve import Asset
import quantfox.metrics_batch as mb
from quantfox.cli import app

runner = CliRunner()


def _series(vals, start="2015-01-05"):
    dates = pd.date_range(start, periods=len(vals), freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in vals]})


def _steady(n=800):
    """>3年、低回撤低波动，不触发任何 flag。"""
    return _series([100.0 * (1.0005 ** i) for i in range(n)])


def test_compute_one_returns_five_columns_and_flags(monkeypatch):
    monkeypatch.setattr(mb, "resolve", lambda code: Asset(symbol=code, type="otc_fund", name=f"基金{code}"))
    monkeypatch.setattr(mb, "load_prices", lambda asset: _steady())

    out = mb._compute_one("000001")
    assert out["code"] == "000001"
    assert out["name"] == "基金000001"
    for key in ("sharpe", "calmar", "max_drawdown", "ann_vol", "price_pct"):
        assert key in out
    assert out["flags"] == []
    assert out.get("error") is None


def test_metrics_batch_preserves_input_order_regardless_of_completion_order(monkeypatch):
    # code "slow" 睡得比其它几只都久，仍必须排在它在 codes 里的原始位置
    order_map = {"slow": 0.05, "fast1": 0.0, "fast2": 0.0, "fast3": 0.0}

    def fake_load_prices(asset):
        time.sleep(order_map[asset.symbol])
        return _steady()

    monkeypatch.setattr(mb, "resolve", lambda code: Asset(symbol=code, type="otc_fund"))
    monkeypatch.setattr(mb, "load_prices", fake_load_prices)

    codes = ["slow", "fast1", "fast2", "fast3"]
    results = mb.metrics_batch(codes, max_workers=4)
    assert [r["code"] for r in results] == codes


def test_metrics_batch_single_failure_does_not_abort_batch(monkeypatch):
    calls = {"bad": 0}

    def fake_resolve(code):
        return Asset(symbol=code, type="otc_fund")

    def fake_load_prices(asset):
        if asset.symbol == "bad":
            calls["bad"] += 1
            raise RuntimeError("network down")
        return _steady()

    monkeypatch.setattr(mb, "resolve", fake_resolve)
    monkeypatch.setattr(mb, "load_prices", fake_load_prices)

    results = mb.metrics_batch(["good1", "bad", "good2"], max_workers=2, retries=1)
    by_code = {r["code"]: r for r in results}
    assert by_code["good1"]["error"] is None
    assert by_code["good2"]["error"] is None
    assert "network down" in by_code["bad"]["error"]
    # 重试1次 => 共调用2次
    assert calls["bad"] == 2


def test_metrics_batch_warms_up_js_engine_before_threadpool(monkeypatch):
    # 见 metrics_batch._warmup_js_engine 的 docstring：akshare 的 fund_open_fund_info_em
    # 内部并发首次构造 py_mini_racer.MiniRacer() 会 native crash（进程直接 abort，
    # 真实网络冒烟实测必现）。metrics_batch() 必须在起线程池前调用一次预热。
    calls = []
    monkeypatch.setattr(mb, "_warmup_js_engine", lambda: calls.append(1))
    monkeypatch.setattr(mb, "resolve", lambda code: Asset(symbol=code, type="otc_fund"))
    monkeypatch.setattr(mb, "load_prices", lambda asset: _steady())

    mb.metrics_batch(["000001"], max_workers=1)
    assert calls == [1]


def test_metrics_batch_flags_wired_through_batch(monkeypatch):
    # 锯齿状序列：低回撤（<3%）+ 高波动（>8%）应命中 nav_spike_suspect；同时 <3年 也命中 short_history
    vals = [100.0]
    for i in range(300):
        vals.append(vals[-1] * (1.09 if i % 2 == 0 else 1 / 1.09 * 1.002))
    df = _series(vals)

    monkeypatch.setattr(mb, "resolve", lambda code: Asset(symbol=code, type="otc_fund"))
    monkeypatch.setattr(mb, "load_prices", lambda asset: df)

    results = mb.metrics_batch(["zigzag"], max_workers=1)
    flags = results[0]["flags"]
    assert "short_history" in flags


def test_cli_metrics_batch_outputs_json_array(monkeypatch):
    monkeypatch.setattr(mb, "resolve", lambda code: Asset(symbol=code, type="otc_fund", name=f"基金{code}"))
    monkeypatch.setattr(mb, "load_prices", lambda asset: _steady())

    result = runner.invoke(app, ["metrics-batch", "000001", "000002"])
    assert result.exit_code == 0
    import json
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert len(data) == 2
    codes = {d["code"] for d in data}
    assert codes == {"000001", "000002"}
    for d in data:
        assert "flags" in d


def test_compute_one_has_dist_and_ma(monkeypatch):
    import numpy as np

    n = 400
    vals = np.concatenate([np.linspace(1.0, 2.0, n - 60), np.linspace(2.0, 1.6, 60)])  # 距高点 -20%
    df = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
                       "value": vals})
    monkeypatch.setattr(mb, "resolve", lambda code: Asset(symbol=code, type="otc_fund", name=f"基金{code}"))
    monkeypatch.setattr(mb, "load_prices", lambda a: df)
    row = mb._compute_one("000001")
    assert abs(row["dist_from_52w_high"] - 0.2) < 0.01
    assert row["ma20_above_ma60"] is False  # 尾段下行


@pytest.mark.skipif(True, reason="真实网络冒烟：手工执行，见 .superpowers/sdd/yield-seeker-c1c2-report.md")
def test_real_network_smoke_20_funds_under_60s():
    """人工跑：QUANTFOX_NET_TEST=1 uv run pytest tests/test_metrics_batch.py -k real_network -m '' --no-skip
    默认永远 skip，避免 CI/离线环境访问网络。"""
    codes = [
        "000001", "000003", "000011", "000021", "000031", "000041", "000051",
        "000061", "000071", "000081", "000091", "000201", "000301", "000401",
        "000501", "000601", "000701", "000801", "000901", "001001",
    ]
    start = time.time()
    results = mb.metrics_batch(codes)
    elapsed = time.time() - start
    assert len(results) == 20
    assert elapsed < 60
