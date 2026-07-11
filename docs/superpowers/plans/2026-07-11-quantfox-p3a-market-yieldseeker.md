# Quantfox P3a（yield-seeker 收尾 + A股市场层 + 事件多源 + 框架 v16）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 spec `docs/superpowers/specs/2026-07-11-quantfox-p3-market-etf-design.md` 的 W1（C3/C4/C5+SOP）、W2（`quantfox market`）、W5（事件多源+缓存）与框架 v16；W3/W4 属 P3b 不在本计划。

**Architecture:** 主题词表抽成共享 `themes.py`（evidence 与 gold_report 共用）；`market.py` 全 fetcher 注入、按块降级、产出 `regime_line`；事件日历加源列表+当日缓存；SOP/框架文本层同步 v16。

**Tech Stack:** 现有栈（typer/pandas/akshare），不新增依赖。

## Global Constraints

- 基线：`uv run pytest -q` = **177 passed, 1 skipped**；每任务后全量重跑全绿。
- 测试零网络、零真实家目录（QUANTFOX_HOME=tmp_path，fetcher 全注入）。
- 隐私铁律：进 git 无真实邮箱/个人账目；合成数据。
- 中文文案，英文代码/commit；commit 尾 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- 尽力而为语义：market/events 任一块失败 → 该块弃权 + DataHealth 明细，绝不虚报"一切正常"。
- 产物只落 `QUANTFOX_HOME`。

---

### Task 1: 共享主题词表 themes.py + C3 名实核对（evidence 2.2）

**Files:**
- Create: `quantfox/themes.py`
- Modify: `quantfox/gold_report.py`（删本地 `_INDUSTRY_WORDS`/`_name_theme_mismatch`，改 import）
- Modify: `quantfox/evidence.py`（holdings `theme_guess` + 顶层 `name_theme_mismatch`，SCHEMA_VERSION 2.1→2.2）
- Test: `tests/test_themes.py`（新建）+ `tests/test_evidence.py`（追加）

**Interfaces:**
- Produces: `themes.INDUSTRY_WORDS: list[str]`；`themes.guess_theme(names: list[str]) -> str | None`（对一组股票/持仓名做行业词计数，返回票数最高的词，无命中 None，平票取词表序靠前者）；`themes.name_theme_mismatch(name: str | None, theme: str | None) -> bool`（语义与现 gold_report 版一致：name 含行业词且该词≠theme→True；任一侧空→False）。
- evidence 卡新增：`profile.holdings.theme_guess`（build_evidence 内当 holdings.top 非空时计算，名单取 `[x["name"] for x in top]`）；顶层 `name_theme_mismatch = themes.name_theme_mismatch(asset.name, theme_guess)`。

- [ ] **Step 1: 失败测试**

`tests/test_themes.py`：

```python
from quantfox.themes import guess_theme, name_theme_mismatch


def test_guess_theme_majority():
    names = ["中芯国际", "北方华创半导体", "半导体ETF", "贵州茅台"]
    assert guess_theme(names) == "半导体"


def test_guess_theme_none_when_no_hit():
    assert guess_theme(["某某股份", "另一公司"]) is None
    assert guess_theme([]) is None


def test_mismatch_semantics():
    assert name_theme_mismatch("示例医疗精选", "半导体") is True
    assert name_theme_mismatch("示例医疗精选", "医疗") is False
    assert name_theme_mismatch(None, "医疗") is False
    assert name_theme_mismatch("示例医疗精选", None) is False
```

`tests/test_evidence.py` 追加（仿现有测试的构造方式，先读该文件）：

