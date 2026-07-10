# Quantfox P2（监控闭环：周报 + 巡检 + 模拟器）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 spec `docs/superpowers/specs/2026-07-10-quantfox-p2-monitoring-design.md`：共享路径模拟器、DataHealth-lite、告警去重、launchd 本地调度、全景淘金周报（五榜+扇形图+战绩回看）、持仓巡检。

**Architecture:** 全部新代码进 Python 引擎：`forecast.simulate_paths` 一个引擎喂周报扇形图和短期波动锥；`gold_report.py`（榜单纯逻辑）与 `gold_report_render.py`（模板渲染）分离；`patrol.py` 纯函数接受注入依赖，CLI 只做接线；调度是生成 launchd plist 的薄 helper。

**Tech Stack:** Python 3.12 + uv、typer、pandas、numpy（pandas 自带依赖）、akshare、ECharts 自包含模板（复用既有 assets 模式）、launchd（macOS）。

## Global Constraints

- 基线：动手前 `uv run pytest -q` = **132 passed, 1 skipped**；每个任务结束全量重跑且全绿。
- 测试不得访问网络、不得碰真实 `~/.quantfox`（一律 `QUANTFOX_HOME=tmp_path` + 注入 fetcher/prices）。
- **隐私铁律**：进 git 的一切不得含真实邮箱/真实个人金额/持仓/收益；测试用合成数据。
- 用户可见文案中文；代码/标识符/commit message 英文；commit 末尾 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- `alerts`、`report_issues` 表 append-only：storage 不提供 UPDATE/DELETE。
- 所有产物写 `QUANTFOX_HOME`（周报在 `reports/gold/`，日志在 `logs/`）。
- 不新增第三方依赖（numpy 随 pandas 已在环境）。
- 任何摘要存在 failed/stale 数据时禁止输出"一切正常"（spec §1.2）。
- 水印文案固定：`历史统计推演，非预测承诺`。

---

### Task 1: `simulate_paths()` + `forecast --short`

**Files:**
- Modify: `quantfox/forecast.py`（文件末尾追加函数）
- Modify: `quantfox/cli.py`（`forecast` 命令加 `--short`）
- Test: `tests/test_simulate.py`（新建）

**Interfaces:**
- Produces: `forecast.simulate_paths(prices: pd.DataFrame, horizon_days: int, n_paths: int = 1000, block: int = 20, conditional_pct: float | None = None, seed: int = 20260710) -> dict | None`。返回键：`days`(list[int] 1..H)、`p10/p25/p50/p75/p90`(list[float]，相对当前净值的累计收益小数，round 4)、`prob_positive_terminal`(float)、`n_paths`、`conditional`(bool)、`degraded_to_unconditional`(bool)、`note`（水印）、可选 `warning`。价格 <120 行返回 None。Task 6（扇形图）与 Task 7（周五波动锥）消费。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_simulate.py`：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_simulate.py -v`
Expected: FAIL（`ImportError: cannot import name 'simulate_paths'`）

- [ ] **Step 3: 实现**

`quantfox/forecast.py` 顶部加 `import numpy as np`，末尾追加：

```python
def simulate_paths(prices: pd.DataFrame, horizon_days: int, n_paths: int = 1000,
                   block: int = 20, conditional_pct=None, seed: int = 20260710):
    """块状自助抽样模拟未来逐日路径（保留波动聚集），供扇形图与短期波动锥共用。
    返回逐日百分位；估值条件化样本不足自动降级并如实标注；历史太短诚实弃权。"""
    s = prices["value"].astype(float).reset_index(drop=True)
    if len(s) < 120:
        return None
    rets = (s / s.shift(1) - 1.0).dropna().reset_index(drop=True).to_numpy()
    if len(rets) <= block:
        return None
    degraded = False
    starts = None
    if conditional_pct is not None:
        win = 252 * 3
        trail = s.rolling(win, min_periods=252).apply(lambda x: (x <= x[-1]).mean(), raw=True)
        band_idx = trail[(trail >= conditional_pct - 0.15) & (trail <= conditional_pct + 0.15)].index
        cand = [i - 1 for i in band_idx if 1 <= i <= len(rets) - block]
        if len(cand) >= 250:
            starts = cand
        else:
            degraded = True
    if starts is None:
        starts = list(range(0, len(rets) - block))
    rng = np.random.default_rng(seed)
    n_blocks = horizon_days // block + 1
    paths = np.empty((n_paths, horizon_days))
    for p in range(n_paths):
        idx = rng.choice(starts, size=n_blocks)
        chunk = np.concatenate([rets[i:i + block] for i in idx])[:horizon_days]
        paths[p] = np.cumprod(1.0 + chunk) - 1.0
    q = {k: np.percentile(paths, v, axis=0) for k, v in
         (("p10", 10), ("p25", 25), ("p50", 50), ("p75", 75), ("p90", 90))}
    out = {"days": list(range(1, horizon_days + 1)),
           **{k: [round(float(x), 4) for x in arr] for k, arr in q.items()},
           "prob_positive_terminal": round(float((paths[:, -1] > 0).mean()), 4),
           "n_paths": n_paths,
           "conditional": conditional_pct is not None and not degraded,
           "degraded_to_unconditional": degraded,
           "note": "历史统计推演，非预测承诺"}
    if len(s) < 500:
        out["warning"] = "样本不足，仅供参考"
    return out
```

- [ ] **Step 4: 跑测试通过后接 CLI**

`quantfox/cli.py` 的 `forecast` 命令改为：

```python
@app.command()
def forecast(query: str,
             short: int = typer.Option(None, "--short", help="短期波动锥：未来 N 个交易日逐日区间（N≤10）")):
    """前瞻收益分布（非点预测）；--short N 给逐日波动锥（区间不是方向）。"""
    from .forecast import forecast as run_fc
    from .forecast import simulate_paths
    from .percentile import price_percentile

    asset = resolve(query)
    prices = _prices_for(asset)
    if short is not None:
        if not 1 <= short <= 10:
            raise typer.BadParameter("--short 取 1..10 个交易日")
        pct = price_percentile(prices, 3).get("price_pct")
        cond = pct if pct is not None and pct > 0.85 else None
        cone = simulate_paths(prices, short, conditional_pct=cond)
        typer.echo(json.dumps({"symbol": asset.symbol, "current_valuation_pct": pct,
                               "cone": cone,
                               "note": "逐日区间（p10-p90），不是方向预测；历史统计推演，非预测承诺"},
                              ensure_ascii=False, indent=2))
        return
    typer.echo(json.dumps(run_fc(prices), ensure_ascii=False, indent=2))
```

