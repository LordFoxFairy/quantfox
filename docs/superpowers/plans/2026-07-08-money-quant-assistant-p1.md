# money 量化分析助手 P1 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个 Python CLI（`quantfox`）+ Claude Code Skill（`fund-analyze`），对场外基金与黄金取数、算指标、收集舆情、组装"证据卡"，由 Claude 综合推理出可解释信号，并把每次预测存档以便复盘评估。

**Architecture:** 一条缝 + 两契约。CLI（确定层）只产出客观数据的"证据卡"JSON；Skill（判断层 = Claude）只依赖证据卡 schema 做推理。两个共享契约：证据卡（pydantic）与分析框架（markdown）。预测账本 append-only，outcome 可复算，杜绝自欺。

**Tech Stack:** Python 3.13、uv、typer（CLI）、pydantic（schema）、pandas + akshare（数据）、pandas-ta（指标）、SQLite（stdlib，预测账本）、pytest（测试）。

## Global Constraints

- Python 版本：>= 3.11（本机 3.13.5）。
- 包管理：uv；项目名 `quantfox`，导入名 `quantfox`。
- 资产范围：仅"场外基金（otc_fund）"与"黄金（gold）"。
- 数据源：akshare，免费无 key。数据层测试一律用**离线 fixtures**，禁止在单测里打实时网络。
- CLI 永不下投资结论；判断/舆情鉴别全部交给 Skill（Claude）。
- 证据卡缺失字段显式 `null` + `data_quality` 说明，禁止静默补空。
- 预测账本 append-only，历史预测不可篡改；outcome 为纯函数可复算。
- 所有金额/比率用 float；日期用 `YYYY-MM-DD` 字符串。
- 频繁提交：每个任务至少一个 commit。

---

### Task 0: 项目脚手架（uv + pytest）

**Files:**
- Modify: `pyproject.toml`
- Create: `money/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`
- Create: `.gitignore`（追加 Python 忽略项）
- Delete: `src/index.ts`, `tsconfig.json`（旧 TS 脚手架）

**Interfaces:**
- Produces: 可用的 `uv run pytest`；导入包 `quantfox`（暴露 `__version__`）。

- [ ] **Step 1: 用 uv 初始化并写 pyproject**

替换 `pyproject.toml` 为：

```toml
[project]
name = "quantfox"
version = "0.1.0"
description = "场外基金与黄金的量化证据卡 + Claude 决策助手"
requires-python = ">=3.11"
dependencies = [
  "typer>=0.12",
  "pydantic>=2.7",
  "pandas>=2.2",
  "akshare>=1.14",
  "pandas-ta>=0.3.14b0",
]

[project.scripts]
money = "money.cli:app"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["money"]
```

- [ ] **Step 2: 建包与冒烟测试**

`money/__init__.py`:
```python
__version__ = "0.1.0"
```

`tests/__init__.py`: 空文件。

`tests/test_smoke.py`:
```python
import money


def test_version():
    assert money.__version__ == "0.1.0"
```

- [ ] **Step 3: 同步依赖并跑测试**

Run: `uv sync && uv run pytest tests/test_smoke.py -v`
Expected: PASS（1 passed）。若 akshare 在 3.13 装不上，降级到 `requires-python=">=3.11,<3.13"` 并用 `uv python pin 3.12`，重跑。

- [ ] **Step 4: 清理旧 TS 脚手架**

删除 `src/index.ts`、`tsconfig.json`。`.gitignore` 追加：
```
.venv/
__pycache__/
*.pyc
.pytest_cache/
data/
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml money tests .gitignore
git rm src/index.ts tsconfig.json
git commit -m "chore: bootstrap python project with uv, remove ts scaffold"
```

---

### Task 1: akshare 接口探针（spike，产出 fixtures）

**目的：** akshare 接口会变，必须用真实调用钉死函数名与返回结构，并保存离线样本供后续数据层测试。这是唯一允许打网络的步骤，且只在开发期手动跑。

**Files:**
- Create: `scripts/probe_akshare.py`
- Create: `tests/fixtures/fund_nav_sample.json`（探针产出）
- Create: `tests/fixtures/gold_sample.json`（探针产出）
- Create: `tests/fixtures/news_sample.json`（探针产出）
- Create: `docs/akshare-interfaces.md`（钉死的接口清单）

**Interfaces:**
- Produces: 三个 fixtures + `docs/akshare-interfaces.md` 记录：基金历史净值函数名、黄金价格函数名、财经新闻函数名，及各自列名。

- [ ] **Step 1: 写探针脚本**

`scripts/probe_akshare.py`（探测多个候选接口，打印列名与前几行，把成功的存成 fixture）：
```python
"""开发期手动运行，探测并钉死 akshare 接口，产出离线 fixtures。"""
import json
from pathlib import Path
import akshare as ak

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
OUT.mkdir(parents=True, exist_ok=True)


def dump(name, df, rows=120):
    print(f"\n=== {name} ===")
    print("columns:", list(df.columns))
    print(df.head(3).to_string())
    (OUT / f"{name}.json").write_text(
        df.tail(rows).to_json(orient="records", force_ascii=False), encoding="utf-8"
    )


# 场外基金历史净值（候选：fund_open_fund_info_em）
df = ak.fund_open_fund_info_em(symbol="501018", indicator="单位净值走势")
dump("fund_nav_sample", df)

# 黄金 Au99.99（候选：spot_hist_sge）
g = ak.spot_hist_sge(symbol="Au99.99")
dump("gold_sample", g)

# 财经新闻（候选：stock_news_em 或 news_cctv 等，择一可用）
try:
    n = ak.stock_news_em(symbol="黄金")
    dump("news_sample", n, rows=30)
except Exception as e:  # noqa
    print("news probe failed:", e)
```

- [ ] **Step 2: 运行探针**

Run: `uv run python scripts/probe_akshare.py`
Expected: 打印三段 columns，`tests/fixtures/*.json` 生成。若某接口名报错 `AttributeError`，在 akshare 文档/dir 里找同义函数替换后重跑。