```python
def test_theme_guess_and_mismatch_in_card():
    from quantfox.data.resolve import Asset
    from quantfox.evidence import build_evidence

    profile = {"applicable": True, "basic": {"type": "股票型"},
               "holdings": {"as_of": "2026-06-30", "top10_concentration": 50.0,
                            "top": [{"name": "北方华创半导体", "pct": 8.0},
                                    {"name": "中芯国际半导体", "pct": 7.0},
                                    {"name": "贵州茅台", "pct": 5.0}]}}
    card = build_evidence(Asset(symbol="000001", type="otc_fund", name="示例医疗健康混合"),
                          prices=None, profile=profile, track_record=None)
    assert card.profile["holdings"]["theme_guess"] == "半导体"
    assert card.name_theme_mismatch is True
    assert card.schema_version == "2.2"


def test_no_mismatch_without_holdings():
    from quantfox.data.resolve import Asset
    from quantfox.evidence import build_evidence

    card = build_evidence(Asset(symbol="000001", type="otc_fund", name="示例医疗健康混合"),
                          prices=None, profile={"applicable": False}, track_record=None)
    assert card.name_theme_mismatch is False
```

- [ ] **Step 2: RED 确认** → `uv run pytest tests/test_themes.py tests/test_evidence.py -v` FAIL

- [ ] **Step 3: 实现**

`quantfox/themes.py`：

```python
"""共享行业主题词表与名实核对启发（evidence C3 与 gold_report 共用，唯一出处）。"""

INDUSTRY_WORDS = ["医疗", "医药", "半导体", "新能源", "白酒", "军工", "科技", "消费",
                  "金融", "地产", "黄金", "芯片", "光伏", "汽车"]


def guess_theme(names):
    """对一组持仓/股票名做行业词计数，返回最高票的词；无命中 None；平票取词表序靠前者。"""
    if not names:
        return None
    counts = {}
    for n in names:
        for w in INDUSTRY_WORDS:
            if n and w in n:
                counts[w] = counts.get(w, 0) + 1
    if not counts:
        return None
    return max(INDUSTRY_WORDS, key=lambda w: (counts.get(w, 0), ), default=None) \
        if max(counts.values()) > 0 else None


def name_theme_mismatch(name, theme):
    if not name or not theme:
        return False
    for w in INDUSTRY_WORDS:
        if w in name and w != theme:
            return True
    return False
```

注意 `guess_theme` 的平票语义：用 `max(INDUSTRY_WORDS, key=lambda w: counts.get(w, 0))` 在词表序上取最先达到最大计数者（上面代码按此意图写，实现时用这个简式）。
注意 `name_theme_mismatch` 语义变化：gold_report 旧版是 `w in name and w not in theme`（theme 是自由文本）；共享版 theme 现在既可能是自由文本（screen 的 theme）也可能是词表词（guess_theme 产出）——保留旧语义 `w not in (theme or "")` 以同时兼容两者，测试按此断言（"半导体" not in "医疗" → mismatch True）。

`gold_report.py`：删除 `_INDUSTRY_WORDS` 与 `_name_theme_mismatch`，顶部 `from .themes import name_theme_mismatch as _name_theme_mismatch`（调用点不变）。

`evidence.py`：`SCHEMA_VERSION = "2.2"`；`EvidenceCard` 增字段 `name_theme_mismatch: bool = False`；`build_evidence` 在 profile 处理处加：

```python
    theme_guess = None
    holdings = (profile.get("holdings") or {}) if profile.get("applicable") else {}
    top = holdings.get("top") or []
    if top:
        from .themes import guess_theme, name_theme_mismatch as _ntm

        theme_guess = guess_theme([x.get("name") for x in top])
        profile = {**profile, "holdings": {**holdings, "theme_guess": theme_guess}}
    mismatch = False
    if theme_guess:
        from .themes import name_theme_mismatch as _ntm2

        mismatch = _ntm2(asset.name, theme_guess)
```

（实现时把 import 收敛到文件顶部一次性 `from .themes import guess_theme, name_theme_mismatch`，上面只是逻辑示意；`mismatch` 传入 EvidenceCard。）

- [ ] **Step 4: GREEN + 既有 schema 断言修正**：`tests/test_evidence.py`/`tests/test_metrics_batch.py` 里如有 `"2.1"` 字面断言改 `"2.2"`；跑全量。

- [ ] **Step 5: Commit**