在 `tests/test_simulate.py` 追加 CLI 测试：

```python
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
```

- [ ] **Step 5: 全量测试 + Commit**

Run: `uv run pytest -q` → 全绿。

```bash
git add quantfox/forecast.py quantfox/cli.py tests/test_simulate.py
git commit -m "feat(forecast): block-bootstrap path simulator + daily volatility cone via --short"
```

---

### Task 2: DataHealth-lite（health.py）

**Files:**
- Create: `quantfox/health.py`
- Test: `tests/test_health.py`（新建）

**Interfaces:**
- Produces: `health.health_item(symbol, status, as_of=None, note="") -> dict`（status ∈ ok/stale/failed）；`health.check_freshness(symbol, prices, trade_dates_list, today: str) -> dict`（用日历判 stale）；`health.summarize_health(items) -> dict`（键 `ok/stale/failed`(int)、`healthy`(bool)、`detail`(非 ok 项列表)、`line`(中文摘要行)）。Task 6/7 消费。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_health.py`：

```python
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
```

- [ ] **Step 2: 确认失败**

Run: `uv run pytest tests/test_health.py -v` → FAIL（module not found）

- [ ] **Step 3: 实现**

创建 `quantfox/health.py`：

```python
"""DataHealth-lite：数据健康如实呈现。存在 failed/stale 时 healthy=False，
任何摘要/报告头部必须显示明细行——禁止"一切正常"式假绿（框架 v15 铁律）。"""


def health_item(symbol, status, as_of=None, note=""):
    return {"symbol": symbol, "status": status, "as_of": as_of, "note": note}


def check_freshness(symbol, prices, trade_dates_list, today):
    """最新净值日 < 最近一个交易日(≤today) 即 stale。"""
    if prices is None or len(prices) == 0:
        return health_item(symbol, "failed", note="无净值数据")
    last_nav = str(prices["date"].iloc[-1])[:10]
    past = [d for d in trade_dates_list if d <= today]
    if not past:
        return health_item(symbol, "ok", as_of=last_nav, note="日历不含今日前交易日，无法判 stale")
    latest_trade = past[-1]
    if last_nav < latest_trade:
        return health_item(symbol, "stale", as_of=last_nav, note=f"最近交易日 {latest_trade} 净值未出")
    return health_item(symbol, "ok", as_of=last_nav)


def summarize_health(items):
    ok = [x for x in items if x["status"] == "ok"]
    stale = [x for x in items if x["status"] == "stale"]
    failed = [x for x in items if x["status"] == "failed"]
    healthy = not stale and not failed
    if healthy:
        line = f"数据健康：全部 {len(ok)} 只数据新鲜"
    else:
        parts = [f"{len(ok)} 只新鲜"]
        if stale:
            parts.append(f"{len(stale)} 只 stale（用旧净值，已列明）")
        if failed:
            parts.append(f"{len(failed)} 只失败")
        line = "数据健康：" + "、".join(parts)
    return {"ok": len(ok), "stale": len(stale), "failed": len(failed),
            "healthy": healthy, "detail": stale + failed, "line": line}
```

- [ ] **Step 4: 测试通过 + 全量 + Commit**

```bash
git add quantfox/health.py tests/test_health.py
git commit -m "feat(health): DataHealth-lite freshness check and honest summary line"
```

---

### Task 3: storage P2 表（alerts 去重 + report_issues）

**Files:**
- Modify: `quantfox/storage.py`（`executescript` 加两张表 + 5 个方法）
- Test: `tests/test_alerts_issues.py`（新建）

**Interfaces:**
- Produces: `Ledger.add_alert(symbol, kind, state, message="") -> int`；`Ledger.latest_alert(symbol, kind) -> dict | None`；`Ledger.add_report_issue(issue_date, board, rank, symbol, name, nav_at_issue) -> int`；`Ledger.issues_for(issue_date) -> list[dict]`；`Ledger.latest_issue_date(before) -> str | None`（严格早于 before 的最近一期）。Task 6/7 消费。均 append-only。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_alerts_issues.py`：

```python
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
```

- [ ] **Step 2: 确认失败** → `uv run pytest tests/test_alerts_issues.py -v` FAIL

- [ ] **Step 3: 实现**

`storage.py` 的 `executescript` 里 `reconciliations` 表后追加：

```sql
            CREATE TABLE IF NOT EXISTS alerts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              symbol TEXT NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL,
              message TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS report_issues (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              issue_date TEXT NOT NULL, board TEXT NOT NULL, rank INTEGER NOT NULL,
              symbol TEXT NOT NULL, name TEXT, nav_at_issue REAL, created_at TEXT NOT NULL
            );
```

类内（reconciliations 方法后）追加：

```python
    # --- 告警去重状态（append-only）与周报榜单存档 ---
    def add_alert(self, symbol, kind, state, message=""):
        c = self._conn()
        cur = c.execute("INSERT INTO alerts (symbol,kind,state,message,created_at) VALUES (?,?,?,?,?)",
                        (symbol, kind, state, message, datetime.now(timezone.utc).isoformat()))
        c.commit()
        return cur.lastrowid

    def latest_alert(self, symbol, kind):
        c = self._conn()
        r = c.execute("SELECT * FROM alerts WHERE symbol=? AND kind=? ORDER BY id DESC LIMIT 1",
                      (symbol, kind)).fetchone()
        return dict(r) if r else None

    def add_report_issue(self, issue_date, board, rank, symbol, name, nav_at_issue):
        c = self._conn()
        cur = c.execute(
            "INSERT INTO report_issues (issue_date,board,rank,symbol,name,nav_at_issue,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (issue_date, board, rank, symbol, name, nav_at_issue,
             datetime.now(timezone.utc).isoformat()))
        c.commit()
        return cur.lastrowid

    def issues_for(self, issue_date):
        c = self._conn()
        return [dict(r) for r in c.execute(
            "SELECT * FROM report_issues WHERE issue_date=? ORDER BY board, rank",
            (issue_date,)).fetchall()]

    def latest_issue_date(self, before):
        c = self._conn()
        r = c.execute("SELECT MAX(issue_date) d FROM report_issues WHERE issue_date<?",
                      (before,)).fetchone()
        return r["d"] if r and r["d"] else None
```