- [ ] **Step 3: 记录接口清单**

把实测的**函数名 + 参数 + 返回列名**写入 `docs/akshare-interfaces.md`（后续数据层严格按此写）。

- [ ] **Step 4: Commit**

```bash
git add scripts/probe_akshare.py tests/fixtures docs/akshare-interfaces.md
git commit -m "spike: pin akshare interfaces and capture offline fixtures"
```

---

### Task 2: 资产解析 resolve.py

**Files:**
- Create: `money/data/__init__.py`
- Create: `money/data/resolve.py`
- Test: `tests/test_resolve.py`

**Interfaces:**
- Produces:
  - `class Asset(pydantic.BaseModel)`: 字段 `symbol:str`, `name:str|None`, `type:Literal["otc_fund","gold"]`。
  - `resolve(query:str) -> Asset`：`"gold"/"黄金"/"au99.99"`（不分大小写）→ type=gold，symbol 归一化为 `"Au99.99"`；6 位数字 → otc_fund。无法识别抛 `ValueError`。

- [ ] **Step 1: 写失败测试**

`tests/test_resolve.py`:
```python
import pytest
from money.data.resolve import resolve, Asset


def test_gold_aliases():
    for q in ["gold", "黄金", "AU99.99", "au99.99"]:
        a = resolve(q)
        assert a.type == "gold"
        assert a.symbol == "Au99.99"


def test_fund_code():
    a = resolve("501018")
    assert a.type == "otc_fund"
    assert a.symbol == "501018"


def test_unknown_raises():
    with pytest.raises(ValueError):
        resolve("banana")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_resolve.py -v`
Expected: FAIL（ModuleNotFoundError）。

- [ ] **Step 3: 实现**

`money/data/__init__.py`: 空。
`money/data/resolve.py`:
```python
import re
from typing import Literal, Optional
from pydantic import BaseModel

AssetType = Literal["otc_fund", "gold"]
_GOLD = {"gold", "黄金", "au99.99", "au9999"}


class Asset(BaseModel):
    symbol: str
    name: Optional[str] = None
    type: AssetType


def resolve(query: str) -> Asset:
    q = query.strip()
    if q.lower() in _GOLD:
        return Asset(symbol="Au99.99", type="gold", name="黄金Au99.99")
    if re.fullmatch(r"\d{6}", q):
        return Asset(symbol=q, type="otc_fund")
    raise ValueError(f"无法识别的标的: {query!r}（支持 6 位基金代码或 '黄金'/'gold'）")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_resolve.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: Commit**

```bash
git add money/data/resolve.py money/data/__init__.py tests/test_resolve.py
git commit -m "feat: asset resolver for otc funds and gold"
```

---

### Task 3: 数据层 funds.py + gold.py（含 fixture 注入）

**Files:**
- Create: `money/data/prices.py`
- Test: `tests/test_prices.py`

**Interfaces:**
- Consumes: `Asset`（Task 2）；fixtures（Task 1）。
- Produces:
  - `load_prices(asset:Asset, fetcher=None) -> pandas.DataFrame`：返回列 `["date","value"]`（date 升序、value=float），`date` 为 `YYYY-MM-DD` 字符串。
  - `fetcher` 参数用于依赖注入：默认走 akshare；测试传入返回 fixture DataFrame 的假 fetcher。
  - 归一化函数 `_normalize_fund(df)`、`_normalize_gold(df)` 把 akshare 原始列映射到 `date/value`（列名以 Task 1 实测为准；下方按常见列名写，若探针结果不同，改这里）。

- [ ] **Step 1: 写失败测试（用 fixtures，不打网络）**

`tests/test_prices.py`:
```python
import json
from pathlib import Path
import pandas as pd
from money.data.resolve import Asset
from money.data.prices import load_prices

FX = Path(__file__).parent / "fixtures"


def _fund_fetcher(asset):
    return pd.read_json(FX / "fund_nav_sample.json")


def _gold_fetcher(asset):
    return pd.read_json(FX / "gold_sample.json")


def test_load_fund_prices_shape():
    a = Asset(symbol="501018", type="otc_fund")
    df = load_prices(a, fetcher=_fund_fetcher)
    assert list(df.columns) == ["date", "value"]
    assert df["date"].is_monotonic_increasing
    assert df["value"].dtype == float
    assert len(df) > 0


def test_load_gold_prices_shape():
    a = Asset(symbol="Au99.99", type="gold")
    df = load_prices(a, fetcher=_gold_fetcher)
    assert list(df.columns) == ["date", "value"]
    assert df["value"].dtype == float
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_prices.py -v`
Expected: FAIL（ImportError）。

- [ ] **Step 3: 实现（列名按 Task 1 docs 校正）**

`money/data/prices.py`:
```python
import pandas as pd
from .resolve import Asset

# 列名映射——若 Task 1 探针结果不同，在此处改
_FUND_DATE_COLS = ["净值日期", "date"]
_FUND_VALUE_COLS = ["单位净值", "value"]
_GOLD_DATE_COLS = ["date", "日期"]
_GOLD_VALUE_COLS = ["close", "收盘价", "收盘"]