```bash
git add quantfox/themes.py quantfox/gold_report.py quantfox/evidence.py tests/test_themes.py tests/test_evidence.py tests/test_metrics_batch.py
git commit -m "feat(evidence): C3 theme_guess from real holdings + name/theme mismatch flag (schema 2.2), shared themes module"
```

---

### Task 2: C4 forecast 小样本警示字段

**Files:**
- Modify: `quantfox/forecast.py`（`forecast()`）
- Test: `tests/test_forecast.py`（追加）

**Interfaces:**
- Produces: `forecast()` 每个 horizon 的 `all`/`from_similar_valuation` 分布 dict：`n < 200` 时附 `"warning": "样本不足，谨慎参考"`；顶层：`len(prices) < 756` 时附 `"age_warning": "成立不足3年，全部前瞻打折看待"`。既有 `all<60`→note 语义不变。

- [ ] **Step 1: 失败测试**（追加到 `tests/test_forecast.py`，构造方式仿该文件现有测试——先读它）

```python
def test_small_sample_warning_fields():
    import numpy as np
    import pandas as pd

    from quantfox.forecast import forecast

    n = 500  # <756 → age_warning；500-250 视 horizon 部分分布 n<200 → warning
    rng = np.random.default_rng(3)
    vals = 2.0 * np.cumprod(1 + rng.normal(0.0003, 0.01, n))
    df = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
                       "value": vals})
    out = forecast(df)
    assert out["age_warning"].startswith("成立不足3年")
    d250 = out["horizons"]["250"]["all"]
    assert d250.get("warning") == "样本不足，谨慎参考"  # n=250 < 200? n=500-250=250 → 不触发！用 120 日验证
```

注意上例最后一行的算术：`fwd_all` 的 n = len(prices) − horizon；用 `n=380` 的序列则 horizon=250 时 n=130<200 触发 warning、horizon=20 时 n=360≥200 不触发——**测试按 n=380 写两条断言**（触发与不触发各一），上面示意需修正为：

```python
def test_small_sample_warning_fields():
    ...
    n = 380
    ...
    out = forecast(df)
    assert out["age_warning"].startswith("成立不足3年")
    assert out["horizons"]["250"]["all"].get("warning") == "样本不足，谨慎参考"   # n=130
    assert "warning" not in out["horizons"]["20"]["all"]                        # n=360
    # 长历史无 age_warning
    n2 = 1000
    vals2 = 2.0 * np.cumprod(1 + rng.normal(0.0003, 0.01, n2))
    df2 = pd.DataFrame({"date": pd.date_range("2021-01-01", periods=n2, freq="B").strftime("%Y-%m-%d"),
                        "value": vals2})
    assert "age_warning" not in forecast(df2)
```

- [ ] **Step 2: RED → 实现**：`_dist()` 加参数不动；在 `forecast()` 组装处：每个 `d["all"]`/`d["from_similar_valuation"]` 生成后 `if dist.get("n", 0) < 200 and "note" not in dist: dist["warning"] = "样本不足，谨慎参考"`；返回 dict 顶层 `if n < 756: out["age_warning"] = "成立不足3年，全部前瞻打折看待"`（n=len(s)）。GREEN，全量。

- [ ] **Step 3: Commit**

```bash
git add quantfox/forecast.py tests/test_forecast.py
git commit -m "feat(forecast): C4 small-sample warning fields (per-distribution n<200, fund age <3y)"
```

---

### Task 3: C5 `quantfox next-confirm`

**Files:**
- Modify: `quantfox/cli.py`（新顶层命令，放 `forecast` 命令之后）
- Test: `tests/test_next_confirm.py`（新建）

**Interfaces:**
- Consumes: `calendar_cn.nav_date_for_order/trade_dates`。
- Produces: CLI `quantfox next-confirm [--at "YYYY-MM-DD HH:MM"]` → JSON `{"order_at", "nav_date", "note"}`。

- [ ] **Step 1: 失败测试**

```python
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


def test_calendar_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTFOX_HOME", str(tmp_path))

    def boom(fetcher=None):
        raise RuntimeError("交易日历不可用且无缓存：请用 --confirm-date 手动指定净值确认日")

    monkeypatch.setattr(cal, "trade_dates", boom)
    res = runner.invoke(cli.app, ["next-confirm", "--at", "2026-07-10 10:00"])
    assert res.exit_code != 0
```