- [ ] **Step 4: 测试通过 + 全量 + Commit**

```bash
git add quantfox/storage.py tests/test_alerts_issues.py
git commit -m "feat(storage): append-only alerts dedup state and weekly report issues archive"
```

---

### Task 4: launchd 调度 helper + `quantfox schedule`

**Files:**
- Create: `quantfox/schedule_mac.py`
- Modify: `quantfox/cli.py`（新增 `schedule_app` 子命令组，加在 `watch_app` 定义之后）
- Test: `tests/test_schedule_mac.py`（新建）

**Interfaces:**
- Produces: `schedule_mac.plist_xml(label, program_args: list[str], calendar: list[dict], log_path) -> str`；`schedule_mac.install(intraday=False, exe=None, agents_dir=None, launchctl=None) -> list`；`uninstall(agents_dir=None, launchctl=None) -> list`；`status(agents_dir=None, launchctl=None) -> dict`。`launchctl` 参数为可注入的 `callable(args: list[str])`（默认 subprocess 调 `launchctl`），测试注入 fake。CLI：`quantfox schedule install [--intraday]` / `uninstall` / `status`。

计划的三个任务（spec §1.3）：

| label | 时间 | 命令 |
|---|---|---|
| com.quantfox.weekly | 周五 21:30 | `quantfox gold-report --email` |
| com.quantfox.patrol | 周一至五 21:35 | `quantfox patrol --email` |
| com.quantfox.intraday（--intraday 才装） | 周一至五 14:30 | `quantfox patrol --intraday --email` |

- [ ] **Step 1: 写失败测试**

创建 `tests/test_schedule_mac.py`：

```python
import quantfox.schedule_mac as sm


def test_plist_xml_contains_calendar_and_log():
    xml = sm.plist_xml("com.quantfox.weekly", ["/usr/local/bin/quantfox", "gold-report", "--email"],
                       [{"Weekday": 5, "Hour": 21, "Minute": 30}], "/tmp/x.log")
    for frag in ("<key>Label</key>", "com.quantfox.weekly", "<integer>21</integer>",
                 "<integer>30</integer>", "gold-report", "/tmp/x.log",
                 "<key>StandardErrorPath</key>"):
        assert frag in xml


def test_install_writes_two_plists_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path / "home"))
    calls = []
    paths = sm.install(exe="/opt/quantfox", agents_dir=tmp_path / "agents",
                       launchctl=lambda args: calls.append(args))
    names = sorted(p.name for p in paths)
    assert names == ["com.quantfox.patrol.plist", "com.quantfox.weekly.plist"]
    assert all(("load" in c or "bootstrap" in c[0] if isinstance(c, str) else "load" in c) for c in calls) or calls
    text = (tmp_path / "agents" / "com.quantfox.patrol.plist").read_text()
    assert "<integer>21</integer>" in text and "patrol" in text


def test_install_intraday_adds_third(tmp_path):
    paths = sm.install(intraday=True, exe="/opt/quantfox", agents_dir=tmp_path / "agents",
                       launchctl=lambda args: None)
    assert any(p.name == "com.quantfox.intraday.plist" for p in paths)


def test_install_without_exe_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(sm.shutil, "which", lambda name: None)
    try:
        sm.install(agents_dir=tmp_path / "agents", launchctl=lambda a: None)
        assert False, "should raise"
    except RuntimeError as e:
        assert "uv tool install" in str(e)


def test_uninstall_removes(tmp_path):
    sm.install(exe="/opt/quantfox", agents_dir=tmp_path / "agents", launchctl=lambda a: None)
    removed = sm.uninstall(agents_dir=tmp_path / "agents", launchctl=lambda a: None)
    assert len(removed) >= 2 and not list((tmp_path / "agents").glob("com.quantfox.*"))


def test_status_reports_missing(tmp_path):
    st = sm.status(agents_dir=tmp_path / "agents", launchctl=lambda a: "")
    assert st["com.quantfox.weekly"]["installed"] is False
```

- [ ] **Step 2: 确认失败** → FAIL（module not found）

- [ ] **Step 3: 实现**

创建 `quantfox/schedule_mac.py`：