def _pick(df: pd.DataFrame, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    raise KeyError(f"未找到列，候选={candidates}，实际={list(df.columns)}")


def _normalize(df, date_cols, value_cols):
    d, v = _pick(df, date_cols), _pick(df, value_cols)
    out = df[[d, v]].rename(columns={d: "date", v: "value"}).copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out["value"] = out["value"].astype(float)
    out = out.dropna().sort_values("date").reset_index(drop=True)
    return out[["date", "value"]]


def _default_fetcher(asset: Asset) -> pd.DataFrame:
    import akshare as ak
    if asset.type == "otc_fund":
        return ak.fund_open_fund_info_em(symbol=asset.symbol, indicator="单位净值走势")
    return ak.spot_hist_sge(symbol=asset.symbol)


def load_prices(asset: Asset, fetcher=None) -> pd.DataFrame:
    fetcher = fetcher or _default_fetcher
    raw = fetcher(asset)
    if asset.type == "otc_fund":
        return _normalize(raw, _FUND_DATE_COLS, _FUND_VALUE_COLS)
    return _normalize(raw, _GOLD_DATE_COLS, _GOLD_VALUE_COLS)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_prices.py -v`
Expected: PASS（2 passed）。若 KeyError，按报错里的"实际列名"更新 Step 3 的候选列表。

- [ ] **Step 5: Commit**

```bash
git add money/data/prices.py tests/test_prices.py
git commit -m "feat: price loader for funds and gold with fixture injection"
```

---

### Task 4: 技术指标 indicators.py

**Files:**
- Create: `money/indicators.py`
- Test: `tests/test_indicators.py`

**Interfaces:**
- Consumes: `load_prices` 输出的 `DataFrame[date,value]`。
- Produces: `compute_indicators(df) -> dict`，结构：
  ```python
  {
    "ma": {"ma5":float|None,"ma10":..,"ma20":..,"ma60":..,"alignment":"多头"|"空头"|"纠缠"},
    "macd": {"dif":float|None,"dea":..,"hist":..,"state":"金叉"|"死叉"|"—"},
    "rsi14": float|None,
    "boll": {"pos":"上轨附近"|"中轨"|"下轨附近","width":float|None},
    "returns": {"1w":float|None,"1m":..,"3m":..,"1y":..},
    "max_drawdown_1y": float|None,
    "volatility_1y": float|None,
  }
  ```
  数据不足以计算的字段填 `None`。

- [ ] **Step 1: 写失败测试（构造单调上升序列，断言可判定字段）**

`tests/test_indicators.py`:
```python
import pandas as pd
from money.indicators import compute_indicators


def _series(vals):
    dates = pd.date_range("2023-01-01", periods=len(vals), freq="D").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in vals]})


def test_uptrend_alignment_bullish():
    df = _series([i for i in range(1, 121)])  # 单调上升
    ind = compute_indicators(df)
    assert ind["ma"]["alignment"] == "多头"
    assert ind["returns"]["1m"] > 0
    assert 0 <= ind["rsi14"] <= 100


def test_short_series_fills_none():
    df = _series([1, 2, 3])  # 太短
    ind = compute_indicators(df)
    assert ind["ma"]["ma60"] is None
    assert ind["returns"]["1y"] is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_indicators.py -v`
Expected: FAIL（ImportError）。

- [ ] **Step 3: 实现**

`money/indicators.py`:
```python
import pandas as pd
import pandas_ta as ta


def _f(x):
    return None if x is None or pd.isna(x) else float(x)


def _ret(s: pd.Series, n: int):
    if len(s) <= n:
        return None
    return _f(s.iloc[-1] / s.iloc[-1 - n] - 1.0)


def compute_indicators(df: pd.DataFrame) -> dict:
    s = df["value"].reset_index(drop=True)
    n = len(s)

    def ma(w):
        return _f(s.rolling(w).mean().iloc[-1]) if n >= w else None

    ma5, ma10, ma20, ma60 = ma(5), ma(10), ma(20), ma(60)
    if None not in (ma5, ma10, ma20, ma60):
        alignment = "多头" if ma5 >= ma10 >= ma20 >= ma60 else ("空头" if ma5 <= ma10 <= ma20 <= ma60 else "纠缠")
    else:
        alignment = "纠缠"

    macd_df = ta.macd(s) if n >= 35 else None
    if macd_df is not None and not macd_df.dropna().empty:
        dif = _f(macd_df.iloc[-1, 0]); hist = _f(macd_df.iloc[-1, 1]); dea = _f(macd_df.iloc[-1, 2])
        prev_hist = _f(macd_df.iloc[-2, 1]) if len(macd_df) >= 2 else None
        state = "—"
        if prev_hist is not None and hist is not None:
            state = "金叉" if prev_hist <= 0 < hist else ("死叉" if prev_hist >= 0 > hist else "—")
    else:
        dif = dea = hist = None; state = "—"

    rsi = _f(ta.rsi(s, length=14).iloc[-1]) if n >= 15 else None

    boll = ta.bbands(s, length=20) if n >= 20 else None
    if boll is not None and not boll.dropna().empty:
        lower, upper = _f(boll.iloc[-1, 0]), _f(boll.iloc[-1, 2])
        last = _f(s.iloc[-1]); width = _f(upper - lower) if None not in (upper, lower) else None
        if None not in (lower, upper, last):
            span = upper - lower or 1.0
            r = (last - lower) / span
            pos = "上轨附近" if r >= 0.8 else ("下轨附近" if r <= 0.2 else "中轨")
        else:
            pos = "中轨"
    else:
        pos, width = "中轨", None

    dd = None
    if n >= 60:
        window = s.iloc[-252:] if n >= 252 else s
        dd = _f((window / window.cummax() - 1.0).min())

    vol = None
    if n >= 30:
        window = s.iloc[-252:] if n >= 252 else s
        vol = _f(window.pct_change().std() * (252 ** 0.5))

    return {
        "ma": {"ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60, "alignment": alignment},
        "macd": {"dif": dif, "dea": dea, "hist": hist, "state": state},
        "rsi14": rsi,
        "boll": {"pos": pos, "width": width},
        "returns": {"1w": _ret(s, 5), "1m": _ret(s, 20), "3m": _ret(s, 60), "1y": _ret(s, 250)},
        "max_drawdown_1y": dd,
        "volatility_1y": vol,
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_indicators.py -v`
Expected: PASS（2 passed）。若 pandas-ta 列顺序不同导致断言失败，按实际列序调整 `macd_df.iloc` / `boll.iloc` 索引。

- [ ] **Step 5: Commit**

```bash
git add money/indicators.py tests/test_indicators.py
git commit -m "feat: technical indicators (ma/macd/rsi/boll/returns/drawdown/vol)"
```

---

### Task 5: 历史分位 percentile.py

**Files:**
- Create: `money/percentile.py`
- Test: `tests/test_percentile.py`

**Interfaces:**
- Consumes: `DataFrame[date,value]`。
- Produces: `price_percentile(df, years=3) -> dict`：`{"price_pct":float|None,"window_years":int,"note":str}`。`price_pct` = 最新值在近 `years` 年（约 252*years 交易日）内的百分位（0..1，point-in-time：只用到最后一天为止的数据）；不足一年数据返回 `None`。

- [ ] **Step 1: 写失败测试**

`tests/test_percentile.py`:
```python
import pandas as pd
from money.percentile import price_percentile


def _series(vals):
    dates = pd.date_range("2020-01-01", periods=len(vals), freq="D").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in vals]})