- [ ] **Step 2: RED → 实现**

```python
@app.command("next-confirm")
def next_confirm(at: str = typer.Option(None, "--at", help='下单时刻 "YYYY-MM-DD HH:MM"，缺省=现在')):
    """现在（或指定时刻）下单，按 15:00 cutoff + 交易日历推场外基金净值确认日。"""
    from .calendar_cn import nav_date_for_order, trade_dates

    order_at = _dt.datetime.strptime(at, "%Y-%m-%d %H:%M") if at else _dt.datetime.now()
    try:
        nav_date = nav_date_for_order(order_at, trade_dates())
    except RuntimeError as e:
        raise typer.BadParameter(str(e)) from e
    typer.echo(json.dumps({"order_at": order_at.strftime("%Y-%m-%d %H:%M"), "nav_date": nav_date,
                           "note": "15:00 前按当日净值确认，之后顺延下一交易日（场外基金）"},
                          ensure_ascii=False))
```

- [ ] **Step 3: GREEN + 全量 + Commit**

```bash
git add quantfox/cli.py tests/test_next_confirm.py
git commit -m "feat(cli): C5 next-confirm — nav confirmation date for an order placed now"
```

---

### Task 4: W2 A股市场层 market.py + CLI

**Files:**
- Create: `quantfox/market.py`
- Modify: `quantfox/cli.py`（新命令 `market`，放 `market-valuation` 之后）
- Test: `tests/test_market.py`（新建）

**Interfaces:**
- Produces: `market.build_market_view(fetchers: dict) -> dict`——`fetchers` 键：`index_hist(symbol) -> pd.DataFrame(date,value)`、`index_pe(symbol) -> pd.DataFrame(date,value)`（PE 序列）、`breadth() -> float | None`（站上 MA60 比例 0-1）、`sector_momentum() -> list[dict(code,name,r_1m,r_3m)] | None`。返回 payload：`{"indices": [...], "breadth": ..., "sectors": {"top": [...], "bottom": [...]}, "health": [...], "regime_line": str}`。CLI `quantfox market [--brief]` 用生产 fetchers 接线（实现时探测 akshare 接口：PE 序列从 `stock_index_pe_lg`/`index_value_hist_funddb` 择稳，指数日线从 `stock_zh_index_daily`/`index_zh_a_hist` 择稳，宽度从 `stock_zh_a_spot_em` 聚合；任一探测不稳→该 fetcher 返回 None/抛异常，块级弃权）。
- 指数清单常量：`INDICES = [("000300", "沪深300"), ("000905", "中证500"), ("399006", "创业板指"), ("000688", "科创50"), ("000922", "中证红利")]`（生产接线时按所选接口的代码格式适配，常量语义不变）。

**块逻辑（写死在 build_market_view）**：
- 每指数：PE 近10年分位（`(pe_series <= latest).mean()`，序列 <1000 点则该指数估值弃权记 health）；动量 r_20/r_60（`hist.value` 尾部收益）；`ma20>ma60` 布尔。fetcher 抛异常/返回 None → 该指数记 health failed，其余继续。
- breadth：直接透传（None → 记 health "宽度不可用"）。
- sectors：按 r_1m 排序取 top5/bottom5；None → 记 health "行业轮动不可用"。
- `regime_line`：模板拼接——估值（可用指数 PE 分位均值 >0.7 → "整体估值偏贵"；0.4-0.7 → "中位"；<0.4 → "偏便宜"；全弃权 → "估值不可用"）+ 动量（多数指数 ma20>ma60 → "趋势偏多" else "趋势偏弱"）+ 热点（sectors.top 前两名名称，"热点：X/Y"；不可用省略）。

