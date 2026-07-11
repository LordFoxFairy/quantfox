# Quantfox P3b（ETF 场内全链路 + patrol --llm）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 spec `docs/superpowers/specs/2026-07-11-quantfox-p3-market-etf-design.md` 的 W3（ETF/LOF 场内全链路）与 W4（`patrol --llm` 触发式深分析）。

**Architecture:** `etf` 作为第三资产类型贯穿 resolve→prices→cost→记账→intraday→universe/screen→gold-report 第六榜→patrol；llm 深分析是独立模块 `llm_review.py`（subprocess 调 `claude -p`，全注入可测），patrol 只做门控接线。

**Tech Stack:** 现有栈；不新增依赖（claude CLI 是运行时可选外部命令，缺失即降级）。

## Global Constraints

- 基线：动手时的 `uv run pytest -q` 全绿数为准（P3a 收官 ≈207±），每任务后全量重跑全绿。
- 测试零网络、零真实家目录、绝不真调 `claude` CLI（subprocess 注入 fake）。
- 隐私铁律照旧；中文文案英文代码；commit 尾 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- ETF 语义诚实：跨境 T+0 品种不确定处如实说；费用是近似模型要注明。
- 既有场外基金/黄金行为零回归（resolve 对普通 6 位码仍返回 otc_fund）。

---

### Task 1: resolve 支持 etf 资产类型

**Files:**
- Modify: `quantfox/data/resolve.py`
- Test: `tests/test_resolve.py`（追加）

**Interfaces:**
- Produces: `AssetType = Literal["otc_fund", "gold", "etf"]`；`Asset` 增可选字段 `market: Optional[Literal["SH", "SZ"]] = None`（仅 etf 填）。识别规则：
  - 显式：`etf:512880`、`512880.SH`/`512880.SZ`（大小写不敏感；symbol 存 6 位码，market 由后缀或前缀定）。
  - 前缀启发（无显式标注时）：`50/51/52/53/56/58` 开头 → etf/SH；`15` 开头 → etf/SZ；`16` 开头 → etf/SZ（LOF 按场内口径）。
  - 其余 6 位 → otc_fund（现行为不变）。
  - `etf:` 前缀给了但代码非 6 位 → ValueError。

- [ ] **Step 1: 失败测试**（追加 `tests/test_resolve.py`，先读现有测试风格）

```python
def test_etf_prefix_heuristics():
    from quantfox.data.resolve import resolve

    a = resolve("512880")
    assert a.type == "etf" and a.market == "SH" and a.symbol == "512880"
    assert resolve("159915").type == "etf" and resolve("159915").market == "SZ"
    assert resolve("501018").type == "etf"  # 50 开头 LOF 场内口径
    assert resolve("161725").type == "etf" and resolve("161725").market == "SZ"


def test_etf_explicit_overrides():
    from quantfox.data.resolve import resolve

    assert resolve("etf:002611").type == "etf"      # 显式覆盖前缀启发
    a = resolve("512880.sh")
    assert a.type == "etf" and a.market == "SH" and a.symbol == "512880"
    assert resolve("159915.SZ").market == "SZ"


def test_otc_fund_unchanged():
    from quantfox.data.resolve import resolve

    a = resolve("002611")
    assert a.type == "otc_fund" and a.market is None


def test_etf_bad_code_raises():
    import pytest

    from quantfox.data.resolve import resolve

    with pytest.raises(ValueError):
        resolve("etf:abc")
```

注意：`501018` 是历史测试里用过的场外样例码吗？先 `grep -rn "501018" tests/ quantfox/`——若它在既有测试中作为 otc_fund 使用，会被前缀启发改判为 etf 而破坏既有测试。**处理规则**：50 开头的 LOF 确实是场内码，既有用例若受影响，把既有用例的样例码换成不受启发影响的（如 002611/110022），在报告中说明；`quantfox` 各 CLI help 文本中的样例码同查同改。

- [ ] **Step 2: RED → 实现**

```python
AssetType = Literal["otc_fund", "gold", "etf"]
_ETF_SH_PREFIXES = ("50", "51", "52", "53", "56", "58")
_ETF_SZ_PREFIXES = ("15", "16")


class Asset(BaseModel):
    symbol: str
    name: Optional[str] = None
    type: AssetType
    market: Optional[Literal["SH", "SZ"]] = None


def _etf_market(code: str) -> str:
    return "SH" if code.startswith(_ETF_SH_PREFIXES) else "SZ"


def resolve(query: str) -> Asset:
    q = query.strip()
    if q.lower() in _GOLD:
        return Asset(symbol="Au99.99", type="gold", name="黄金Au99.99")
    low = q.lower()
    if low.startswith("etf:"):
        code = q[4:].strip()
        if not re.fullmatch(r"\d{6}", code):
            raise ValueError(f"etf: 后须接 6 位代码: {query!r}")
        return Asset(symbol=code, type="etf", market=_etf_market(code))
    m = re.fullmatch(r"(\d{6})\.(sh|sz)", low)
    if m:
        return Asset(symbol=m.group(1), type="etf", market=m.group(2).upper())
    if re.fullmatch(r"\d{6}", q):
        if q.startswith(_ETF_SH_PREFIXES) or q.startswith(_ETF_SZ_PREFIXES):
            return Asset(symbol=q, type="etf", market=_etf_market(q))
        return Asset(symbol=q, type="otc_fund")
    raise ValueError(f"无法识别的标的: {query!r}（支持 6 位基金代码、etf:代码、代码.SH/.SZ 或 '黄金'/'gold'）")
```