def test_latest_is_highest():
    df = _series(list(range(1, 400)))  # 最新值最大
    r = price_percentile(df, years=1)
    assert r["price_pct"] is not None and r["price_pct"] > 0.99


def test_insufficient_returns_none():
    df = _series([1, 2, 3])
    assert price_percentile(df, years=1)["price_pct"] is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_percentile.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现**

`money/percentile.py`:
```python
import pandas as pd


def price_percentile(df: pd.DataFrame, years: int = 3) -> dict:
    s = df["value"].reset_index(drop=True)
    win = 252 * years
    note = f"最新值在近 {years} 年内的百分位（point-in-time）"
    if len(s) < 252:
        return {"price_pct": None, "window_years": years, "note": "数据不足一年，无法计算"}
    window = s.iloc[-win:] if len(s) >= win else s
    latest = window.iloc[-1]
    pct = float((window <= latest).mean())
    return {"price_pct": pct, "window_years": years, "note": note}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_percentile.py -v`
Expected: PASS（2 passed）。

- [ ] **Step 5: Commit**

```bash
git add money/percentile.py tests/test_percentile.py
git commit -m "feat: point-in-time historical price percentile"
```

---

### Task 6: 舆情收集 news.py

**Files:**
- Create: `money/data/news.py`
- Test: `tests/test_news.py`

**Interfaces:**
- Consumes: `Asset`；fixtures（Task 1 `news_sample.json`）。
- Produces: `load_news(asset, fetcher=None, limit=10) -> list[dict]`，每项 `{"title","source","date","url","summary"}`（缺失字段填空串）。`fetcher` 依赖注入；默认走 akshare 新闻接口（函数名以 Task 1 为准）。**只收集不预判。**

- [ ] **Step 1: 写失败测试**

`tests/test_news.py`:
```python
from pathlib import Path
import pandas as pd
from money.data.resolve import Asset
from money.data.news import load_news

FX = Path(__file__).parent / "fixtures"


def _fetcher(asset, limit):
    return pd.read_json(FX / "news_sample.json")


def test_load_news_normalized():
    a = Asset(symbol="Au99.99", type="gold")
    items = load_news(a, fetcher=_fetcher, limit=5)
    assert isinstance(items, list) and len(items) <= 5
    for it in items:
        assert set(it.keys()) == {"title", "source", "date", "url", "summary"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_news.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现（列名按 Task 1 校正）**

`money/data/news.py`:
```python
import pandas as pd
from .resolve import Asset

# 列名映射——若 Task 1 探针结果不同，在此处改
_COL = {
    "title": ["新闻标题", "title", "标题"],
    "source": ["文章来源", "source", "来源"],
    "date": ["发布时间", "date", "时间"],
    "url": ["新闻链接", "url", "链接"],
    "summary": ["新闻内容", "content", "内容", "摘要"],
}


def _pick(row, cands):
    for c in cands:
        if c in row and pd.notna(row[c]):
            return str(row[c])
    return ""


def _query_for(asset: Asset) -> str:
    return "黄金" if asset.type == "gold" else asset.symbol


def _default_fetcher(asset: Asset, limit: int) -> pd.DataFrame:
    import akshare as ak
    return ak.stock_news_em(symbol=_query_for(asset))


def load_news(asset: Asset, fetcher=None, limit: int = 10) -> list[dict]:
    fetcher = fetcher or _default_fetcher
    try:
        df = fetcher(asset, limit)
    except Exception:
        return []
    items = []
    for _, row in df.head(limit).iterrows():
        items.append({k: _pick(row, cands) for k, cands in _COL.items()})
    return items
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_news.py -v`
Expected: PASS。若 KeyError/空，按实际列名更新 `_COL`。

- [ ] **Step 5: Commit**

```bash
git add money/data/news.py tests/test_news.py
git commit -m "feat: news collector (collect-only, fixture injection)"
```

---

### Task 7: 证据卡 evidence.py

**Files:**
- Create: `money/evidence.py`
- Test: `tests/test_evidence.py`

**Interfaces:**
- Consumes: `Asset`, `load_prices`, `compute_indicators`, `price_percentile`, `load_news`, 以及 storage 的 `track_record_for`（Task 8，测试里用假对象注入）。
- Produces:
  - pydantic 模型 `EvidenceCard`（含 `schema_version="1.0"` 与 spec 第 7 节字段）。
  - `build_evidence(asset, *, prices, news, track_record) -> EvidenceCard`：纯函数，输入已取好的数据，组装证据卡，计算 `data_quality`。
  - `EvidenceCard.to_json()` / `.to_markdown()`。

- [ ] **Step 1: 写失败测试**

`tests/test_evidence.py`:
```python
import pandas as pd
from money.data.resolve import Asset
from money.evidence import build_evidence, EvidenceCard


def _series(vals):
    dates = pd.date_range("2022-01-01", periods=len(vals), freq="D").strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in vals]})


def test_build_full_card():
    a = Asset(symbol="501018", type="otc_fund", name="测试基金")
    card = build_evidence(
        a,
        prices=_series(list(range(1, 400))),
        news=[{"title": "利好", "source": "x", "date": "2023-01-01", "url": "", "summary": "s"}],
        track_record={"past_signals": 3, "hit_rate": 0.66, "ic": 0.1, "vs_benchmark": 0.02},
    )
    assert isinstance(card, EvidenceCard)
    assert card.schema_version == "1.0"
    assert card.asset.symbol == "501018"
    assert card.price.latest == 399.0
    assert card.data_quality.price == "ok"
    assert "501018" in card.to_json()
    assert "证据卡" in card.to_markdown()