- [ ] **Step 1: 失败测试**（全注入，覆盖：全块成功出 regime_line 与三块数据；单指数 fetcher 抛异常→health 有明细且其余指数正常；breadth/sectors None→行弃权；PE 序列过短→该指数估值弃权。测试构造合成 PE/hist 序列（numpy 随机 1200 点），断言 regime_line 含"估值"字样与热点名。每条断言写实、无空壳。）

- [ ] **Step 2: RED → 实现 market.py →GREEN**

- [ ] **Step 3: CLI 接线**：`market` 命令组装生产 fetchers（每个 fetcher 内部 try/except 返回 None 或抛给块级处理），`--brief` 只输出 `{"regime_line": ...}`。真实接口探测放实现时：探测失败的接口在 fetcher 里直接 `raise RuntimeError("接口不可用")` 让块级降级——不留假数据路径。

- [ ] **Step 4: 全量 + Commit**

```bash
git add quantfox/market.py quantfox/cli.py tests/test_market.py
git commit -m "feat(market): A-share market layer — index valuation percentile, momentum, breadth, sector rotation, regime line"
```

---

### Task 5: gold-report 头部 regime 升级（双重降级）

**Files:**
- Modify: `quantfox/cli.py`（gold-report 命令的 meta 组装处）
- Modify: `quantfox/gold_report_render.py`（header regime 行渲染消费 `meta["regime_line"]`，缺失时回退现 market_valuation 展示，再缺失显示"regime 不可用"）
- Test: `tests/test_gold_render.py`（追加：payload meta 带 regime_line → HTML 含之；不带但有 market_valuation → 旧展示；都无 → "regime 不可用"）

- [ ] **Step 1: 失败测试（三分支断言）→ Step 2: 实现（CLI：try market --brief 等价函数 `build_market_view` 生产接线取 regime_line，异常→None；render 三分支）→ Step 3: GREEN + 全量 + Commit**

```bash
git add quantfox/cli.py quantfox/gold_report_render.py tests/test_gold_render.py
git commit -m "feat(gold-report): regime header upgraded to market layer line with double fallback"
```

---

### Task 6: W5 事件日历多源 + 当日缓存

**Files:**
- Modify: `quantfox/data/events_cn.py`
- Test: `tests/test_events_cn.py`（新建）

**Interfaces:**
- Produces: `next_week_events(sources=None, cache_path=None, today=None) -> list | None`——`sources`: list[callable]，默认 `[_source_baidu, _source_secondary]`（次源实现时探测 akshare 宏观日历类接口，探测不稳则次源函数体直接 `raise RuntimeError("不可用")`——保持双源结构，行为等价单源）；依序尝试，首个成功非空即用；成功结果写 `cache_path`（默认 `data_dir()/"events_cache.json"`，内容 `{"date": today, "events": [...]}`）；调用开头若缓存存在且 `date==today` 直接返回缓存；全失败返回 None（不写缓存）。

- [ ] **Step 1: 失败测试**（注入 sources/fake cache_path/today：首源失败次源成功；双源失败→None；缓存当日命中不调 source（用计数器断言）；缓存过期重取。）→ **Step 2: RED → 实现 → GREEN + 全量**（既有 test_gold_render 若 monkeypatch 该函数签名需同步——它走 events_fn 注入，不受影响，确认即可。）

- [ ] **Step 3: Commit**

```bash
git add quantfox/data/events_cn.py tests/test_events_cn.py
git commit -m "feat(events): multi-source with same-day cache, abstain on total failure"
```

---

### Task 7: 框架 v16 + SOP 文本（诉求校准/风偏 + flags/theme_guess 消费 + next-confirm）

**Files:**
- Modify: `quantfox/prompts/analysis_framework.md`（version 16）
- Modify: `skills/fund-screener/SKILL.md`（「第 0 步 · 诉求校准与风偏探测」）+ 7 个 SKILL.md 共享段出处行 v15→v16
- Modify: `skills/fund-analyze/SKILL.md`（名实核对一句）
- Test: `tests/test_framework.py`、`tests/test_skill_file.py`（版本断言 16/v16 + 新关键词）

**框架 v16 增量（「诚实铁律」节后追加两条）**：