```python
"""本地 launchd 调度（macOS）。生成 ~/Library/LaunchAgents 下的 plist：
周报（周五21:30）/ 收盘巡检（工作日21:35）/ 盘中巡检（可选，工作日14:30）。
云端 /schedule 摸不到本地 ~/.quantfox，故只支持本机调度；睡眠错过由 launchd 唤醒后补跑。"""
import platform
import shutil
import subprocess
from pathlib import Path

from .config import data_dir

_WEEKDAYS = [1, 2, 3, 4, 5]

JOBS = {
    "com.quantfox.weekly": {"args": ["gold-report", "--email"],
                            "calendar": [{"Weekday": 5, "Hour": 21, "Minute": 30}]},
    "com.quantfox.patrol": {"args": ["patrol", "--email"],
                            "calendar": [{"Weekday": w, "Hour": 21, "Minute": 35} for w in _WEEKDAYS]},
    "com.quantfox.intraday": {"args": ["patrol", "--intraday", "--email"],
                              "calendar": [{"Weekday": w, "Hour": 14, "Minute": 30} for w in _WEEKDAYS]},
}


def _default_launchctl(args):
    return subprocess.run(["launchctl", *args], capture_output=True, text=True).stdout


def _default_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def plist_xml(label, program_args, calendar, log_path) -> str:
    def dic(entries):
        inner = "".join(f"<key>{k}</key><integer>{v}</integer>" for k, v in entries.items())
        return f"<dict>{inner}</dict>"

    cal = "".join(dic(c) for c in calendar)
    args = "".join(f"<string>{a}</string>" for a in program_args)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>{label}</string>
<key>ProgramArguments</key><array>{args}</array>
<key>StartCalendarInterval</key><array>{cal}</array>
<key>StandardOutPath</key><string>{log_path}</string>
<key>StandardErrorPath</key><string>{log_path}</string>
</dict></plist>
"""


def _jobs(intraday):
    names = ["com.quantfox.weekly", "com.quantfox.patrol"] + (
        ["com.quantfox.intraday"] if intraday else [])
    return {n: JOBS[n] for n in names}


def install(intraday=False, exe=None, agents_dir=None, launchctl=None):
    if platform.system() != "Darwin" and agents_dir is None:
        raise RuntimeError("仅支持 macOS launchd；其他平台请自行 crontab，例如：30 21 * * 5 quantfox gold-report --email")
    exe = exe or shutil.which("quantfox")
    if not exe:
        raise RuntimeError("找不到 quantfox 可执行文件：先 `uv tool install .` 装成全局命令")
    agents_dir = Path(agents_dir or _default_agents_dir())
    agents_dir.mkdir(parents=True, exist_ok=True)
    launchctl = launchctl or _default_launchctl
    logs = data_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    written = []
    for label, job in _jobs(intraday).items():
        p = agents_dir / f"{label}.plist"
        p.write_text(plist_xml(label, [exe, *job["args"]], job["calendar"],
                               str(logs / f"{label}.log")), encoding="utf-8")
        launchctl(["unload", str(p)])
        launchctl(["load", "-w", str(p)])
        written.append(p)
    return written


def uninstall(agents_dir=None, launchctl=None):
    agents_dir = Path(agents_dir or _default_agents_dir())
    launchctl = launchctl or _default_launchctl
    removed = []
    for label in JOBS:
        p = agents_dir / f"{label}.plist"
        if p.exists():
            launchctl(["unload", str(p)])
            p.unlink()
            removed.append(p)
    return removed


def status(agents_dir=None, launchctl=None):
    agents_dir = Path(agents_dir or _default_agents_dir())
    launchctl = launchctl or _default_launchctl
    loaded = launchctl(["list"]) or ""
    out = {}
    for label in JOBS:
        p = agents_dir / f"{label}.plist"
        log = data_dir() / "logs" / f"{label}.log"
        tail = ""
        if log.exists():
            lines = log.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
            tail = lines[-1] if lines else ""
        out[label] = {"installed": p.exists(), "loaded": label in loaded, "last_log": tail}
    return out
```

`quantfox/cli.py` 在 `watch_app` 组命令之后追加：

```python
schedule_app = typer.Typer(help="本地定时（macOS launchd）：周报/巡检自动跑")
app.add_typer(schedule_app, name="schedule")


@schedule_app.command("install")
def schedule_install(intraday: bool = typer.Option(False, "--intraday", help="加装盘中 14:30 巡检")):
    """安装 launchd 定时：周五21:30 周报 + 工作日21:35 巡检。Mac 睡眠会错过，唤醒后补跑。"""
    from .schedule_mac import install

    try:
        paths = install(intraday=intraday)
    except RuntimeError as e:
        raise typer.BadParameter(str(e)) from e
    typer.echo(json.dumps({"installed": [str(p) for p in paths]}, ensure_ascii=False, indent=2))


@schedule_app.command("uninstall")
def schedule_uninstall():
    """卸载全部 quantfox 定时任务。"""
    from .schedule_mac import uninstall

    typer.echo(json.dumps({"removed": [str(p) for p in uninstall()]}, ensure_ascii=False))


@schedule_app.command("status")
def schedule_status():
    """查看定时任务安装/加载状态与最近日志行。"""
    from .schedule_mac import status

    typer.echo(json.dumps(status(), ensure_ascii=False, indent=2))
```

- [ ] **Step 4: 测试通过 + 全量 + Commit**

```bash
git add quantfox/schedule_mac.py quantfox/cli.py tests/test_schedule_mac.py
git commit -m "feat(schedule): launchd helper with install/uninstall/status CLI"
```

---

### Task 5: 周报榜单纯逻辑（gold_report.py）+ metrics_batch 增列

**Files:**
- Modify: `quantfox/metrics_batch.py`（`_compute_one` 增两列）
- Create: `quantfox/gold_report.py`（纯逻辑：候选池 + 五榜）
- Test: `tests/test_gold_report.py`（新建）

**Interfaces:**
- Consumes: `metrics_batch.metrics_batch(codes) -> list[dict]`（本任务给每行增加 `dist_from_52w_high: float`、`ma20_above_ma60: bool`）；`screen.screen(df, ...) -> list[dict]`（行含 code/name/theme/score/overheated——以实际代码为准，先读 `quantfox/screen.py`）。
- Produces: `gold_report.select_pool(universes: dict[str, pd.DataFrame]) -> list[str]`（≤80 只去重代码）；`gold_report.build_boards(universes, pool_metrics: list[dict], screen_rows: list[dict], top=10) -> dict`——返回 `{"potential": [...], "high_return": [...], "steady": [...], "pullback": [...], "defensive": [...]}`，行含 `code/name/fund_type/sort_key/r_1y/sharpe/calmar/max_drawdown/ann_vol/price_pct/dist_from_52w_high/flags/ma20_above_ma60/name_theme_mismatch` 及榜专属列（potential 加 `score/overheated`）。Task 6 消费。

**先读**：`quantfox/screen.py`（theme 归类与 screen() 输出行结构）、`quantfox/metrics.py`（键名）。

- [ ] **Step 1: metrics_batch 增列（含测试）**

`tests/test_metrics_batch.py` 追加：

```python
def test_compute_one_has_dist_and_ma(monkeypatch):
    import numpy as np
    import pandas as pd

    import quantfox.metrics_batch as mb

    n = 400
    vals = np.concatenate([np.linspace(1.0, 2.0, n - 60), np.linspace(2.0, 1.6, 60)])  # 距高点 -20%
    df = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
                       "value": vals})
    monkeypatch.setattr(mb, "load_prices", lambda a: df)
    row = mb._compute_one("000001")
    assert abs(row["dist_from_52w_high"] - 0.2) < 0.01
    assert row["ma20_above_ma60"] is False  # 尾段下行
```

`metrics_batch._compute_one` 的 return 前加：

```python
    v = prices["value"].astype(float)
    tail = v.tail(TRADING_DAYS_PER_YEAR)
    dist = round(1.0 - float(tail.iloc[-1]) / float(tail.max()), 4) if len(tail) else None
    ma_ok = bool(v.tail(20).mean() > v.tail(60).mean()) if len(v) >= 60 else None
```

并在返回 dict 中加 `"dist_from_52w_high": dist, "ma20_above_ma60": ma_ok,`。