def test_missing_prices_flags_quality():
    a = Asset(symbol="501018", type="otc_fund")
    card = build_evidence(a, prices=_series([]), news=[], track_record=None)
    assert card.data_quality.price == "missing"
    assert card.price.latest is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_evidence.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现**

`money/evidence.py`（用 pydantic 建模，组装并算 data_quality；复用 Task 4/5 计算）：
```python
import json
from typing import Optional, Literal
import pandas as pd
from pydantic import BaseModel
from .data.resolve import Asset
from .indicators import compute_indicators
from .percentile import price_percentile


class PriceBlock(BaseModel):
    latest: Optional[float] = None
    latest_date: Optional[str] = None
    returns: dict = {}
    max_drawdown_1y: Optional[float] = None
    volatility_1y: Optional[float] = None


class DataQuality(BaseModel):
    price: Literal["ok", "stale", "partial", "missing"] = "missing"
    news: Literal["ok", "sparse", "missing"] = "missing"
    notes: list[str] = []


class EvidenceCard(BaseModel):
    schema_version: str = "1.0"
    asset: Asset
    price: PriceBlock = PriceBlock()
    indicators: dict = {}
    percentile: dict = {}
    news: list[dict] = []
    track_record: Optional[dict] = None
    data_quality: DataQuality = DataQuality()

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        p = self.price
        lines = [
            f"# 证据卡：{self.asset.name or self.asset.symbol} ({self.asset.symbol})",
            f"- 类型：{self.asset.type}  最新：{p.latest}（{p.latest_date}）",
            f"- 收益 1w/1m/3m/1y：{p.returns}",
            f"- 最大回撤1y：{p.max_drawdown_1y}  年化波动：{p.volatility_1y}",
            f"- 均线：{self.indicators.get('ma')}",
            f"- MACD：{self.indicators.get('macd')}  RSI14：{self.indicators.get('rsi14')}",
            f"- 布林：{self.indicators.get('boll')}  历史分位：{self.percentile}",
            f"- 舆情条数：{len(self.news)}  战绩：{self.track_record}",
            f"- 数据质量：price={self.data_quality.price} news={self.data_quality.news} {self.data_quality.notes}",
        ]
        return "\n".join(lines)


def build_evidence(asset: Asset, *, prices: pd.DataFrame, news: list[dict], track_record: Optional[dict]) -> EvidenceCard:
    notes = []
    if prices is None or len(prices) == 0:
        price = PriceBlock(); indicators = {}; pct = {}; pq = "missing"; notes.append("无价格数据")
    else:
        ind = compute_indicators(prices)
        price = PriceBlock(
            latest=float(prices["value"].iloc[-1]),
            latest_date=str(prices["date"].iloc[-1]),
            returns=ind["returns"],
            max_drawdown_1y=ind["max_drawdown_1y"],
            volatility_1y=ind["volatility_1y"],
        )
        indicators = {k: ind[k] for k in ("ma", "macd", "rsi14", "boll")}
        pct = price_percentile(prices, years=3)
        pq = "ok" if len(prices) >= 252 else "partial"
        if pq == "partial":
            notes.append("价格数据不足一年，指标置信度下调")
    nq = "ok" if len(news) >= 3 else ("sparse" if news else "missing")
    return EvidenceCard(
        asset=asset, price=price, indicators=indicators, percentile=pct,
        news=news, track_record=track_record,
        data_quality=DataQuality(price=pq, news=nq, notes=notes),
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_evidence.py -v`
Expected: PASS（2 passed）。

- [ ] **Step 5: Commit**

```bash
git add money/evidence.py tests/test_evidence.py
git commit -m "feat: evidence card model and assembler with data-quality flags"
```

---

### Task 8: 预测账本与复盘 storage.py

**Files:**
- Create: `money/storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Produces（SQLite，路径参数化，测试用临时文件）：
  - `Ledger(db_path)`：构造即建表。
  - `log_signal(symbol, type, signal, signal_numeric, confidence, horizons:list[int], price_ref, evidence_json, rationale, framework_version, schema_version, ts) -> int`（append-only，返回 id）。
  - `compute_outcomes(prediction_id, price_series:pd.DataFrame) -> list[dict]`：对每个 horizon 用真实价格算 `realized_return`，与基准（买入持有=同一序列，故基准即自身；预留 benchmark_series 参数默认 None → excess=None），返回并缓存。纯函数式：同输入同输出。
  - `track_record_for(symbol) -> dict|None`：聚合该 symbol 已算 outcome 的 `past_signals/hit_rate/ic/vs_benchmark`；无数据返回 None。
  - `review(symbol=None, since_version=None) -> dict`：全局或单标的战绩汇总。
  - `ts` 参数必传（禁止用 `datetime.now()` 以便测试可复现）。

- [ ] **Step 1: 写失败测试**

`tests/test_storage.py`:
```python
import pandas as pd
from money.storage import Ledger


def _prices(start_val, days):
    dates = pd.date_range("2023-01-01", periods=days, freq="D").strftime("%Y-%m-%d")
    vals = [start_val + i for i in range(days)]  # 每天 +1，上涨
    return pd.DataFrame({"date": dates, "value": [float(v) for v in vals]})


def test_log_and_track(tmp_path):
    led = Ledger(tmp_path / "t.db")
    pid = led.log_signal(
        symbol="501018", type="otc_fund", signal="买", signal_numeric=1,
        confidence=0.6, horizons=[5, 20], price_ref=100.0, evidence_json="{}",
        rationale="test", framework_version="1", schema_version="1.0",
        ts="2023-01-01",
    )
    assert pid > 0
    # 价格从 100 起每天 +1，买入后上涨 → 命中
    outs = led.compute_outcomes(pid, _prices(100.0, 40))
    assert any(o["realized_return"] > 0 for o in outs)
    tr = led.track_record_for("501018")
    assert tr["past_signals"] == 1
    assert 0.0 <= tr["hit_rate"] <= 1.0