- [ ] **Step 3: GREEN + 全量（修复受前缀启发影响的既有样例码）+ Commit**

```bash
git add quantfox/data/resolve.py tests/test_resolve.py
git commit -m "feat(resolve): etf asset type with prefix heuristics and explicit overrides"
```

---

### Task 2: ETF 日线取数 + profile 不适用 + 证据卡 pass-through

**Files:**
- Modify: `quantfox/data/prices.py`（etf 分支）、`quantfox/data/fund_profile.py`（etf → `{"applicable": False}`）
- Test: `tests/test_prices.py`、`tests/test_evidence.py`（追加）

**Interfaces:**
- Produces: `load_prices(asset)` 对 `asset.type == "etf"` 走 etf fetcher（生产：真实探测 akshare `fund_etf_hist_em(symbol=code, period="daily", adjust="qfq")` 类接口，选稳者；**用后复权价保证收益/回撤跨分红正确，docstring 注明**），输出规范化 date/value(+OHLC 若可得) 与现有格式一致；`load_profile(asset)` 对 etf 返回 `{"applicable": False}`（evidence 的 profile 段自然 n/a）。
- 既有 `_normalize_*` 复用；注入 fetcher 参数模式与现有一致。

- [ ] **Step 1: 失败测试**：注入 fake etf df（含开高低收列名按所选接口真实列名——实现者探测后以真实列名写 fixture 并在注释注明接口名）断言规范化输出；`build_evidence` 对 etf asset + 该 prices 出卡（profile n/a、metrics/percentile/flags 正常、schema 2.2）。
- [ ] **Step 2: RED → 实现（含真实接口探测，探测结果如实写报告）→ GREEN + 全量 + Commit**

```bash
git add quantfox/data/prices.py quantfox/data/fund_profile.py tests/test_prices.py tests/test_evidence.py
git commit -m "feat(etf): daily prices via adjusted close, profile n/a, evidence pass-through"
```

---

### Task 3: ETF 费用模型 + 记账即时确认

**Files:**
- Modify: `quantfox/storage.py`（`round_trip_cost` etf 分支）、`quantfox/cli.py`（`watch_buy` etf 跳过日历）
- Test: `tests/test_storage.py`、`tests/test_watch_cli.py`（追加）

**Interfaces:**
- `round_trip_cost(h, "etf")` = `0.0015`（双边佣金万2.5×2 + 价差冲击近似 0.1%，与持有期无关；docstring 注明是近似模型）。
- `watch buy <etf码> --amount --nav <成交价>`：`confirm_date = entry_date`（即时确认，不走 15:00 cutoff）；不带 `--nav` 时对 etf 直接 `BadParameter("场内 ETF 请提供成交价 --nav（券商成交回报）")`——场内成交价只有用户知道，不猜。
- `watch expect/reconcile/patrol` 语义不变（etf 持仓走同一状态机）。

- [ ] **Step 1: 失败测试**：cost etf 分支两断言（h=5 与 h=250 同为 0.0015）；CLI etf buy with nav → confirm_date==entry_date 且不调 calendar（monkeypatch trade_dates 为 raise 的 boom 证明未咨询）；etf buy without nav → exit≠0 且文案含 "--nav"。
- [ ] **Step 2: RED → 实现 → GREEN + 全量 + Commit**

```bash
git add quantfox/storage.py quantfox/cli.py tests/test_storage.py tests/test_watch_cli.py
git commit -m "feat(etf): flat round-trip cost model and instant-confirm bookkeeping"
```

---

### Task 4: ETF 盘中行情

**Files:**
- Modify: `quantfox/intraday.py`（`etf_intraday(spot_df, code) -> dict`）、`quantfox/cli.py`（`intraday` 命令 etf 分支）、`quantfox/patrol.py`（`run_intraday_patrol` 对 etf 用 etf_intraday，阈值沿用 ±2%）
- Test: `tests/test_intraday.py`、`tests/test_patrol.py`（追加）