- [ ] **Step 2: 五榜纯逻辑测试**

创建 `tests/test_gold_report.py`（合成 universe + 合成 metrics 行，不触网）：

```python
import pandas as pd

from quantfox.gold_report import build_boards, select_pool


def _uni(codes, r1y_base=10.0):
    n = len(codes)
    return pd.DataFrame({
        "code": codes, "name": [f"示例基金{c}" for c in codes],
        "r_1w": [0.1] * n, "r_1m": [1.0] * n, "r_3m": [3.0] * n, "r_6m": [6.0] * n,
        "r_1y": [r1y_base + i for i in range(n)],
        "r_2y": [15.0] * n, "r_3y": [20.0] * n, "ytd": [5.0] * n, "fee": [0.0015] * n,
    })


def _met(code, fund_type="股票型", **kw):
    row = {"code": code, "name": f"示例基金{code}", "fund_type": fund_type,
           "sharpe": 1.0, "calmar": 0.8, "max_drawdown": -0.2, "ann_vol": 0.15,
           "price_pct": 0.5, "dist_from_52w_high": 0.05, "ma20_above_ma60": True,
           "flags": [], "error": None}
    row.update(kw)
    return row


UNIVERSES = {"股票型": _uni([f"10{i:04d}" for i in range(30)]),
             "混合型": _uni([f"20{i:04d}" for i in range(30)]),
             "债券型": _uni([f"30{i:04d}" for i in range(30)], r1y_base=3.0),
             "指数型": _uni([f"40{i:04d}" for i in range(30)]),
             "QDII": _uni([f"50{i:04d}" for i in range(30)])}


def test_pool_bounded_and_deduped():
    pool = select_pool(UNIVERSES)
    assert 0 < len(pool) <= 80 and len(pool) == len(set(pool))


def test_boards_shapes_and_gates():
    pool = select_pool(UNIVERSES)
    metrics = [_met(c) for c in pool]
    # 构造榜单素材：一只捡漏（打折20%卡玛1.2）、一只债基假稳、一只高估值
    metrics[0].update(dist_from_52w_high=0.20, calmar=1.2)
    metrics[1].update(fund_type="债券型", flags=["bond_equity_risk"], ann_vol=0.02)
    metrics[2].update(price_pct=0.95)
    screen_rows = [{"code": m["code"], "name": m["name"], "theme": "宽基", "score": 90 - i,
                    "overheated": i == 0} for i, m in enumerate(metrics[:12])]
    boards = build_boards(UNIVERSES, metrics, screen_rows, top=10)
    assert set(boards) == {"potential", "high_return", "steady", "pullback", "defensive"}
    assert len(boards["potential"]) == 10 and boards["potential"][0]["overheated"] is True
    assert all(len(b) <= 10 for b in boards.values())
    # 回调捡漏：满足 卡玛>0.5 且 打折>15% 的那只在榜
    assert any(r["code"] == metrics[0]["code"] for r in boards["pullback"])
    # 防守榜：带 flags 的债基沉底或标红（不剔除但 flagged 排最后）
    dfs = boards["defensive"]
    assert all((r["flags"] == []) or (i >= len([x for x in dfs if not x["flags"]]))
               for i, r in enumerate(dfs))
    # 高估值标记透传
    hi = [r for b in boards.values() for r in b if r["code"] == metrics[2]["code"]]
    assert all(r["price_pct"] > 0.85 for r in hi)


def test_name_theme_mismatch_flagged():
    pool = select_pool(UNIVERSES)
    metrics = [_met(c) for c in pool]
    metrics[3]["name"] = "示例医疗精选"
    screen_rows = [{"code": metrics[3]["code"], "name": metrics[3]["name"],
                    "theme": "半导体", "score": 99, "overheated": False}]
    boards = build_boards(UNIVERSES, metrics, screen_rows, top=10)
    row = next(r for r in boards["potential"] if r["code"] == metrics[3]["code"])
    assert row["name_theme_mismatch"] is True
```

- [ ] **Step 3: 确认失败** → FAIL（module not found）

- [ ] **Step 4: 实现 gold_report.py**

创建 `quantfox/gold_report.py`：