def test_append_only_no_overwrite(tmp_path):
    led = Ledger(tmp_path / "t.db")
    a = led.log_signal(symbol="X", type="gold", signal="观望", signal_numeric=0,
                       confidence=0.5, horizons=[5], price_ref=1.0, evidence_json="{}",
                       rationale="", framework_version="1", schema_version="1.0", ts="2023-01-01")
    b = led.log_signal(symbol="X", type="gold", signal="买", signal_numeric=1,
                       confidence=0.5, horizons=[5], price_ref=1.0, evidence_json="{}",
                       rationale="", framework_version="1", schema_version="1.0", ts="2023-01-02")
    assert b == a + 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_storage.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现**

`money/storage.py`:
```python
import json
import sqlite3
from pathlib import Path
import pandas as pd


class Ledger:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn().executescript(
            """
            CREATE TABLE IF NOT EXISTS predictions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts TEXT, symbol TEXT, type TEXT, signal TEXT, signal_numeric INTEGER,
              confidence REAL, horizons TEXT, price_ref REAL, evidence_json TEXT,
              rationale TEXT, framework_version TEXT, schema_version TEXT
            );
            CREATE TABLE IF NOT EXISTS outcomes (
              prediction_id INTEGER, horizon INTEGER, realized_return REAL,
              excess REAL, hit INTEGER,
              PRIMARY KEY (prediction_id, horizon)
            );
            """
        )

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def log_signal(self, *, symbol, type, signal, signal_numeric, confidence, horizons,
                   price_ref, evidence_json, rationale, framework_version, schema_version, ts) -> int:
        c = self._conn()
        cur = c.execute(
            "INSERT INTO predictions (ts,symbol,type,signal,signal_numeric,confidence,horizons,"
            "price_ref,evidence_json,rationale,framework_version,schema_version) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, symbol, type, signal, signal_numeric, confidence, json.dumps(horizons),
             price_ref, evidence_json, rationale, framework_version, schema_version),
        )
        c.commit()
        return cur.lastrowid

    def compute_outcomes(self, prediction_id, price_series: pd.DataFrame, benchmark_series=None):
        c = self._conn()
        row = c.execute("SELECT * FROM predictions WHERE id=?", (prediction_id,)).fetchone()
        if row is None:
            return []
        horizons = json.loads(row["horizons"])
        ref = row["price_ref"]; sign = row["signal_numeric"]
        s = price_series.reset_index(drop=True)
        pos = s.index[s["date"] > row["ts"]]
        start = int(pos[0]) if len(pos) else 0
        results = []
        for h in horizons:
            idx = start + h
            if idx >= len(s):
                continue
            realized = float(s["value"].iloc[idx] / ref - 1.0)
            hit = 1 if (realized > 0) == (sign > 0) or (sign == 0 and abs(realized) < 0.01) else 0
            c.execute("INSERT OR REPLACE INTO outcomes VALUES (?,?,?,?,?)",
                      (prediction_id, h, realized, None, hit))
            results.append({"horizon": h, "realized_return": realized, "excess": None, "hit": hit})
        c.commit()
        return results

    def track_record_for(self, symbol):
        c = self._conn()
        rows = c.execute(
            "SELECT o.hit, o.realized_return, p.signal_numeric FROM outcomes o "
            "JOIN predictions p ON p.id=o.prediction_id WHERE p.symbol=?", (symbol,)
        ).fetchall()
        n_pred = c.execute("SELECT COUNT(*) n FROM predictions WHERE symbol=?", (symbol,)).fetchone()["n"]
        if not rows:
            return None if n_pred == 0 else {"past_signals": n_pred, "hit_rate": None, "ic": None, "vs_benchmark": None}
        hits = [r["hit"] for r in rows]
        hit_rate = sum(hits) / len(hits)
        # IC：signal_numeric 与 realized_return 的相关（样本少则 None）
        ic = None
        if len(rows) >= 3:
            sn = pd.Series([r["signal_numeric"] for r in rows], dtype=float)
            rr = pd.Series([r["realized_return"] for r in rows], dtype=float)
            ic = None if sn.std() == 0 or rr.std() == 0 else float(sn.corr(rr))
        return {"past_signals": n_pred, "hit_rate": hit_rate, "ic": ic, "vs_benchmark": None}

    def review(self, symbol=None, since_version=None):
        c = self._conn()
        q = ("SELECT p.symbol, o.hit, o.realized_return, p.signal_numeric, p.confidence "
             "FROM outcomes o JOIN predictions p ON p.id=o.prediction_id WHERE 1=1")
        args = []
        if symbol:
            q += " AND p.symbol=?"; args.append(symbol)
        if since_version:
            q += " AND p.framework_version>=?"; args.append(since_version)
        rows = c.execute(q, args).fetchall()
        if not rows:
            return {"n": 0, "note": "暂无已到期的预测，数据不足"}
        hits = [r["hit"] for r in rows]
        return {
            "n": len(rows),
            "hit_rate": sum(hits) / len(hits),
            "note": "样本量小，仅供参考" if len(rows) < 20 else "ok",
        }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_storage.py -v`
Expected: PASS（2 passed）。

- [ ] **Step 5: Commit**

```bash
git add money/storage.py tests/test_storage.py
git commit -m "feat: append-only prediction ledger with outcome/track-record/review"
```

---

### Task 9: 分析框架 analysis_framework.md

**Files:**
- Create: `quantfox/prompts/analysis_framework.md`
- Create: `quantfox/prompts/__init__.py`
- Test: `tests/test_framework.py`

**Interfaces:**
- Produces: `quantfox/prompts/framework_path() -> Path` 与 `framework_version() -> str`（读取文件首行 `<!-- version: N -->`）。

- [ ] **Step 1: 写失败测试**

`tests/test_framework.py`:
```python
from money.prompts import framework_path, framework_version


def test_framework_exists_and_versioned():
    p = framework_path()
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "信号档位" in text
    assert "风险" in text
    assert framework_version() == "1"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_framework.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现**

`quantfox/prompts/__init__.py`:
```python
import re
from pathlib import Path