**Interfaces:**
- `etf_intraday(spot_df, code)`：从 `fund_etf_spot_em` 全表 df 里取该 code 行 → `{"available": True, "price": float, "pct_change": float(小数), "name": str}`；无该行 → `{"available": False}`。生产接线在 cli/patrol 的取数分支（真实探测列名）。
- patrol intraday 对 etf 持仓：`_intraday_estimate` 内部按 asset.type 分派（etf → etf_intraday；otc_fund → 现有基金估算；gold 不变）。

- [ ] **Step 1: 失败测试**（fake spot df 两行，取行/缺行；patrol intraday 注入 etf 持仓超阈值触发 `intraday_move`）→ **Step 2: RED → 实现 → GREEN + 全量 + Commit**

```bash
git add quantfox/intraday.py quantfox/cli.py quantfox/patrol.py tests/test_intraday.py tests/test_patrol.py
git commit -m "feat(etf): intraday spot quotes wired into intraday command and patrol"
```

---

### Task 5: ETF universe + `screen --etf`

**Files:**
- Create: `quantfox/data/etf_universe.py`
- Modify: `quantfox/cli.py`（`screen` 加 `--etf` 分支）
- Test: `tests/test_etf_universe.py`（新建）

**Interfaces:**
- `load_etf_universe(fetcher=None, min_turnover=50_000_000) -> pd.DataFrame`：列 `code/name/price/pct_change/turnover`（元）；流动性过滤 `turnover >= min_turnover`；生产 fetcher 真实探测 `fund_etf_spot_em`（列名以实测为准，报告注明）。
- `screen --etf [--top 20]`：universe → `metrics_batch([codes])`（etf 走 Task 2 的价格链路）→ 按卡玛降序 top，输出含五列+flags+turnover；与既有 `screen`（场外）互斥使用（给了 --etf 忽略 type/style 参数并提示）。

- [ ] **Step 1: 失败测试**（注入 universe fetcher + monkeypatch metrics_batch：过滤、排序、flags 透传、--etf 输出 JSON 形状）→ **Step 2: RED → 实现 → GREEN + 全量 + Commit**

```bash
git add quantfox/data/etf_universe.py quantfox/cli.py tests/test_etf_universe.py
git commit -m "feat(etf): liquidity-filtered universe and screen --etf calmar ranking"
```

---

### Task 6: gold-report 第六榜「ETF 精选」

**Files:**
- Modify: `quantfox/gold_report.py`（`build_etf_board(etf_universe_df, pool_metrics, top=10) -> list[dict]`——卡玛降序、行含公共列+turnover）、`quantfox/gold_report_render.py`（第六榜渲染 + `_BOARD_LABELS` 加 etf；issues 归档 board="etf"；ETF 数据整体失败 → 该榜省略 + health 注明）、`quantfox/cli.py`（gold-report 组装 etf 榜：load_etf_universe → 取 top~30 流动性池 → metrics_batch → build_etf_board；任何异常 → etf_board=None）
- Test: `tests/test_gold_report.py`、`tests/test_gold_render.py`（追加）

**要点**：assemble 增可选注入 `etf_board=None`（与 holdings_fn 同模式——CLI 组装，assemble 纯注入）；榜行复用五榜公共列语义；回看机制自动覆盖（issues board="etf"）。

- [ ] **Step 1: 失败测试**（build_etf_board 排序/过滤/top 截断；assemble 带 etf_board → HTML 含「ETF 精选」+ issues 落库含 board etf；不带 → 榜省略）→ **Step 2: RED → 实现 → GREEN + 全量 + Commit**

```bash
git add quantfox/gold_report.py quantfox/gold_report_render.py quantfox/cli.py tests/test_gold_report.py tests/test_gold_render.py
git commit -m "feat(gold-report): sixth board ETF selection with liquidity pool and issue archive"
```

---

### Task 7: SOP/skill 文本——ETF 适用范围

**Files:**
- Modify: `skills/fund-analyze/SKILL.md`（frontmatter description 的"只适用于场外基金与黄金；A股个股…不在范围"改为"适用于场外基金、黄金与场内 ETF/LOF；A股个股、加密货币不在范围"；正文加一段场内语义：成交价即确认、无申赎费用佣金近似、跨境 T+0 品种不确定处如实告知）
- Modify: `skills/fund-watch/SKILL.md`（记账 bullet 补 etf：`watch buy <etf> --amount --nav <成交价>` 即时确认）
- Modify: `skills/fund-screener/SKILL.md`（提 `screen --etf` 一句）
- Modify: `quantfox/prompts/analysis_framework.md`（「产物与留痕铁律」个性化条后追加一句：`场内 ETF：成交价即确认无 T+1 悬挂；费用为近似模型（佣金+价差~0.15%）；跨境 T+0 品种交割语义不确定处必须如实告知。`——version 保持 16 不 bump）
- Test: `tests/test_skill_file.py`（追加断言：fund-analyze 含 `ETF`、fund-watch 含 `成交价`、fund-screener 含 `screen --etf`）