```python
"""全景淘金周报：五榜纯逻辑（不取数、不渲染——可注入可测试）。
诚实内建：高收益榜特意保留但满屏警示；估值>0.85 标红；假稳 flags 不剔除但沉底；
幸存者偏差与"过去≠未来"由渲染层固定文案承担。"""
import pandas as pd

_INDUSTRY_WORDS = ["医疗", "医药", "半导体", "新能源", "白酒", "军工", "科技", "消费",
                   "金融", "地产", "黄金", "芯片", "光伏", "汽车"]


def select_pool(universes: dict) -> list:
    """候选池 ≤80：每类 r_1y top8 ∪ 股票/混合/指数/QDII 的 r_3y top8 ∪ 债券型 r_3y top20。"""
    codes = []
    for t, df in universes.items():
        codes += list(df.sort_values("r_1y", ascending=False)["code"].head(8))
    for t in ("股票型", "混合型", "指数型", "QDII"):
        if t in universes:
            codes += list(universes[t].sort_values("r_3y", ascending=False)["code"].head(8))
    if "债券型" in universes:
        codes += list(universes["债券型"].sort_values("r_3y", ascending=False)["code"].head(20))
    seen, out = set(), []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out[:80]


def _fund_type_of(code, universes):
    for t, df in universes.items():
        if (df["code"] == code).any():
            return t
    return None


def _name_theme_mismatch(name, theme):
    if not name or not theme:
        return False
    for w in _INDUSTRY_WORDS:
        if w in name and w not in theme:
            return True
    return False


def _base_row(m, universes):
    code = m["code"]
    r1y = None
    t = m.get("fund_type") or _fund_type_of(code, universes)
    if t and t in universes:
        hit = universes[t].loc[universes[t]["code"] == code, "r_1y"]
        r1y = float(hit.iloc[0]) if len(hit) else None
    return {"code": code, "name": m.get("name"), "fund_type": t, "r_1y": r1y,
            "sharpe": m.get("sharpe"), "calmar": m.get("calmar"),
            "max_drawdown": m.get("max_drawdown"), "ann_vol": m.get("ann_vol"),
            "price_pct": m.get("price_pct"),
            "dist_from_52w_high": m.get("dist_from_52w_high"),
            "ma20_above_ma60": m.get("ma20_above_ma60"),
            "flags": m.get("flags") or [], "name_theme_mismatch": False}


def _pareto_steady(rows):
    """夏普/卡玛双指标非支配集（都不为 None 的行）。"""
    cand = [r for r in rows if r["sharpe"] is not None and r["calmar"] is not None]
    front = []
    for r in cand:
        if not any(o["sharpe"] >= r["sharpe"] and o["calmar"] >= r["calmar"]
                   and (o["sharpe"] > r["sharpe"] or o["calmar"] > r["calmar"]) for o in cand):
            front.append(r)
    return front


def build_boards(universes, pool_metrics, screen_rows, top=10) -> dict:
    metrics_ok = [m for m in pool_metrics if not m.get("error")]
    by_code = {m["code"]: m for m in metrics_ok}
    rows = [_base_row(m, universes) for m in metrics_ok]
    theme_by_code = {s["code"]: s.get("theme") for s in screen_rows}
    for r in rows:
        r["name_theme_mismatch"] = _name_theme_mismatch(r["name"], theme_by_code.get(r["code"]))

    # 潜力榜：直接消费 screen() 输出（多周期一致+动能不过热），透传 score/overheated
    potential = []
    for s in screen_rows[:top]:
        base = _base_row(by_code.get(s["code"], {"code": s["code"], "name": s.get("name")}), universes)
        base.update({"score": s.get("score"), "overheated": bool(s.get("overheated")),
                     "sort_key": s.get("score"),
                     "name_theme_mismatch": _name_theme_mismatch(s.get("name"), s.get("theme"))})
        potential.append(base)

    # 高收益榜：全类型 r_1y top（特意保留，渲染层满屏警示）
    all_uni = pd.concat(universes.values(), ignore_index=True)
    hi = all_uni.sort_values("r_1y", ascending=False).head(top)
    high_return = []
    for _, u in hi.iterrows():
        m = by_code.get(str(u["code"]), {"code": str(u["code"]), "name": u["name"]})
        base = _base_row(m, universes)
        base.update({"r_1y": float(u["r_1y"]), "sort_key": float(u["r_1y"])})
        high_return.append(base)

    steady = sorted(_pareto_steady(rows), key=lambda r: r["calmar"], reverse=True)[:top]
    for r in steady:
        r["sort_key"] = r["calmar"]

    pullback = [r for r in rows
                if (r["calmar"] or 0) > 0.5 and (r["dist_from_52w_high"] or 0) > 0.15]
    pullback = sorted(pullback, key=lambda r: (r["dist_from_52w_high"] or 0) * (r["calmar"] or 0),
                      reverse=True)[:top]
    for r in pullback:
        r["sort_key"] = round((r["dist_from_52w_high"] or 0) * (r["calmar"] or 0), 4)

    bonds = [r for r in rows if r["fund_type"] == "债券型"]
    clean = sorted([r for r in bonds if not r["flags"]], key=lambda r: r["ann_vol"] or 9)
    flagged = sorted([r for r in bonds if r["flags"]], key=lambda r: r["ann_vol"] or 9)
    defensive = (clean + flagged)[:top]  # 假稳不剔除但沉底标红（渲染层）
    for r in defensive:
        r["sort_key"] = r["ann_vol"]

    return {"potential": potential, "high_return": high_return, "steady": steady,
            "pullback": pullback, "defensive": defensive}
```

（若 `screen.py` 的行键名与上文不符，以实际代码为准调整并在报告注明。）

- [ ] **Step 5: 测试通过 + 全量 + Commit**

```bash
git add quantfox/metrics_batch.py quantfox/gold_report.py tests/test_metrics_batch.py tests/test_gold_report.py
git commit -m "feat(gold-report): candidate pool and five honest boards (pure logic) + dist/ma columns in metrics-batch"
```

---

### Task 6: 周报渲染 + 战绩回看 + 事件日历 + CLI `gold-report`

**Files:**
- Create: `quantfox/gold_report_render.py`、`quantfox/assets/gold_report_template.html`、`quantfox/data/events_cn.py`
- Modify: `quantfox/cli.py`（新命令 `gold-report`）、`quantfox/notify.py`（加 `notify_send` 薄封装）
- Test: `tests/test_gold_render.py`（新建）

**Interfaces:**
- Consumes: Task 1 `simulate_paths`、Task 2 `summarize_health/check_freshness`、Task 3 issues 方法、Task 5 `select_pool/build_boards`、既有 `report.html_to_pdf`、`screen.screen`、`data.valuation.market_valuation`。
- Produces: `gold_report_render.build_gold_html(payload: dict) -> str`（自包含 HTML）；`gold_report_render.assemble(universes, prices_fn, metrics_fn, screen_fn, led, today, trade_dates_list, top=10) -> dict`（payload：boards/health/summary/review/charts/events/meta）。`notify.notify_send(subject, body, attach=None, html=False) -> dict`（转发 send_email——通道扩展点）。CLI `quantfox gold-report [--email] [--top 10]`。

**要点（实现按此展开）**：
1. `assemble()` 流程：5 类 universe → `screen.screen(股票型 universe)` 出潜力榜原料 → `select_pool` → `metrics_fn(pool)`（生产为 `metrics_batch`）→ 对五榜全部上榜 code 用 `prices_fn` 并发拉净值（ThreadPoolExecutor 4 workers、重试1次；失败记 health failed）→ 每只 `check_freshness` 记 health → top-3/榜做 `simulate_paths(prices, 250, conditional_pct=price_pct if >0.85 else None)`，其余上榜的做 `simulate_paths(prices, 60, n_paths=300)` 只取 p50 当迷你线 → 榜单成分 `add_report_issue`（nav_at_issue=该基金最新净值；取价失败的存 None）→ `latest_issue_date(before=today)` 有则对上期逐只算 `(nav_now/nav_at_issue - 1)`，按榜聚合平均，产出 review 节（上期取价失败/已无数据的行标"无法回看"）→ events：`events_cn.next_week_events()` 返回 None 则 payload["events"]=None 且 health line 追加"（事件日历不可用）"。
2. 模板 `gold_report_template.html`：复用 `screen_report_template.html` 的自包含结构与 `report.py` 内联 echarts 的做法（先读这两个文件）；布局：头部四件套（regime/health 行/金矿摘要/免责+幸存者偏差）→ 五榜表（估值>0.85 单元格红底；flags 红字；`name_theme_mismatch` 显示"名实待核"徽标；高收益榜表头带"⚠️ 裸收益榜：追高与回撤风险自负"横幅）→ 每榜 top-3 扇形图（历史净值线 + p50 + p10-p90 与 p25-p75 两层带状 area，tooltip 显示"第X天：中位+Y%，80%区间[A,B]"）+ 其余迷你 p50 线 → 我的持仓节（Task 7 提供数据则渲染，payload 无则省略）→ 上期回看表 → 尾部固定水印“历史统计推演，非预测承诺”。
3. `events_cn.py`：

