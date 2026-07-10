# Quantfox P1（一致性 + 全局统一 + mandate + 对账留痕）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 spec `docs/superpowers/specs/2026-07-10-quantfox-p1-consistency-mandate-design.md`：统一配置与产物落盘、个人投资档案（mandate-lite）、七 skill 诚实铁律一致化、场外基金 T+1 自动确认与对账留痕。

**Architecture:** Python 引擎（typer CLI + sqlite Ledger）承载全部新代码：`config.py` 扩成统一配置入口，新增 `mandate.py`/`calendar_cn.py` 两个小模块，`storage.py` 加 pending lot 与 append-only `reconciliations` 表；skill 层只改 markdown（框架 v14 + 7 个 SKILL.md 统一引用）。

**Tech Stack:** Python 3.12 + uv、typer、pandas、akshare（全部现有依赖，不新增）、pytest。

## Global Constraints

- 运行测试一律 `python -m pytest`（在仓库根）；动手前基线必须全绿（现 78 passed）。
- 测试不得访问网络：akshare 相关一律注入 fake fetcher / 构造 DataFrame。
- 所有用户可见文案中文；代码、标识符、commit message 英文。
- `reconciliations` 表 append-only：storage 层不提供任何 UPDATE/DELETE 方法。
- 不新增第三方依赖。
- 产物/配置一律在 `data_dir()`（`QUANTFOX_HOME`，默认 `~/.quantfox/`），任何新代码不得往仓库目录写运行产物。
- 金额四舍五入 2 位、份额 4 位、净值原样（与现有 storage 一致）。
- 每个 Task 结束必须 commit，message 末尾带 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。

---

### Task 1: 统一配置 config.json + 目录权限 + reports_dir()

**Files:**
- Modify: `quantfox/config.py`
- Modify: `quantfox/notify.py:15-31`（email_config_path/save/load 三函数）
- Modify: `quantfox/cli.py:231-233`、`quantfox/cli.py:261-263`（reports 目录改用 helper）
- Test: `tests/test_config.py`（新建）

**Interfaces:**
- Consumes: 现有 `config.data_dir()`。
- Produces: `config.reports_dir() -> Path`、`config.config_path() -> Path`、`config.load_config() -> dict`（结构 `{"schema_version":"1.0","smtp":{...},"notify":{"to":...},"prefs":{}}`）、`config.save_config(cfg: dict) -> Path`。`notify.load_email_config()` 返回值保持旧的扁平 dict（smtp 字段 + `notify_to`），`notify.save_email_config(cfg)` 签名不变——后续任务与现有调用方零改动。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_config.py`：

```python
import json
import os
import stat

from quantfox.config import config_path, load_config, reports_dir, save_config