- [ ] **Step 1: 测试 RED → Step 2: 文本实现 → GREEN + 全量 + Commit**

```bash
git add skills/ quantfox/prompts/analysis_framework.md tests/test_skill_file.py
git commit -m "docs(skills): ETF applicability and onsite semantics across analyze/watch/screener + framework note"
```

---

### Task 8: W4 `patrol --llm` 触发式深分析

**Files:**
- Create: `quantfox/llm_review.py`
- Modify: `quantfox/patrol.py`（llm 门控）、`quantfox/cli.py`（patrol --llm 接线改真实调用；`schedule install --llm`）、`quantfox/schedule_mac.py`（install(llm=False)：patrol job args 加 --llm）
- Test: `tests/test_llm_review.py`（新建）+ `tests/test_patrol.py`、`tests/test_schedule_mac.py`（追加）

**Interfaces:**
- `llm_review.run_llm_review(alerts: list[dict], evidence_map: dict[str, str], runner=None, timeout=300) -> dict`：
  - `runner(cmd: list[str], input_text: str, timeout: int) -> str`——默认 subprocess 实现（`shutil.which("claude")` 缺失 → raise RuntimeError("claude CLI 不存在")）；测试注入 fake。
  - prompt 模板（写死）：框架铁律约束（禁点数字承诺、看中位、高位看条件化、只给"继续持有/减仓观察/待人工复核"档位）、输入=alerts 摘要+各标的 evidence JSON、要求 ≤300 字中文人话判断。
  - 返回 `{"ok": True, "text": ...}` 或 `{"ok": False, "reason": "缺CLI/超时/非零退出/输出为空"}`——**永不 raise**。
- patrol 门控（`run_patrol` 不动，CLI 层）：`--llm` 且 `new_alerts` 非空 且 `led.latest_alert("_global", "llm_run")` 的 state != today → 跑 llm_review，成功则邮件正文追加「AI 判断（仅供参考，非投资建议）」段 + `add_alert("_global", "llm_run", today, "ran")`；失败降级注明。
- `schedule install --llm`：patrol plist 命令含 `--llm`（默认不含）。

- [ ] **Step 1: 失败测试**（llm_review 三分支：fake runner 成功/超时 raise TimeoutError→ok False/缺 CLI；patrol CLI 门控：有告警+当日首次→runner 调用+邮件含 AI 段+llm_run 落库；同日第二次→不调；无告警→不调；schedule --llm plist 断言）→ **Step 2: RED → 实现 → GREEN + 全量 + Commit**

```bash
git add quantfox/llm_review.py quantfox/patrol.py quantfox/cli.py quantfox/schedule_mac.py tests/test_llm_review.py tests/test_patrol.py tests/test_schedule_mac.py
git commit -m "feat(patrol): gated llm deep review via claude -p with daily dedup and graceful degradation"
```

---

### Task 9: 端到端验收 + 真实冒烟 + 状态文件

- [ ] **Step 1**: 全量 `uv run pytest -q` 全绿（贴总数）。
- [ ] **Step 2 真实冒烟（尽力而为，如实报）**：`uv run quantfox evidence 510300 --format json`（etf 卡：type/market/metrics/flags）；`uv run quantfox forecast 510300 --short 5`；`uv run quantfox screen --etf --top 10`；`uv run quantfox gold-report`（确认第六榜出现或如实弃权）；`uv run quantfox intraday 510300`；若 `which claude` 存在：构造 `--llm` 真实触发一次（用 `uv run quantfox patrol --llm` 在有新告警日；无新告警则注明未触发原因，不硬造）。
- [ ] **Step 3**: `docs/task.md` P3b 条目 + 后续列表（P4：A股个股、对外发布立项）。
- [ ] **Step 4**: Commit `docs: mark P3b done` + push + 收尾四件报告。

---

## Self-Review 记录

- **Spec 覆盖**：W3 资产模型→T1、数据→T2、费用/记账→T3、盘中→T4、universe/screen→T5、第六榜→T6、SOP→T7；W4→T8；验收→T9。spec"evidence profile n/a"在 T2；"patrol etf 同状态机"在 T3/T4 测试。
- **类型一致**：Asset.market 在 T1 定义、T2/T4 消费；etf_intraday 返回形状 T4 内闭环；run_llm_review 契约 T8 内闭环；build_etf_board 行形状与 render 消费一致。
- **占位符**：T2/T4/T5 的真实接口列名授权实现时探测（fixture 用实测列名并注明）；两方向语义（接线成功/降级弃权）都已写死。
- **风险注记**：T1 前缀启发可能改判既有测试样例码（501018 等）——Step 1 已内置排查与处理规则。