```markdown
5. **假稳三查必须消费 flags 字段**：evidence/metrics-batch 输出的 `flags`（nav_spike_suspect/bond_equity_risk/short_history）出现任何一项时，必须向用户明示该风险并降档处理，禁止只字不提。
6. **名实核对**：evidence 的 `name_theme_mismatch=true` 时，必须点明"基金名与实际重仓主题不符"，舆情按 `holdings.theme_guess` 的实际主题搜，不按基金名搜。
```

「产物与留痕铁律」个性化条后追加一句：`大盘 regime 判断用 quantfox market --brief（其不可用再退 market-valuation）；下单时点用 quantfox next-confirm 推净值确认日。`

**fund-screener 第 0 步（插在现第 0.5 步之前）**——按 yield-seeker spec §1-2 压缩为固定文本：

```markdown
## 第 0 步 · 诉求校准与风偏探测（对话内完成，不发问卷）
- **预期校准**：用户报收益诉求时先对阶梯表——货基/纯债 2-4%、固收+ 4-8%、均衡混合 8-15%、行业进攻 15%+（皆为长期年化量级、非承诺）。诉求超出对应风险等级的承受力时当面点破"高收益+高概率+短期"互斥。
- **风偏探测**：从对话信号判断（亏过多少会睡不着/持有过什么/期限多长），据此定 --style（steady/balanced/momentum/pullback）与债股比，不问问卷式问题。
- 校准结论一句话复述给用户确认后再进筛选。
```

**fund-analyze 第 4 步后补一句**：`证据卡 name_theme_mismatch=true → 点明名实不符，舆情按 holdings.theme_guess 主题搜。`

**测试**：`test_framework.py` 版本断言 16、关键词加 `name_theme_mismatch`、`theme_guess`；`test_skill_file.py` 矩阵 keywords 的 `"v15"` 改 `"v16"`，另加断言 fund-screener 含 `诉求校准`、fund-analyze 含 `theme_guess`。

- [ ] **Step 1: 改测试 RED → Step 2: 实现文本 → Step 3: GREEN + 全量 + Commit**

```bash
git add quantfox/prompts/analysis_framework.md skills/ tests/test_framework.py tests/test_skill_file.py
git commit -m "feat(framework): v16 — flags/theme consumption rules, market regime pointer; screener step-0 expectation calibration"
```

---

### Task 8: 端到端验收 + 真实冒烟 + 状态文件

- [ ] **Step 1**: `uv run pytest -q` 全绿（贴总数）。
- [ ] **Step 2 真实冒烟（需网络，尽力而为，失败如实报）**：`uv run quantfox market`（贴 regime_line 与 health）；`uv run quantfox market --brief`；`uv run quantfox next-confirm`；`uv run quantfox evidence <任一持仓代码> --format json | python3 -c "import json,sys; c=json.load(sys.stdin); print(c['schema_version'], c.get('name_theme_mismatch'), (c['profile'].get('holdings') or {}).get('theme_guess'))"`；`uv run quantfox gold-report`（确认头部 regime 行变化）。
- [ ] **Step 3**: `docs/task.md` P3a 条目（做了什么一句话块）；后续列表更新（P3b：ETF+llm 待做）。
- [ ] **Step 4**: Commit `docs: mark P3a done` + push origin main + 收尾四件报告。

---

## Self-Review 记录

- **Spec 覆盖（P3a 范围）**：W1 C3→T1、C4→T2、C5→T3、SOP→T7；W2→T4+T5；W5→T6；框架 v16→T7；验收→T8。W3/W4 明确属 P3b。
- **类型一致**：themes.guess_theme/name_theme_mismatch 在 T1/T7 引用一致；build_market_view fetchers 键与 T4 测试注入一致；events sources/cache 签名 T6 内闭环；schema 2.2 在 T1 与 T8 冒烟断言一致。
- **占位符**：T4/T5/T6 的测试以断言清单+构造要求给出且明确"每条落成可执行 assert"；接口探测（akshare 具体函数）授权实现时决策、两个方向（成功接线/降级弃权）语义都已写死。