_PATH = Path(__file__).parent / "analysis_framework.md"


def framework_path() -> Path:
    return _PATH


def framework_version() -> str:
    m = re.search(r"<!--\s*version:\s*(\S+)\s*-->", _PATH.read_text(encoding="utf-8"))
    return m.group(1) if m else "0"
```

`quantfox/prompts/analysis_framework.md`:
```markdown
<!-- version: 1 -->
# 分析框架（判断层唯一真理源）

你（Claude）读一张"证据卡"+ 最新舆情，产出可解释的信号。严格遵守：

## 信号档位
- 强买 / 买 / 观望 / 减 / 回避。数值化：强买=2, 买=1, 观望=0, 减=-1, 回避=-2。

## 判定倾向（参照，非硬阈值）
- 偏买：均线多头 + MACD 金叉/histogram 转正 + RSI 未超买(<70) + 历史分位偏低(<0.4) + 舆情偏正。
- 偏回避：均线空头 + 死叉 + RSI 超买(>75) + 历史分位偏高(>0.8) + 明确利空。
- 证据打架时倾向"观望"，并说明分歧点。

## 输出必须包含
1. 信号 + 置信度(0-1)。若 data_quality 有 missing/partial，明确下调置信度并说明。
2. 采信了哪几条舆情、为什么；忽略了哪些噪音/营销，为什么。
3. 量化证据如何支撑或反驳该信号。
4. 风险与不确定性（必写）。
5. 参照 track_record 的校准说明（历史上此类判断准不准，据此收放把握）。

## 禁止
- 给精确点位或精确收益承诺。
- 把 null 当依据。
- 无理由的乐观或悲观。

## 场外基金提示
净值 T+1，信号面向"次日申购"语义；注意短期赎回费。
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_framework.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add quantfox/prompts tests/test_framework.py
git commit -m "feat: versioned analysis framework (judgment-layer contract)"
```

---

### Task 10: CLI cli.py

**Files:**
- Create: `money/cli.py`
- Create: `money/config.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: 全部前序模块。
- Produces: typer `app`，命令：
  - `quantfox evidence <query> [--format json|markdown]`：解析→取价→取新闻→查战绩→组装证据卡→打印。
  - `quantfox fetch <query>` / `quantfox indicators <query>` / `quantfox news <query>`：调试用。
  - `quantfox log-signal ...` / `quantfox outcomes` / `quantfox review [query] [--all] [--since V]`。
  - `money/config.py`：`data_dir()`（默认 `~/.money`，可 `MONEY_HOME` 覆盖）、`ledger_path()`。
- 网络失败时 evidence 仍输出证据卡但 data_quality 标 missing（用 CliRunner 测试时注入假数据不打网络）。

- [ ] **Step 1: 写失败测试（用 typer CliRunner，money evidence 走注入）**

`tests/test_cli.py`:
```python
from typer.testing import CliRunner
from money.cli import app

runner = CliRunner()


def test_evidence_gold_markdown(monkeypatch):
    import pandas as pd
    import money.cli as cli
    df = pd.DataFrame({"date": pd.date_range("2022-01-01", periods=400).strftime("%Y-%m-%d"),
                       "value": [float(i) for i in range(1, 401)]})
    monkeypatch.setattr(cli, "_prices_for", lambda asset: df)
    monkeypatch.setattr(cli, "_news_for", lambda asset: [])
    result = runner.invoke(app, ["evidence", "gold", "--format", "markdown"])
    assert result.exit_code == 0
    assert "证据卡" in result.stdout


def test_resolve_error_exit_code():
    result = runner.invoke(app, ["evidence", "banana"])
    assert result.exit_code != 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现**

`money/config.py`:
```python
import os
from pathlib import Path