def test_load_config_empty_home(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    cfg = load_config()
    assert cfg["schema_version"] == "1.0"
    assert cfg["smtp"] == {} and cfg["prefs"] == {}


def test_migrates_legacy_email_json(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    legacy = {"smtp_host": "smtp.qq.com", "smtp_port": 465, "username": "a@qq.com",
              "password": "pw", "from_addr": "a@qq.com", "notify_to": "b@qq.com", "use_ssl": True}
    (tmp_path / "email.json").write_text(json.dumps(legacy), encoding="utf-8")
    cfg = load_config()
    assert cfg["smtp"]["smtp_host"] == "smtp.qq.com"
    assert "notify_to" not in cfg["smtp"]
    assert cfg["notify"]["to"] == "b@qq.com"
    assert config_path().exists()  # 迁移后落盘


def test_config_file_permission_0600(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    save_config({"schema_version": "1.0", "smtp": {"password": "x"}, "notify": {}, "prefs": {}})
    mode = stat.S_IMODE(os.stat(config_path()).st_mode)
    assert mode == 0o600


def test_data_dir_permission_0700(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path / "home"))
    reports_dir()  # 触发创建
    mode = stat.S_IMODE(os.stat(tmp_path / "home").st_mode)
    assert mode == 0o700


def test_reports_dir_under_home(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    assert reports_dir() == tmp_path / "reports"
    assert reports_dir().is_dir()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL（`ImportError: cannot import name 'config_path'`）

- [ ] **Step 3: 实现 config.py**

`quantfox/config.py` 全文替换为：

```python
import json
import os
from pathlib import Path


def data_dir() -> Path:
    d = Path(os.environ.get("QUANTFOX_HOME", Path.home() / ".quantfox"))
    d.mkdir(parents=True, exist_ok=True)
    try:
        d.chmod(0o700)
    except OSError:
        pass
    return d


def ledger_path() -> Path:
    return data_dir() / "ledger.db"


def reports_dir() -> Path:
    d = data_dir() / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return data_dir() / "config.json"


def save_config(cfg: dict) -> Path:
    p = config_path()
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        p.chmod(0o600)  # 含 SMTP 授权码，只允许本用户读
    except OSError:
        pass
    return p


def load_config() -> dict:
    """统一配置入口。首次读取若只有旧 email.json 则自动迁移生成 config.json。"""
    p = config_path()
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    legacy = data_dir() / "email.json"
    if legacy.exists():
        smtp = json.loads(legacy.read_text(encoding="utf-8"))
        cfg = {"schema_version": "1.0",
               "smtp": {k: v for k, v in smtp.items() if k != "notify_to"},
               "notify": {"to": smtp.get("notify_to")},
               "prefs": {}}
        save_config(cfg)
        return cfg
    return {"schema_version": "1.0", "smtp": {}, "notify": {}, "prefs": {}}
```

- [ ] **Step 4: notify.py 委托到统一配置**

替换 `quantfox/notify.py` 的 `email_config_path`/`save_email_config`/`load_email_config` 三个函数（其余不动）：

```python
def email_config_path() -> Path:
    from .config import config_path

    return config_path()


def save_email_config(cfg: dict) -> Path:
    from .config import load_config, save_config

    full = load_config()
    full["smtp"] = {k: v for k, v in cfg.items() if k != "notify_to"}
    full.setdefault("notify", {})["to"] = cfg.get("notify_to")
    return save_config(full)


def load_email_config():
    from .config import load_config

    cfg = load_config()
    smtp = cfg.get("smtp") or {}
    if not smtp:
        return None
    return {**smtp, "notify_to": (cfg.get("notify") or {}).get("to")}
```

同时把文件头 docstring 里的 `email.json` 说明改为 `config.json（旧 email.json 自动迁移）`。

- [ ] **Step 5: cli.py 改用 reports_dir()**

`quantfox/cli.py` 顶部 import 改：`from .config import data_dir, ledger_path` → `from .config import ledger_path, reports_dir`。
`screen_report`（231-233 行）和 `report`（261-263 行）里的：

```python
        d = data_dir() / "reports"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"..."
```

两处均改为：

```python
        path = reports_dir() / f"..."
```

（f-string 内容各自保持原样。）

- [ ] **Step 6: 全量测试**

Run: `python -m pytest -q`
Expected: 全绿（含原 test_notify.py roundtrip，现在读写 config.json）

- [ ] **Step 7: Commit**

```bash
git add quantfox/config.py quantfox/notify.py quantfox/cli.py tests/test_config.py
git commit -m "feat(config): unified config.json (auto-migrate email.json), 0700 home / 0600 config, reports_dir helper

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: InvestorMandate-lite（mandate.py + CLI）

**Files:**
- Create: `quantfox/mandate.py`
- Modify: `quantfox/cli.py`（新增 mandate 子命令组，加在 email_app 定义之前）
- Test: `tests/test_mandate.py`（新建）

**Interfaces:**
- Consumes: `config.data_dir()`。
- Produces: `mandate.load_mandate() -> dict | None`、`mandate.save_mandate(m: dict) -> Path`（校验失败 `raise ValueError`）、`mandate.derived(m: dict) -> dict`（键 `single_instrument_amount_cap`/`theme_amount_cap`/`days_to_target`，能算几个算几个）、`mandate.SCHEMA_VERSION = "1.0"`。CLI：`quantfox mandate set ...`、`quantfox mandate show`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_mandate.py`：

```python
import json

import pytest

from quantfox.mandate import derived, load_mandate, mandate_path, save_mandate


def _base():
    return {"schema_version": "1.0", "mandate_as_of": "2026-07-10", "currency": "CNY",
            "total_wealth": 100000.0, "deployable_capital": 60000.0,
            "target_date": "2027-02-10", "target_net_return": 0.08,
            "maximum_loss_amount": 10000.0, "maximum_single_instrument_weight": 0.2,
            "maximum_theme_weight": 0.35}


def test_save_load_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    assert load_mandate() is None
    save_mandate(_base())
    assert load_mandate()["deployable_capital"] == 60000.0


def test_save_backs_up_previous(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    save_mandate(_base())
    m2 = _base()
    m2["deployable_capital"] = 50000.0
    save_mandate(m2)
    bak = json.loads(mandate_path().with_suffix(".json.bak").read_text(encoding="utf-8"))
    assert bak["deployable_capital"] == 60000.0


def test_partial_mandate_ok(monkeypatch, tmp_path):
    # 字段可部分缺省：只给可投金额也合法
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    save_mandate({"schema_version": "1.0", "mandate_as_of": "2026-07-10",
                  "deployable_capital": 30000.0})
    assert load_mandate()["deployable_capital"] == 30000.0


def test_validation_rejects_bad_values(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))
    bad = _base()
    bad["deployable_capital"] = 200000.0  # 超过 total_wealth
    with pytest.raises(ValueError):
        save_mandate(bad)
    bad2 = _base()
    bad2["target_date"] = "2020-01-01"  # 早于 mandate_as_of
    with pytest.raises(ValueError):
        save_mandate(bad2)
    bad3 = _base()
    bad3["maximum_single_instrument_weight"] = 1.5  # 比率出界
    with pytest.raises(ValueError):
        save_mandate(bad3)


def test_derived_caps():
    d = derived(_base())
    assert d["single_instrument_amount_cap"] == 12000.0   # 60000*0.2
    assert d["theme_amount_cap"] == 21000.0               # 60000*0.35
    assert d["days_to_target"] == 215
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_mandate.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'quantfox.mandate'`）

- [ ] **Step 3: 实现 mandate.py**

创建 `quantfox/mandate.py`：

```python
"""个人投资档案（InvestorMandate-lite）：个性化决策的地基。
字段摘自可信决策核心设计 6.1，去掉一切 validated-模型依赖；
除 schema_version 外全部可选——缺什么就少个性化什么，绝不阻断分析。"""
import datetime as _dt
import json
from pathlib import Path

from .config import data_dir

SCHEMA_VERSION = "1.0"


def mandate_path() -> Path:
    return data_dir() / "mandate.json"


def validate(m: dict) -> list[str]:
    errors = []
    tw, dc = m.get("total_wealth"), m.get("deployable_capital")
    if tw is not None and tw <= 0:
        errors.append("total_wealth 必须 > 0")
    if dc is not None and dc <= 0:
        errors.append("deployable_capital 必须 > 0")
    if tw is not None and dc is not None and dc > tw:
        errors.append("deployable_capital 不得超过 total_wealth")
    for k in ("minimum_cash_reserve", "maximum_loss_amount"):
        v = m.get(k)
        if v is not None and v < 0:
            errors.append(f"{k} 不得为负")
    for k in ("maximum_single_instrument_weight", "maximum_theme_weight"):
        v = m.get(k)
        if v is not None and not (0 < v <= 1):
            errors.append(f"{k} 必须在 (0,1]")
    td, as_of = m.get("target_date"), m.get("mandate_as_of")
    if td:
        try:
            base = _dt.date.fromisoformat(as_of) if as_of else _dt.date.today()
            if _dt.date.fromisoformat(td) <= base:
                errors.append("target_date 必须晚于 mandate_as_of")
        except ValueError:
            errors.append("target_date/mandate_as_of 必须是 YYYY-MM-DD")
    return errors


def save_mandate(m: dict) -> Path:
    errors = validate(m)
    if errors:
        raise ValueError("；".join(errors))
    p = mandate_path()
    if p.exists():
        p.replace(p.with_suffix(".json.bak"))  # 覆盖前留一版
    p.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return p


def load_mandate():
    p = mandate_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def derived(m: dict) -> dict:
    """派生量：能算几个算几个（单标的/主题金额上限、距目标天数）。"""
    out = {}
    dc = m.get("deployable_capital")
    if dc and m.get("maximum_single_instrument_weight"):
        out["single_instrument_amount_cap"] = round(dc * m["maximum_single_instrument_weight"], 2)
    if dc and m.get("maximum_theme_weight"):
        out["theme_amount_cap"] = round(dc * m["maximum_theme_weight"], 2)
    if m.get("target_date") and m.get("mandate_as_of"):
        try:
            out["days_to_target"] = (_dt.date.fromisoformat(m["target_date"])
                                     - _dt.date.fromisoformat(m["mandate_as_of"])).days
        except ValueError:
            pass
    return out
```

- [ ] **Step 4: 跑模块测试**

Run: `python -m pytest tests/test_mandate.py -v`
Expected: 6 PASS

- [ ] **Step 5: CLI 子命令**

`quantfox/cli.py` 在 `email_app = typer.Typer(...)` 之前插入：

```python
mandate_app = typer.Typer(help="个人投资档案（个性化决策地基）：本金/目标/风险上限")
app.add_typer(mandate_app, name="mandate")


@mandate_app.command("set")
def mandate_set(total_wealth: float = typer.Option(None, help="全部可计量财富（元）"),
                deployable: float = typer.Option(None, help="本次可投入资金（元）"),
                cash_reserve: float = typer.Option(None, help="现金底线（元）"),
                target_date: str = typer.Option(None, help="目标日期 YYYY-MM-DD"),
                target_return: float = typer.Option(None, help="目标净收益，小数（8% 填 0.08）"),
                max_loss: float = typer.Option(None, help="最大可亏金额（元）"),
                max_single_weight: float = typer.Option(None, help="单标的上限，占可投比例 (0,1]"),
                max_theme_weight: float = typer.Option(None, help="单主题上限，占可投比例 (0,1]"),
                exclude: str = typer.Option(None, help="排除标的，逗号分隔代码"),
                notes: str = typer.Option("", help="备注")):
    """写入/更新档案（覆盖式，旧档案自动备份 .bak）。字段全可选，缺什么少个性化什么。"""
    from .mandate import SCHEMA_VERSION, derived, save_mandate

    m = {"schema_version": SCHEMA_VERSION, "mandate_as_of": _dt.date.today().isoformat(),
         "currency": "CNY", "total_wealth": total_wealth, "deployable_capital": deployable,
         "minimum_cash_reserve": cash_reserve, "target_date": target_date,
         "target_net_return": target_return, "maximum_loss_amount": max_loss,
         "maximum_single_instrument_weight": max_single_weight,
         "maximum_theme_weight": max_theme_weight,
         "excluded_instruments": [x.strip() for x in exclude.split(",") if x.strip()] if exclude else [],
         "notes": notes}
    m = {k: v for k, v in m.items() if v not in (None, [], "")}
    m["schema_version"] = SCHEMA_VERSION
    try:
        p = save_mandate(m)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    typer.echo(json.dumps({"saved": str(p), "mandate": m, "derived": derived(m)},
                          ensure_ascii=False, indent=2))


@mandate_app.command("show")
def mandate_show():
    """显示档案 + 派生量（单标的金额上限等）。无档案时提示如何建立。"""
    from .mandate import derived, load_mandate, mandate_path

    m = load_mandate()
    if m is None:
        typer.echo(json.dumps({"configured": False, "path": str(mandate_path()),
                               "note": "尚无档案：quantfox mandate set --deployable 60000 --max-single-weight 0.2 ..."},
                              ensure_ascii=False))
        return
    typer.echo(json.dumps({"configured": True, "mandate": m, "derived": derived(m)},
                          ensure_ascii=False, indent=2))
```

- [ ] **Step 6: CLI 冒烟 + 全量测试**

Run: `QUANTFOX_HOME=/tmp/qfx-test python -m quantfox.cli mandate set --total-wealth 100000 --deployable 60000 --max-single-weight 0.2 && QUANTFOX_HOME=/tmp/qfx-test python -m quantfox.cli mandate show && python -m pytest -q`
Expected: set/show 输出含 `single_instrument_amount_cap: 12000.0`；pytest 全绿。
（若 `python -m quantfox.cli` 不可执行，用 `uv run quantfox ...` 等价替代。）

- [ ] **Step 7: Commit**

```bash
git add quantfox/mandate.py quantfox/cli.py tests/test_mandate.py
git commit -m "feat(mandate): InvestorMandate-lite profile + mandate set/show CLI

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: 中国交易日历（15:00 cutoff 推净值确认日）

**Files:**
- Create: `quantfox/calendar_cn.py`
- Test: `tests/test_calendar.py`（新建）

**Interfaces:**
- Consumes: `config.data_dir()`；akshare `tool_trade_date_hist_sina`（仅运行时，测试注入 fetcher）。
- Produces: `calendar_cn.trade_dates(fetcher=None) -> list[str]`（ISO 日期升序，带本地缓存）、`calendar_cn.nav_date_for_order(order_at: datetime, dates: list[str]) -> str`。Task 4 消费这两个函数。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_calendar.py`：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_calendar.py -v`
Expected: FAIL（module not found）

- [ ] **Step 3: 实现 calendar_cn.py**

创建 `quantfox/calendar_cn.py`：

```python
"""中国交易日历 + 场外基金 15:00 cutoff 推净值确认日。
数据源 akshare tool_trade_date_hist_sina，本地缓存 30 天；
拉取失败用旧缓存并警告；无缓存直接报错要求 --confirm-date，绝不静默猜。"""
import datetime as _dt
import json
import sys
from pathlib import Path

from .config import data_dir

CACHE_MAX_AGE_DAYS = 30
CUTOFF = _dt.time(15, 0)


def _cache_path() -> Path:
    return data_dir() / "trade_calendar.json"


def _fetch_dates() -> list:
    import akshare as ak

    df = ak.tool_trade_date_hist_sina()
    return sorted(str(x)[:10] for x in df["trade_date"])


def trade_dates(fetcher=None) -> list:
    p = _cache_path()
    cached = None
    if p.exists():
        cached = json.loads(p.read_text(encoding="utf-8"))
        age = (_dt.date.today() - _dt.date.fromisoformat(cached["fetched_at"][:10])).days
        if age <= CACHE_MAX_AGE_DAYS:
            return cached["dates"]
    try:
        dates = (fetcher or _fetch_dates)()
        p.write_text(json.dumps({"fetched_at": _dt.date.today().isoformat(), "dates": dates},
                                ensure_ascii=False), encoding="utf-8")
        return dates
    except Exception as e:  # noqa
        if cached:
            print(f"# 交易日历刷新失败，用旧缓存({cached['fetched_at']}): {e}", file=sys.stderr)
            return cached["dates"]
        raise RuntimeError("交易日历不可用且无缓存：请用 --confirm-date 手动指定净值确认日") from e


def nav_date_for_order(order_at: _dt.datetime, dates: list) -> str:
    """15:00 前 + 当天是交易日 → 按当日净值；否则顺延到下一交易日。"""
    d = order_at.date().isoformat()
    if d in dates and order_at.time() < CUTOFF:
        return d
    later = [x for x in dates if x > d]
    if not later:
        raise RuntimeError(f"交易日历不含 {d} 之后的日期：刷新日历或用 --confirm-date 手动指定")
    return later[0]
```

- [ ] **Step 4: 跑测试**

Run: `python -m pytest tests/test_calendar.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add quantfox/calendar_cn.py tests/test_calendar.py
git commit -m "feat(calendar): CN trade calendar with local cache + 15:00 cutoff nav-date resolver

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: watch buy 自动确认 + pending lot + watch confirm

**Files:**
- Modify: `quantfox/storage.py`（`_recompute_holding`、`position`；新增 `pending_lots`、`fill_lot`）
- Modify: `quantfox/cli.py`（`watch_buy` 重写；新增 `watch confirm`）
- Test: `tests/test_lots.py`（追加）

**Interfaces:**
- Consumes: Task 3 的 `trade_dates`/`nav_date_for_order`；现有 `Ledger.add_lot`（`confirm_nav=None` 时 `shares=None` 即 pending，行为已支持）。
- Produces: `Ledger.pending_lots(symbol=None) -> list[dict]`、`Ledger.fill_lot(lot_id: int, nav: float) -> float | None`（返回份额；非 pending 返回 None）；`position()` 输出新增键 `pending_lots`（list）。CLI：`watch buy` 的 `--nav` 变为可选（自动推确认日取净值），新增 `--order-time HH:MM` 与 `--confirm-date`；新增 `quantfox watch confirm <symbol>`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_lots.py` 追加：

```python
def test_pending_lot_excluded_from_cost(tmp_path):
    led = Ledger(tmp_path / "t.db")
    led.add_lot("002611", "otc_fund", 8000, 2.8357, "2026-07-07")
    led.add_lot("002611", "otc_fund", 12000, None, "2026-07-08", confirm_date="2026-07-09")  # 净值未出
    pos = led.position("002611")
    # 加权成本只算已确认那笔，pending 金额不得混入
    assert pos["total_amount"] == 8000
    assert pos["weighted_cost"] == 2.8357
    assert len(pos["pending_lots"]) == 1
    assert pos["pending_lots"][0]["confirm_date"] == "2026-07-09"


def test_fill_lot_confirms_pending(tmp_path):
    led = Ledger(tmp_path / "t.db")
    led.add_lot("002611", "otc_fund", 12000, None, "2026-07-08", confirm_date="2026-07-09")
    lot_id = led.pending_lots("002611")[0]["id"]
    shares = led.fill_lot(lot_id, 2.8219)
    assert abs(shares - round(15000 / 2.8219, 4)) < 0.001
    assert led.pending_lots("002611") == []
    pos = led.position("002611")
    assert pos["total_amount"] == 12000 and pos["weighted_cost"] == 2.8219


def test_fill_lot_ignores_confirmed(tmp_path):
    led = Ledger(tmp_path / "t.db")
    led.add_lot("002611", "otc_fund", 8000, 2.8357, "2026-07-07")
    lot_id = led.list_lots("002611")[0]["id"]
    assert led.fill_lot(lot_id, 9.9) is None  # 已确认的不允许改（成本不可被覆盖）
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_lots.py -v`
Expected: 新增 3 条 FAIL（`position` 无 `pending_lots` 键 / 无 `pending_lots` 方法）

- [ ] **Step 3: storage.py 实现**

`_recompute_holding` 中间三行：

```python
        tot_amt = sum(x["amount"] for x in lots if x["amount"])
        tot_sh = sum(x["shares"] for x in lots if x["shares"])
        wcost = round(tot_amt / tot_sh, 4) if tot_sh else None
```

改为（pending 不进成本）：

```python
        confirmed = [x for x in lots if x["shares"]]
        if not confirmed:
            return  # 全是 pending：净值未出，不动持仓成本
        tot_amt = sum(x["amount"] for x in confirmed if x["amount"])
        tot_sh = sum(x["shares"] for x in confirmed)
        wcost = round(tot_amt / tot_sh, 4) if tot_sh else None
        first = min(x["order_date"] for x in confirmed)
```

（并删掉原 `first = min(...)` 行，避免重复。）

`position` 的聚合部分：

```python
        tot_amt = round(sum(x["amount"] for x in lots if x["amount"]), 2)
        tot_sh = round(sum(x["shares"] for x in lots if x["shares"]), 4)
        wcost = round(tot_amt / tot_sh, 4) if tot_sh else None
        out = {"symbol": symbol, "lots": lots, "total_amount": tot_amt,
               "total_shares": tot_sh, "weighted_cost": wcost}
```

改为：

```python
        confirmed = [x for x in lots if x["shares"]]
        pending = [x for x in lots if not x["shares"]]
        tot_amt = round(sum(x["amount"] for x in confirmed if x["amount"]), 2)
        tot_sh = round(sum(x["shares"] for x in confirmed), 4)
        wcost = round(tot_amt / tot_sh, 4) if tot_sh else None
        out = {"symbol": symbol, "lots": lots, "total_amount": tot_amt,
               "total_shares": tot_sh, "weighted_cost": wcost, "pending_lots": pending}
        if pending:
            out["pending_note"] = f"{len(pending)} 笔净值未出（不计成本），出值后 quantfox watch confirm {symbol} 补记"
```

类内（`position` 之后）新增两个方法：

```python
    def pending_lots(self, symbol=None):
        c = self._conn()
        q = "SELECT * FROM lots WHERE shares IS NULL"
        args = []
        if symbol:
            q += " AND symbol=?"
            args.append(symbol)
        return [dict(r) for r in c.execute(q + " ORDER BY order_date, id", args).fetchall()]

    def fill_lot(self, lot_id, nav):
        """补记 pending lot：净值公布后回填份额。已确认的拒绝改（成本不可覆盖）。"""
        c = self._conn()
        row = c.execute("SELECT * FROM lots WHERE id=?", (lot_id,)).fetchone()
        if row is None or row["shares"] is not None:
            return None
        shares = round(row["amount"] / nav, 4)
        c.execute("UPDATE lots SET confirm_nav=?, shares=? WHERE id=?", (nav, shares, lot_id))
        c.commit()
        self._recompute_holding(row["symbol"], row["type"])
        return shares
```

- [ ] **Step 4: 跑 storage 测试**

Run: `python -m pytest tests/test_lots.py tests/test_storage.py -v`
Expected: 全 PASS

- [ ] **Step 5: cli.py 重写 watch buy + 新增 watch confirm**

`watch_buy` 整个函数替换为：

```python
@watch_app.command("buy")
def watch_buy(symbol: str,
              amount: float = typer.Option(None, help="买入金额（元）——按金额记一笔"),
              nav: float = typer.Option(None, help="确认净值（已知就直接给，跳过自动推算）"),
              entry_price: float = typer.Option(None, help="已知加权成本净值时用（单笔/直填成本）"),
              entry_date: str = typer.Option(None, help="下单日期 YYYY-MM-DD，默认今天"),
              order_time: str = typer.Option(None, help="下单时间 HH:MM（判断 15:00 cutoff；默认当前时间）"),
              confirm_date: str = typer.Option(None, help="手动指定净值确认日（日历不可用时兜底）")):
    """记一笔买入：--amount 自动按 15:00 cutoff 推确认日取净值；净值未出记 pending 待补。"""
    asset = resolve(symbol)
    entry_date = entry_date or _dt.date.today().isoformat()
    led = _ledger()
    if amount is not None:
        if nav is not None:  # 用户直接报 App 确认净值（最可信，优先）
            shares = led.add_lot(asset.symbol, asset.type, amount, nav, entry_date,
                                 confirm_date=confirm_date or entry_date)
            typer.echo(json.dumps({"holding": asset.symbol,
                                   "lot": {"amount": amount, "nav": nav, "shares": shares},
                                   "position": led.position(asset.symbol)}, ensure_ascii=False))
            return
        if confirm_date is None:  # 自动推净值确认日（15:00 cutoff + 交易日历）
            from .calendar_cn import nav_date_for_order, trade_dates

            t = _dt.time.fromisoformat(order_time) if order_time else _dt.datetime.now().time()
            try:
                confirm_date = nav_date_for_order(
                    _dt.datetime.combine(_dt.date.fromisoformat(entry_date), t), trade_dates())
            except RuntimeError as e:
                raise typer.BadParameter(str(e)) from e
        found = None
        try:
            prices = _prices_for(asset)
            hit = prices[prices["date"].astype(str).str[:10] == confirm_date]
            if len(hit):
                found = float(hit["value"].iloc[-1])
        except Exception as e:  # noqa
            typer.echo(f"# 取价失败: {e}", err=True)
        if found is not None:
            shares = led.add_lot(asset.symbol, asset.type, amount, found, entry_date,
                                 confirm_date=confirm_date)
            typer.echo(json.dumps({"holding": asset.symbol,
                                   "lot": {"amount": amount, "nav": found, "shares": shares,
                                           "confirm_date": confirm_date},
                                   "position": led.position(asset.symbol)}, ensure_ascii=False))
        else:
            led.add_lot(asset.symbol, asset.type, amount, None, entry_date, confirm_date=confirm_date)
            typer.echo(json.dumps({"holding": asset.symbol, "pending": True,
                                   "confirm_date": confirm_date,
                                   "note": f"确认日 {confirm_date} 净值未公布；出值后跑 "
                                           f"quantfox watch confirm {asset.symbol} 自动补记"},
                                  ensure_ascii=False))
    elif entry_price is not None:
        led.mark_bought(asset.symbol, asset.type, entry_price, entry_date)
        typer.echo(json.dumps({"holding": asset.symbol, "entry_price": entry_price,
                               "entry_date": entry_date}, ensure_ascii=False))
    else:
        raise typer.BadParameter("给 --amount（自动推确认日/净值，或配 --nav 直填），或 --entry-price")
```

紧随其后新增：

```python
@watch_app.command("confirm")
def watch_confirm(symbol: str):
    """补记 pending lots：确认日净值公布后自动回填份额与成本。"""
    asset = resolve(symbol)
    led = _ledger()
    pend = led.pending_lots(asset.symbol)
    if not pend:
        typer.echo(json.dumps({"symbol": asset.symbol, "filled": [], "note": "无 pending 笔"},
                              ensure_ascii=False))
        return
    prices = _prices_for(asset)
    dates = prices["date"].astype(str).str[:10]
    filled, still = [], []
    for lot in pend:
        hit = prices[dates == lot["confirm_date"]]
        if len(hit):
            shares = led.fill_lot(lot["id"], float(hit["value"].iloc[-1]))
            filled.append({"id": lot["id"], "confirm_date": lot["confirm_date"], "shares": shares})
        else:
            still.append({"id": lot["id"], "confirm_date": lot["confirm_date"], "note": "净值仍未出"})
    typer.echo(json.dumps({"symbol": asset.symbol, "filled": filled, "pending": still,
                           "position": led.position(asset.symbol)}, ensure_ascii=False, indent=2))
```

- [ ] **Step 6: 全量测试**

Run: `python -m pytest -q`
Expected: 全绿

- [ ] **Step 7: Commit**

```bash
git add quantfox/storage.py quantfox/cli.py tests/test_lots.py
git commit -m "feat(watch): auto T+1 nav-date on buy, pending lots excluded from cost, watch confirm backfill

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: reconciliations 留痕表 + watch expect / reconcile

**Files:**
- Modify: `quantfox/storage.py`（建表 + `add_reconciliation`/`reconciliations_for`/`latest_reconciliation`/`daily_expectation` + 模块级 `classify_delta`）
- Modify: `quantfox/cli.py`（新增 `watch expect`、`watch reconcile`；`watch position` 尾部带最近对账）
- Test: `tests/test_reconcile.py`（新建）

**Interfaces:**
- Consumes: lots 表（Task 4 语义：`shares IS NULL` = pending）。
- Produces: `storage.classify_delta(delta: float) -> str`（`ok`≤0.05 < `rounding`≤0.5 < `mismatch`）；`Ledger.daily_expectation(symbol, prices: pd.DataFrame) -> dict | None`（键 `symbol/trade_date/prev_date/expected_daily_pnl/expected_total_pnl/shares_counted`）；`Ledger.add_reconciliation(**kw) -> int`；`Ledger.reconciliations_for(symbol, trade_date=None) -> list[dict]`；`Ledger.latest_reconciliation(symbol) -> dict | None`。CLI：`quantfox watch expect [symbol]`、`quantfox watch reconcile <symbol> --app-profit X [--date D]`。

**口径（对齐 App，来自 002611 实战）**：t 日预期当日收益只算 `confirm_date < t`（严格早于，确认当日不计当日盈亏）的已确认份额 × (nav_t − nav_{t−1})；累计浮盈亏 = 已确认份额 × nav_t − 已确认投入金额（pending 不计）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_reconcile.py`：

```python
import pandas as pd

from quantfox.storage import Ledger, classify_delta

PRICES = pd.DataFrame({
    "date": ["2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10"],
    "value": [2.8357, 2.8313, 2.8219, 2.8190],
})


def _ledger_002611(tmp_path):
    led = Ledger(tmp_path / "t.db")
    led.add_lot("002611", "otc_fund", 8000, 2.8357, "2026-07-07", confirm_date="2026-07-07")
    led.add_lot("002611", "otc_fund", 12000, 2.8219, "2026-07-08", confirm_date="2026-07-09")
    return led


def test_daily_expectation_matches_app(tmp_path):
    led = _ledger_002611(tmp_path)
    exp = led.daily_expectation("002611", PRICES)
    assert exp["trade_date"] == "2026-07-10" and exp["prev_date"] == "2026-07-09"
    # 7/10 两笔都已确认（7/7、7/9 均 < 7/10）
    assert abs(exp["expected_daily_pnl"] - (-20.51)) < 0.05
    # 累计 = 份额×nav_t − 投入
    assert abs(exp["expected_total_pnl"] - (-59.45)) < 0.5


def test_confirm_day_shares_not_counted(tmp_path):
    led = _ledger_002611(tmp_path)
    # 只看到 7/9 为止的净值：第二笔当日刚确认，不计当日盈亏 → 只算第一笔
    exp = led.daily_expectation("002611", PRICES.iloc[:3])
    shares_1w = round(8000 / 2.8357, 4)
    assert abs(exp["expected_daily_pnl"] - round(shares_1w * (2.8219 - 2.8313), 2)) < 0.02
    assert exp["shares_counted"] == shares_1w


def test_expectation_none_without_lots_or_prices(tmp_path):
    led = Ledger(tmp_path / "t.db")
    assert led.daily_expectation("002611", PRICES) is None  # 无 lots
    led.add_lot("002611", "otc_fund", 8000, 2.8357, "2026-07-07")
    assert led.daily_expectation("002611", PRICES.iloc[:1]) is None  # 不足两天净值


def test_reconciliation_append_and_latest(tmp_path):
    led = _ledger_002611(tmp_path)
    led.add_reconciliation(symbol="002611", trade_date="2026-07-10",
                           expected_daily_pnl=-20.51, expected_total_pnl=-59.45, verdict="pending")
    led.add_reconciliation(symbol="002611", trade_date="2026-07-10",
                           expected_daily_pnl=-20.51, app_daily_pnl=-20.47,
                           delta=0.04, verdict="ok")
    rows = led.reconciliations_for("002611", trade_date="2026-07-10")
    assert len(rows) == 2  # append-only：两条都在
    assert led.latest_reconciliation("002611")["verdict"] == "ok"


def test_classify_delta_bands():
    assert classify_delta(0.04) == "ok"
    assert classify_delta(-0.05) == "ok"
    assert classify_delta(0.3) == "rounding"
    assert classify_delta(-2.0) == "mismatch"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_reconcile.py -v`
Expected: FAIL（`ImportError: classify_delta`）

- [ ] **Step 3: storage.py 实现**

建表 SQL：`__init__` 的 `executescript` 里 lots 表后追加：

```sql
            CREATE TABLE IF NOT EXISTS reconciliations (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              symbol TEXT NOT NULL,
              trade_date TEXT NOT NULL,
              expected_daily_pnl REAL,
              app_daily_pnl REAL,
              delta REAL,
              expected_total_pnl REAL,
              verdict TEXT,
              note TEXT,
              created_at TEXT NOT NULL
            );
```

模块级函数（`round_trip_cost` 之后）：

```python
def classify_delta(delta: float) -> str:
    """对账判定：|delta|≤0.05 元四舍五入误差；≤0.5 元口径小差；再大就是真不对。"""
    a = abs(delta)
    if a <= 0.05:
        return "ok"
    if a <= 0.5:
        return "rounding"
    return "mismatch"
```

Ledger 类内（`calibration` 之后）新增：

```python
    # --- 对账留痕（append-only）：预期收益/对账结论必须落库，不许只留在对话里 ---
    def daily_expectation(self, symbol, prices: pd.DataFrame):
        """t 日预期当日收益 = confirm_date < t 的已确认份额 × (nav_t − nav_{t−1})（对齐 App 口径：
        确认当日不计当日盈亏）。累计浮盈亏只算已确认笔。"""
        lots = [x for x in self.list_lots(symbol) if x["shares"]]
        if not lots or prices is None or len(prices) < 2:
            return None
        s = prices.reset_index(drop=True)
        dates = s["date"].astype(str).str[:10]
        t, prev = dates.iloc[-1], dates.iloc[-2]
        nav_t, nav_prev = float(s["value"].iloc[-1]), float(s["value"].iloc[-2])
        counted = round(sum(x["shares"] for x in lots if (x["confirm_date"] or "") < t), 4)
        all_sh = round(sum(x["shares"] for x in lots), 4)
        invested = round(sum(x["amount"] for x in lots if x["amount"]), 2)
        return {"symbol": symbol, "trade_date": t, "prev_date": prev,
                "expected_daily_pnl": round(counted * (nav_t - nav_prev), 2),
                "expected_total_pnl": round(all_sh * nav_t - invested, 2),
                "shares_counted": counted}

    def add_reconciliation(self, *, symbol, trade_date, expected_daily_pnl=None,
                           app_daily_pnl=None, delta=None, expected_total_pnl=None,
                           verdict="pending", note=""):
        c = self._conn()
        cur = c.execute(
            "INSERT INTO reconciliations (symbol,trade_date,expected_daily_pnl,app_daily_pnl,"
            "delta,expected_total_pnl,verdict,note,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (symbol, trade_date, expected_daily_pnl, app_daily_pnl, delta,
             expected_total_pnl, verdict, note, datetime.now(timezone.utc).isoformat()))
        c.commit()
        return cur.lastrowid

    def reconciliations_for(self, symbol, trade_date=None):
        c = self._conn()
        q = "SELECT * FROM reconciliations WHERE symbol=?"
        args = [symbol]
        if trade_date:
            q += " AND trade_date=?"
            args.append(trade_date)
        return [dict(r) for r in c.execute(q + " ORDER BY id", args).fetchall()]

    def latest_reconciliation(self, symbol):
        c = self._conn()
        r = c.execute("SELECT * FROM reconciliations WHERE symbol=? ORDER BY id DESC LIMIT 1",
                      (symbol,)).fetchone()
        return dict(r) if r else None
```

- [ ] **Step 4: 跑测试**

Run: `python -m pytest tests/test_reconcile.py tests/test_storage.py -v`
Expected: 全 PASS

- [ ] **Step 5: CLI — watch expect / reconcile / position 尾注**

`quantfox/cli.py` 在 `watch_confirm` 之后新增：

```python
@watch_app.command("expect")
def watch_expect(symbol: str = typer.Argument(None)):
    """当日预期收益（落库留痕）：按最新净值与已确认份额算预期，写入 reconciliations。"""
    led = _ledger()
    if symbol:
        symbols = [resolve(symbol).symbol]
    else:
        symbols = [h["symbol"] for h in led.list_holdings() if h["status"] == "holding"]
    out = []
    for sym in symbols:
        try:
            prices = _prices_for(resolve(sym))
        except Exception as e:  # noqa
            out.append({"symbol": sym, "error": f"取价失败: {e}"})
            continue
        exp = led.daily_expectation(sym, prices)
        if exp is None:
            out.append({"symbol": sym, "note": "无已确认分笔或净值不足两天，算不了预期"})
            continue
        led.add_reconciliation(symbol=sym, trade_date=exp["trade_date"],
                               expected_daily_pnl=exp["expected_daily_pnl"],
                               expected_total_pnl=exp["expected_total_pnl"], verdict="pending")
        out.append({**exp, "note": "已落库；拿到 App 实际数后跑 watch reconcile 比对"})
    typer.echo(json.dumps(out, ensure_ascii=False, indent=2))


@watch_app.command("reconcile")
def watch_reconcile(symbol: str,
                    app_profit: float = typer.Option(..., "--app-profit", help="App 显示的当日收益（元，亏为负）"),
                    date: str = typer.Option(None, help="净值日 YYYY-MM-DD，默认最新")):
    """与 App 对账：比对预期与实际当日收益，判定 ok/rounding/mismatch 并落库。"""
    from .storage import classify_delta

    asset = resolve(symbol)
    led = _ledger()
    prices = _prices_for(asset)
    exp = led.daily_expectation(asset.symbol, prices)
    if exp is None:
        typer.echo(json.dumps({"symbol": asset.symbol, "error": "无已确认分笔或净值不足，先记账"},
                              ensure_ascii=False))
        raise typer.Exit(1)
    if date and date != exp["trade_date"]:
        rows = [r for r in led.reconciliations_for(asset.symbol, trade_date=date)
                if r["expected_daily_pnl"] is not None]
        if not rows:
            typer.echo(json.dumps({"symbol": asset.symbol, "error": f"{date} 无预期记录，只能对最新净值日 {exp['trade_date']}"},
                                  ensure_ascii=False))
            raise typer.Exit(1)
        exp = {"symbol": asset.symbol, "trade_date": date,
               "expected_daily_pnl": rows[-1]["expected_daily_pnl"],
               "expected_total_pnl": rows[-1]["expected_total_pnl"]}
    delta = round(app_profit - exp["expected_daily_pnl"], 2)
    verdict = classify_delta(delta)
    note = "" if verdict == "ok" else (
        "四舍五入级差异，可接受" if verdict == "rounding"
        else "对不上：排查确认日(T/T+1)、份额、费率口径；把 App 成本净值报给我重新对齐")
    led.add_reconciliation(symbol=asset.symbol, trade_date=exp["trade_date"],
                           expected_daily_pnl=exp["expected_daily_pnl"], app_daily_pnl=app_profit,
                           delta=delta, expected_total_pnl=exp.get("expected_total_pnl"),
                           verdict=verdict, note=note)
    typer.echo(json.dumps({"symbol": asset.symbol, "trade_date": exp["trade_date"],
                           "expected": exp["expected_daily_pnl"], "app": app_profit,
                           "delta": delta, "verdict": verdict, "note": note},
                          ensure_ascii=False, indent=2))
```

`watch_position` 输出前（`typer.echo(json.dumps(pos, ...))` 之前）加：

```python
    rec = led.latest_reconciliation(asset.symbol)
    if rec:
        pos["last_reconcile"] = {"trade_date": rec["trade_date"], "verdict": rec["verdict"],
                                 "delta": rec["delta"]}
```

- [ ] **Step 6: 全量测试**

Run: `python -m pytest -q`
Expected: 全绿

- [ ] **Step 7: Commit**

```bash
git add quantfox/storage.py quantfox/cli.py tests/test_reconcile.py
git commit -m "feat(reconcile): append-only reconciliations ledger + watch expect/reconcile, position shows last verdict

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: 分析框架 v14（诚实铁律 + 产物与留痕铁律统一出处）

**Files:**
- Modify: `quantfox/prompts/analysis_framework.md`
- Test: `tests/test_framework.py`（追加 1 条）

**Interfaces:**
- Produces: 框架 v14 文本；`framework_version()` 返回 `"14"`。Task 7 的 SKILL.md 引用段以本节标题为锚。

- [ ] **Step 1: 写失败测试**

在 `tests/test_framework.py` 末尾追加：

```python
def test_framework_v14_iron_rules():
    from quantfox.prompts import framework_path, framework_version

    assert framework_version() == "14"
    text = framework_path().read_text(encoding="utf-8")
    for kw in ("诚实铁律", "产物与留痕铁律", "from_similar_valuation", "QUANTFOX_HOME",
               "watch expect", "mandate show", "幸存者偏差"):
        assert kw in text, f"框架缺关键词: {kw}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_framework.py -v`
Expected: 新增条 FAIL（version 仍是 13）

- [ ] **Step 3: 编辑框架**

`quantfox/prompts/analysis_framework.md`：
1. 首行 `<!-- version: 13 -->` → `<!-- version: 14 -->`。
2. 在「第一优先级：保本优先」一节之后、「定位与目标口径」之前插入：

```markdown
## 诚实铁律（唯一出处：各 skill 引用本节，不各写各的）
1. **看中位不看均值**：任何收益分布（forecast/回测/历史区间）以**中位数**为"典型结局"；均值被牛市尾部拉高，禁止拿均值当预期收益讲给用户。
2. **估值闸门**：估值分位 > 0.85 一律剔除或降级——深筛分/动能分是**相对分 ≠ 能买**；结论必须区分"相对分"与"绝对估值位"。
3. **幸存者偏差**：榜单/回测/深筛顶部天然虚高，过去 ≠ 未来；凡涉及排名与回测的结论必须带这条风险提示。
4. **前瞻必须条件化**：估值分位 > 0.85 时以 `quantfox forecast` 的 `from_similar_valuation`（从当前估值位买入的历史下场）为准；样本不足（无条件 <60 / 条件 <30）时明说"别当真"。

## 产物与留痕铁律
- **落盘**：任何报告/导出/中间产物一律写 `QUANTFOX_HOME`（默认 `~/.quantfox/`，报告在 `reports/`），**绝不写进代码仓库目录**。
- **留痕**：对话中给出的任何"预期收益 / 对账结论"必须通过 `quantfox watch expect` / `quantfox watch reconcile` 落库（append-only），不允许只留在对话里——会话会关，账本不会。
- **个性化**：分析前先 `quantfox mandate show` 读用户档案；有档案 → 仓位/金额建议必须受单标的与主题上限约束、结论对齐用户目标与期限；无档案 → 一句话提示可用 `quantfox mandate set` 建立，**不阻断**分析。
```

- [ ] **Step 4: 跑测试**

Run: `python -m pytest tests/test_framework.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add quantfox/prompts/analysis_framework.md tests/test_framework.py
git commit -m "feat(framework): v14 — consolidated honesty iron rules + artifact/ledger discipline as single source

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: 七 SKILL.md 同步（引用铁律 + mandate 第 0 步 + 补 forecast）

**Files:**
- Modify: `skills/fund-analyze/SKILL.md`、`skills/fund-screener/SKILL.md`、`skills/fund-compare/SKILL.md`、`skills/fund-watch/SKILL.md`、`skills/position-sizer/SKILL.md`、`skills/portfolio-manager/SKILL.md`、`skills/signal-postmortem/SKILL.md`
- Test: `tests/test_skill_file.py`（追加 2 条）

**Interfaces:**
- Consumes: 框架 v14 两节标题（Task 6）；`quantfox mandate show`（Task 2）；`watch expect/reconcile/confirm`（Task 4/5）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_skill_file.py` 末尾追加：

```python
def test_honesty_matrix_all_skills():
    # 7 skill × 铁律关键词全覆盖（grep 矩阵验收，spec §3）
    keywords = ["中位", "0.85", "幸存者偏差", "from_similar_valuation", "QUANTFOX_HOME", "mandate"]
    for name in EXPECTED:
        text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
        for kw in keywords:
            assert kw in text, f"{name}/SKILL.md 缺铁律关键词: {kw}"


def test_forecast_step_in_analysis_skills():
    # 涉及"要不要买/持有"判断的 skill 必须有前瞻步骤
    for name in ("fund-analyze", "fund-screener", "fund-watch", "fund-compare", "portfolio-manager"):
        text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
        assert "quantfox forecast" in text, f"{name}/SKILL.md 缺 quantfox forecast 步骤"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_skill_file.py -v`
Expected: 新增 2 条 FAIL

- [ ] **Step 3: 每个 SKILL.md 插入统一段落**

对 7 个 SKILL.md，在正文第一个 `##` 小节之前（frontmatter 与标题之后）插入同一段：

```markdown
## 诚实铁律 + 档案 + 留痕（出处：quantfox/prompts/analysis_framework.md v14，以框架为准）
- **看中位不看均值**；估值分位 **>0.85 过闸门**（剔除/降级，相对分≠能买）；涉及排名/回测必提**幸存者偏差**；高位前瞻以 `from_similar_valuation` 为准，样本不足明说别当真。
- **第 0 步先 `quantfox mandate show`**：有档案 → 金额/仓位建议受单标的与主题上限约束，结论对齐用户目标与期限；无档案 → 一句话提示可 `quantfox mandate set` 建立，不阻断。
- **产物落 `QUANTFOX_HOME`**（默认 `~/.quantfox/`），绝不写进代码仓库；对话里的预期收益/对账结论用 `quantfox watch expect` / `watch reconcile` 落库，不许只留在对话里。
```

- [ ] **Step 4: 三个 skill 补 forecast 步骤**

- `skills/fund-watch/SKILL.md`：在巡检/检查步骤（`watch check` 出现处）之后加一步：

```markdown
- **持仓前瞻赔率**（对"要不要继续拿/加仓"给数据）：对每只 holding 跑 `quantfox forecast <代码>`，读"从当前位置持有 20/60/120 日"的正收益概率与**中位**；估值分位 >0.85 以 `from_similar_valuation` 为准。中位明显转负或高位条件化赔率大幅恶化 → 在摘要里点名提示，而不是等跌破止损线才说话。
```

- `skills/fund-compare/SKILL.md`：在对比维度清单处加：

```markdown
- **前瞻分布对比**：逐只跑 `quantfox forecast <代码>`，对比中位（不是均值）与正收益概率；估值分位 >0.85 的用 `from_similar_valuation` 口径对比，别拿山顶上的无条件数字比山脚的。
```

- `skills/portfolio-manager/SKILL.md`：在组合体检步骤处加：

```markdown
- **逐持仓前瞻汇总**：对每只持仓跑 `quantfox forecast <代码>`，汇总"组合里每只从当前位置的中位赔率"；高位（分位>0.85）持仓用 `from_similar_valuation`。全组合中位赔率恶化是减仓信号之一。
```

（若该 skill 已有 forecast 字样则只补缺的口径描述，不重复。）

- [ ] **Step 5: 跑测试**

Run: `python -m pytest tests/test_skill_file.py -v`
Expected: 全 PASS

- [ ] **Step 6: 复查 + 全量测试**

Run: `for f in skills/*/SKILL.md; do echo "== $f"; grep -c "诚实铁律" $f; done && python -m pytest -q`
Expected: 每个文件计数 ≥1；pytest 全绿

- [ ] **Step 7: Commit**

```bash
git add skills/ tests/test_skill_file.py
git commit -m "feat(skills): sync honesty iron rules, mandate step-0, artifact/ledger discipline across all 7 skills; add forecast steps to watch/compare/portfolio

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: 仓库清理 + 遗留稿归档

**Files:**
- Modify: `.gitignore`
- Move: `output/*` → `~/.quantfox/reports/audit/`（仓库外，不入库）
- Move: `docs/superpowers/specs/2026-07-10-quantfox-trustworthy-decision-core-design.md` → `docs/reference/trustworthy-decision-core.md`（未跟踪文件，普通 mv 后 git add）

**Interfaces:** 无代码接口；产出干净的 `git status`。

- [ ] **Step 1: 移走 audit 报告（移动不删除）**

```bash
mkdir -p ~/.quantfox/reports/audit
mv output/pdf/*.pdf output/reports/*.md ~/.quantfox/reports/audit/
rmdir output/pdf output/reports output
ls ~/.quantfox/reports/audit/
```

Expected: 4 个文件列出；仓库无 `output/`。

- [ ] **Step 2: .gitignore 追加**

在 `.gitignore` 的 `# Python` 段之后追加：

```
# quantfox 运行产物与代理沙箱（产物一律在 ~/.quantfox，见 analysis_framework.md）
/output/
.gitwarp/
```

- [ ] **Step 3: 归档遗留稿**

```bash
mkdir -p docs/reference
mv docs/superpowers/specs/2026-07-10-quantfox-trustworthy-decision-core-design.md docs/reference/trustworthy-decision-core.md
```

然后在 `docs/reference/trustworthy-decision-core.md` 标题行之后插入：

```markdown
> **定位：北极星参考，非实施规格。** 按期摘取有回报的部分（P1 已摘 InvestorMandate-lite 字段与"结论落库留痕/数据失败不得报正常"思想）；预注册验证协议、内容哈希、canonical JSON 等企业级机制不落地。路线图见 `docs/superpowers/specs/2026-07-10-quantfox-p1-consistency-mandate-design.md` §0。
```

- [ ] **Step 4: 验证 + Commit**

```bash
git status --short
git add .gitignore docs/reference/
git commit -m "chore: archive trustworthy-decision-core as north-star reference; gitignore output/ and .gitwarp/

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git status --short
```

Expected: 提交后 `git status --short` 输出为空（`.gitwarp/` 已被忽略）。

---

### Task 9: 端到端验收 + 状态文件更新

**Files:**
- Modify: `docs/task.md`（勾掉/追加条目）、`docs/HANDOFF-2026-07-10.md`（可选：顶部加一行"已由 P1 接续"）

**Interfaces:** 消费前面全部任务。

- [ ] **Step 1: 全量测试**

Run: `python -m pytest -q`
Expected: 全绿（约 78 + 新增 ≈ 20+ 条）。把总数贴进收尾报告。

- [ ] **Step 2: grep 矩阵终验**

```bash
for kw in 中位 0.85 幸存者偏差 from_similar_valuation QUANTFOX_HOME mandate; do
  echo "== $kw"; grep -L "$kw" skills/*/SKILL.md || echo "（全覆盖）"
done
```

Expected: 每个关键词下输出 `（全覆盖）`。

- [ ] **Step 3: 真实数据冒烟（需网络，尽力而为）**

```bash
quantfox mandate show
quantfox watch position 002611
quantfox watch expect 002611
```

Expected: position 显示两笔 lot + 加权成本；expect 输出当日预期并提示已落库。网络失败则明说"冒烟未跑成 + 原因"，不得假称通过。
（注意：这是用户真实账本 `~/.quantfox/ledger.db`，**只读命令 + expect 落一条 pending 记录**，不做任何删改。）

- [ ] **Step 4: 更新 docs/task.md**

在「后续（未开始）」上方追加一段（日期用实际完成日）：

```markdown
- [x] **P1 一致性+全局统一+mandate+对账留痕**（2026-07-10，spec/plan 见 docs/superpowers/）：
  config.json 统一配置（email.json 自动迁移、0700/0600 权限）；mandate-lite（`quantfox mandate set/show`，7 skill 第0步）；
  框架 v14 诚实铁律唯一出处 + 7 skill 同步 + grep 矩阵测试；交易日历 15:00 cutoff 自动确认日、pending lot、
  `watch confirm/expect/reconcile` + append-only reconciliations 留痕；output/ 清理入 ~/.quantfox，遗留稿归档 docs/reference。
```

并把「后续（未开始）」里 A2/price_ref_date 相关行改为完成或指向本条。

- [ ] **Step 5: Commit + 收尾报告**

```bash
git add docs/task.md docs/HANDOFF-2026-07-10.md
git commit -m "docs: mark P1 done in task ledger

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

收尾必报：做了什么 / 关键改动 / 跑了什么验证（贴 pytest 总数与 grep 矩阵输出）/ 还有什么没验（如网络冒烟）。

---

## Self-Review 记录

- **Spec 覆盖**：§1 全局家目录 → Task 1/8；§2 mandate → Task 2 + Task 7 第 0 步；§3 一致性 → Task 6/7；§4 T+1+留痕 → Task 3/4/5；§5 归档 → Task 8；§7 验收 → 各 task 测试 + Task 9。spec §1"logs/ 只建约定"——体现在框架文案，不写代码，符合。
- **类型一致**：`daily_expectation` 返回键与 Task 5 CLI 消费一致；`classify_delta` 阈值与 spec（0.05/0.5）一致；`nav_date_for_order(order_at, dates)` 两处调用签名一致；`add_lot(..., confirm_date=)` 与现有 storage 签名一致。
- **无占位符**：所有代码/命令/文案完整给出。