```python
"""下周宏观事件（尽力而为）：接口异常/结构变化一律返回 None——省略整节，绝不编数据。"""
import datetime as _dt


def next_week_events():
    try:
        import akshare as ak
        import pandas as pd

        df = ak.news_economic_baidu()
        col_date = "日期" if "日期" in df.columns else df.columns[0]
        col_name = "事件" if "事件" in df.columns else df.columns[1]
        today = _dt.date.today()
        end = today + _dt.timedelta(days=7)
        out = []
        for _, r in df.iterrows():
            d = pd.to_datetime(r[col_date]).date()
            if today <= d <= end:
                out.append({"date": d.isoformat(), "event": str(r[col_name])})
        return out or None
    except Exception:  # noqa - 任何异常都弃权
        return None
```

4. CLI `gold-report`：接线真实依赖（universes 5 次 `load_universe`；`metrics_batch`；`load_prices`）；输出 HTML+PDF 到 `data_dir()/reports/gold/gold_YYYY-MM-DD.html/.pdf`（目录不存在则建）；`--email` 用 `notify_send(subject=f"[quantfox周报] {MM-DD} 五类Top10 + 预测曲线", attach=pdf)`。
5. `notify.notify_send`：

```python
def notify_send(subject, body="", attach=None, html=False):
    """通知发送薄封装：当前只有邮件通道；未来加通道只改这里。"""
    return send_email(None, subject, body, attach=attach, html=html)
```

- [ ] **Step 1: 写失败测试**（`tests/test_gold_render.py`，全合成注入：fake universes（复用 test_gold_report 的 `_uni`）、`prices_fn` 返回合成净值、`metrics_fn` 返回合成行、`screen_fn` 返回合成 screen 行、`Ledger(tmp_path)`）：

```python
def test_assemble_and_render(tmp_path, monkeypatch):
    # 断言：payload 含 boards/health/review/charts/events 键；首期 review 为 None；
    # 第二次以 today+7 调 assemble → review 非空且含每榜平均；
    # build_gold_html 输出含 "历史统计推演，非预测承诺"、health line、"⚠️"、五榜标题、ECharts 数据 JSON；
    # issues 表两期都有行。
```

（测试代码由实现者按上述断言写全——每条断言都必须落成可执行 assert，不许留空壳。）

- [ ] **Step 2: 确认失败 → 实现 → 通过**（顺序：events_cn → notify_send → assemble → 模板 → CLI）

- [ ] **Step 3: 全量测试 + Commit**

```bash
git add quantfox/gold_report_render.py quantfox/assets/gold_report_template.html quantfox/data/events_cn.py quantfox/cli.py quantfox/notify.py tests/test_gold_render.py
git commit -m "feat(gold-report): self-contained weekly report with fan charts, issue archive, prior-issue review, best-effort event calendar"
```

---

### Task 7: 持仓巡检 patrol

**Files:**
- Create: `quantfox/patrol.py`
- Modify: `quantfox/cli.py`（新命令 `patrol`）
- Test: `tests/test_patrol.py`（新建）

**Interfaces:**
- Consumes: `monitor.check_holding/check_candidate`、`Ledger`（holdings/lots/pending_lots/fill_lot/daily_expectation/add_reconciliation/latest_reconciliation/add_alert/latest_alert）、`health`、`simulate_paths`、`percentile.price_percentile`、`calendar_cn.trade_dates`、`notify.notify_send`。
- Produces: `patrol.run_patrol(led, resolve_fn, prices_fn, trade_dates_list, today, weekly_cone=False) -> dict`（键：`new_alerts` list、`health` dict、`expect` list、`filled` list、`cone_notes` list、`email_body` str|None——无新告警时 None）。CLI `quantfox patrol [--email] [--intraday] [--llm]`。

**告警状态机（写死在 patrol.py，全部走 alerts 去重：状态变才追加+计入邮件）**：

| kind | triggered 条件 | clear 条件 |
|---|---|---|
| data_failure | prices_fn 抛异常 | 本次取价成功 |
| exit_signal | check_holding status=="需离场" | 状态不再是需离场 |
| early_warning | status=="留意" | 不再留意 |
| valuation_high | price_pct > 0.85 | ≤0.85 |
| pending_confirm | 存在 pending lot 且 today 已过 confirm_date 后 ≥2 个交易日 | 无此类 pending |
| reconcile_mismatch | latest_reconciliation verdict=="mismatch" | verdict 非 mismatch |

**流程**：对 `led.list_holdings()` 每只：取价（失败→data_failure，继续下一只）→ `check_freshness` 记 health → pending lot 若确认日净值已出 **自动 `fill_lot` 补记**并进 `filled` → 各 kind 算 state → `latest_alert` 比对，变化则 `add_alert` 并进 `new_alerts`（首次出现且 state=="clear" 不记）→ holding 状态的跑 `daily_expectation` + `add_reconciliation(verdict="pending")` 进 `expect` → `weekly_cone=True` 时对 holding 跑 `simulate_paths(prices, 5, conditional)`，p50[-1] < -0.01 则进 `cone_notes`。最后组 `email_body`（有 new_alerts 才组）：health line + 告警列表 + expect 表 + cone_notes。

**CLI**：默认模式接真实依赖，`today=date.today()`，周五（weekday==4）自动 `weekly_cone=True`；`--email` 且 `email_body` 非 None → `notify_send(f"[quantfox巡检] {MM-DD} {len(new_alerts)}条新信号", body)`；无新告警只打印 JSON 摘要不发邮件。`--intraday`：对 holdings 跑既有 `intraday` 逻辑（复用 cli.intraday 的取数分支，抽成 `_intraday_estimate(asset)` 内部函数供两处用），估算涨跌绝对值 >2%（黄金 >1.5%）→ kind="early_warning"、state=f"intraday-{today}-{'up' if chg>0 else 'down'}"，走同一去重；盘中不落 reconciliations。`--llm`：`typer.echo(json.dumps({"error": "llm 深分析未实现，预留参数位（P3）"}, ensure_ascii=False))` 后 return。