def data_dir() -> Path:
    d = Path(os.environ.get("MONEY_HOME", Path.home() / ".money"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def ledger_path() -> Path:
    return data_dir() / "ledger.db"
```

`money/cli.py`:
```python
import json
import typer
from .data.resolve import resolve
from .data.prices import load_prices
from .data.news import load_news
from .evidence import build_evidence
from .indicators import compute_indicators
from .percentile import price_percentile
from .storage import Ledger
from .prompts import framework_version
from .config import ledger_path

app = typer.Typer(help="场外基金与黄金的量化证据卡 + Claude 决策助手")


def _prices_for(asset):
    return load_prices(asset)


def _news_for(asset):
    return load_news(asset)


def _ledger():
    return Ledger(ledger_path())


@app.command()
def evidence(query: str, format: str = typer.Option("json", help="json|markdown")):
    """产出完整证据卡（Skill 主命令）。"""
    asset = resolve(query)
    try:
        prices = _prices_for(asset)
    except Exception as e:  # noqa
        prices = prices_empty()
        typer.echo(f"# 取价失败: {e}", err=True)
    try:
        news = _news_for(asset)
    except Exception:
        news = []
    tr = _ledger().track_record_for(asset.symbol)
    card = build_evidence(asset, prices=prices, news=news, track_record=tr)
    typer.echo(card.to_markdown() if format == "markdown" else card.to_json())


def prices_empty():
    import pandas as pd
    return pd.DataFrame({"date": [], "value": []})


@app.command()
def fetch(query: str):
    asset = resolve(query)
    typer.echo(_prices_for(asset).tail(10).to_string())


@app.command()
def indicators(query: str):
    asset = resolve(query)
    typer.echo(json.dumps(compute_indicators(_prices_for(asset)), ensure_ascii=False, indent=2))


@app.command()
def news(query: str):
    asset = resolve(query)
    typer.echo(json.dumps(_news_for(asset), ensure_ascii=False, indent=2))


@app.command("log-signal")
def log_signal(symbol: str, signal: str, signal_numeric: int, confidence: float,
               price_ref: float, ts: str, type: str = "otc_fund",
               horizons: str = "5,20,60", rationale: str = "", evidence_json: str = "{}"):
    pid = _ledger().log_signal(
        symbol=symbol, type=type, signal=signal, signal_numeric=signal_numeric,
        confidence=confidence, horizons=[int(x) for x in horizons.split(",")],
        price_ref=price_ref, evidence_json=evidence_json, rationale=rationale,
        framework_version=framework_version(), schema_version="1.0", ts=ts,
    )
    typer.echo(json.dumps({"prediction_id": pid}))


@app.command()
def outcomes(query: str, prediction_id: int):
    asset = resolve(query)
    res = _ledger().compute_outcomes(prediction_id, _prices_for(asset))
    typer.echo(json.dumps(res, ensure_ascii=False, indent=2))


@app.command()
def review(query: str = typer.Argument(None), all: bool = typer.Option(False, "--all"),
           since: str = typer.Option(None, "--since")):
    led = _ledger()
    if all or query is None:
        typer.echo(json.dumps(led.review(since_version=since), ensure_ascii=False, indent=2))
    else:
        asset = resolve(query)
        typer.echo(json.dumps(led.review(symbol=asset.symbol, since_version=since), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS（2 passed）。

- [ ] **Step 5: Commit**

```bash
git add money/cli.py money/config.py tests/test_cli.py
git commit -m "feat: typer CLI (evidence/fetch/indicators/news/log-signal/outcomes/review)"
```

---

### Task 11: Claude Code Skill `fund-analyze`

**Files:**
- Create: `.claude/skills/fund-analyze/SKILL.md`
- Test: `tests/test_skill_file.py`

**Interfaces:**
- Produces: 一个 SKILL.md，指导 Claude：跑 `quantfox review` 看战绩 → 跑 `quantfox evidence <q> --format json` 取证据卡 → 用 WebSearch 补最新舆情 → 按 `analysis_framework.md` 推理 → 输出信号 → 跑 `quantfox log-signal` 存档。

- [ ] **Step 1: 写失败测试（校验 SKILL.md 结构）**

`tests/test_skill_file.py`:
```python
from pathlib import Path


def test_skill_file_valid():
    p = Path(".claude/skills/fund-analyze/SKILL.md")
    text = p.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "name:" in text and "description:" in text
    assert "money evidence" in text
    assert "money log-signal" in text
    assert "analysis_framework" in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_skill_file.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现**

`.claude/skills/fund-analyze/SKILL.md`:
```markdown
---
name: fund-analyze
description: 分析场外基金或黄金，给出可解释的买入/观望/回避信号。当用户想分析、评估、判断某只基金或黄金是否可购入、涨跌前景、风险时使用。输入基金 6 位代码或"黄金"。
---

# 基金/黄金分析

你是一个严谨的量化参谋。分析某标的时，按下列步骤，全程用中文、透明说明依据。

## 步骤
1. 确定标的：从用户话里提取基金代码（6 位）或识别"黄金"。含糊则先问清。
2. 看历史战绩（校准自己）：
   `quantfox review <标的>`
3. 取证据卡：
   `quantfox evidence <标的> --format json`
   读取其中 price/indicators/percentile/news/track_record/data_quality。
4. 补最新舆情：用 WebSearch/WebFetch 搜该标的近期新闻、公告、讨论，鉴别真伪与来源可信度。
5. 按判断框架推理：读取并遵守 `quantfox/prompts/analysis_framework.md` 的信号档位与输出要求。
6. 产出结论：信号 + 置信度 + 采信/忽略了哪些舆情及原因 + 量化支撑 + 风险 + 基于战绩的校准说明。
7. 存档本次预测（用于日后复盘）：
   `quantfox log-signal --symbol <代码> --type <otc_fund|gold> --signal <档位> --signal-numeric <2..-2> --confidence <0-1> --price-ref <证据卡最新价> --ts <今天YYYY-MM-DD> --horizons 5,20,60 --rationale "<一句话理由>"`

## 铁律
- 不承诺精确点位/收益。data_quality 有缺失时明说并下调置信度。
- 若 track_record 显示某类判断历史命中率低，收敛把握并说明。
- 最终决策与风险由用户承担，需在结尾提示。
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_skill_file.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/fund-analyze/SKILL.md tests/test_skill_file.py
git commit -m "feat: fund-analyze Claude Code skill"
```

---

### Task 12: 全量测试 + 真实端到端冒烟 + README

**Files:**
- Create: `README.md`
- Modify: `docs/task.md`（勾掉 P1）

**Interfaces:** 无新接口，验证整体。

- [ ] **Step 1: 全量单测**

Run: `uv run pytest -v`
Expected: 全部 PASS。

- [ ] **Step 2: 真实端到端冒烟（打网络，手动）**

Run:
```bash
quantfox evidence gold --format markdown
quantfox evidence 501018 --format json | head -40
```
Expected: 打印出证据卡；若 akshare 接口报错，回 Task 3/6 按实际列名修正后重跑。把实际输出贴进完成报告。

- [ ] **Step 3: 写 README（安装 + 用法 + 免责声明）**

README 包含：`uv sync` 安装、`quantfox evidence` 用法、Skill 用法、以及**明确免责声明**（非投资建议、不保证盈利、决策自负）。

- [ ] **Step 4: Commit**

```bash
git add README.md docs/task.md
git commit -m "docs: readme, disclaimer, mark P1 complete"
```

---

## Self-Review

- **Spec coverage**：数据(Task3)、指标(Task4)、分位(Task5)、舆情收集(Task6)、证据卡(Task7)、预测账本+复盘(Task8)、分析框架(Task9)、CLI(Task10)、Skill(Task11)、严谨性(point-in-time 分位/真实收益 outcome/append-only/样本不足提示，散落 Task5/8)。P2/P3 明确不在本计划。✅
- **Placeholder scan**：无 TBD；数据层列名依赖 Task 1 探针实测，已在对应步骤标注"按实测校正"。
- **Type consistency**：`Asset`/`EvidenceCard`/`Ledger` 方法名跨任务一致；`load_prices/compute_indicators/price_percentile/load_news/build_evidence/log_signal/compute_outcomes/track_record_for/review` 命名统一。
```