- [ ] **Step 1: 写失败测试**（`tests/test_patrol.py`，合成 Ledger + 注入 prices_fn/resolve_fn/日历）：

```python
# 必须覆盖的断言（每条写成真实可执行测试）：
# 1) 首轮跌破触发 exit_signal 进 new_alerts；同一状态第二轮跑 new_alerts 为空（去重）；
#    价格回升后第三轮出 clear 告警。
# 2) 取价抛异常 → data_failure triggered + health.failed==1 + email_body 含"失败"。
# 3) pending lot 确认日净值已出 → 自动补记进 filled，position 加权成本更新。
# 4) pending lot 净值未出且已过确认日2个交易日 → pending_confirm triggered。
# 5) latest reconcile 为 mismatch → reconcile_mismatch triggered。
# 6) 无任何新告警 → email_body is None（CLI 不发邮件：monkeypatch notify_send 断言未调用）。
# 7) weekly_cone=True 且注入下行序列 → cone_notes 非空。
# 8) --llm 输出未实现 JSON；--intraday 超阈值触发一次、同日第二次沉默。
```

（同 Task 6：每条断言写成真实 assert，不许空壳。）

- [ ] **Step 2: 确认失败 → 实现 → 通过 → 全量**

- [ ] **Step 3: Commit**

```bash
git add quantfox/patrol.py quantfox/cli.py tests/test_patrol.py
git commit -m "feat(patrol): daily holdings patrol with deduped alerts, auto backfill, expect logging, weekly cone, intraday mode"
```

---

### Task 8: 框架 v15 + skills 版本引用 + fund-screener 周报入口

**Files:**
- Modify: `quantfox/prompts/analysis_framework.md`（version 15 + 一条铁律）
- Modify: 7 个 `skills/*/SKILL.md`（出处行 v14→v15）+ `skills/fund-screener/SKILL.md`（加一行周报消费）
- Test: `tests/test_framework.py`、`tests/test_skill_file.py`（改断言）

- [ ] **Step 1: 改测试**：`test_framework_v14_iron_rules` 改名 `test_framework_v15_iron_rules`，断言 `framework_version() == "15"`、关键词追加 `"数据健康"`；`test_honesty_matrix_all_skills` 的 keywords 列表追加 `"v15"`。跑确认 FAIL。

- [ ] **Step 2: 实现**：
- 框架首行 `<!-- version: 14 -->` → `15`；「产物与留痕铁律」末尾追加一条：

```markdown
- **数据健康如实呈现**：任何摘要/报告只要存在取数失败或 stale 数据，禁止表述为"一切正常"，必须列出明细行（哪只、什么状态、截至哪天）。
```

- 7 个 SKILL.md 共享段标题行的 `v14` 改 `v15`（仅版本号，其余文字不动）。
- `skills/fund-screener/SKILL.md` 在 SOP 第 1 步（market-valuation）之前加一行：

```markdown
- **第 0.5 步 · 读最新周报**：若 `~/.quantfox/reports/gold/` 有最近一期 gold-report，先读它的五榜与回看战绩作候选起点与热度语境，避免每次从零扫全市场。
```

- [ ] **Step 3: 测试通过 + 全量 + Commit**

```bash
git add quantfox/prompts/analysis_framework.md skills/ tests/test_framework.py tests/test_skill_file.py
git commit -m "feat(framework): v15 data-health honesty rule; skills reference bump; screener consumes weekly report"
```

---

### Task 9: 端到端验收 + 真实冒烟 + 安装调度 + 状态文件

**Files:**
- Modify: `docs/task.md`
- 真实产物：`~/.quantfox/reports/gold/`、`~/Library/LaunchAgents/com.quantfox.*.plist`

- [ ] **Step 1: 全量测试**：`uv run pytest -q` → 全绿，贴总数。
- [ ] **Step 2: 真实周报冒烟（需网络，约 2-5 分钟）**：`uv run quantfox gold-report`（不 --email）→ 断言输出 JSON 给出 html/pdf 路径且 PDF >100KB；`open` HTML 供用户看（打不开就报告路径）。失败则贴错误，不假称通过。
- [ ] **Step 3: 真实巡检冒烟**：`uv run quantfox patrol`（不 --email）→ 输出摘要 JSON；确认 alerts/reconciliations 落库（`sqlite3` 查行数）。
- [ ] **Step 4: 安装调度**：`uv run quantfox schedule install` → `uv run quantfox schedule status` 显示 weekly/patrol 已装已加载。macOS 睡眠语义在输出里向用户复述一句。
- [ ] **Step 5: 更新 `docs/task.md`**：P2 条目打勾（含各组件一句话）；「后续」加 P3 提示（A股市场层+ETF、llm 深分析、事件日历多源）。
- [ ] **Step 6: Commit + push + 收尾四件报告**

```bash
git add docs/task.md
git commit -m "docs: mark P2 monitoring loop done"
git push origin main
```

---

## Self-Review 记录

- **Spec 覆盖**：§0 决策表→Task 4/6/7 分别承接调度/邮件/llm 存根；§1.1→Task 1；§1.2→Task 2（v15 铁律在 Task 8）；§1.3→Task 4；§1.4→Task 3；§2 全部→Task 5/6（issues/回看/事件/邮件标题在 Task 6）；§3 全部→Task 7（含盘中与周五波动锥、自动补记）；§4→Task 8；§6→各任务测试 + Task 9。无缺口。
- **类型一致**：`simulate_paths` 返回键在 Task 6/7 的消费处一致；`health_item/summarize_health` 签名一致；`add_alert/latest_alert`、`add_report_issue/issues_for/latest_issue_date` 与 Task 6/7 调用一致；`notify_send` 在 Task 6 定义、Task 7 消费。
- **占位符**：Task 6/7 的测试步骤以"断言清单"形式给出并明确要求全部落成可执行 assert——这是给 sonnet 实现者的收敛边界而非空壳；其余任务代码齐全。
