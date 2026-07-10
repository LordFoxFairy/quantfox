# Quantfox P2 设计：监控闭环（全景淘金周报 + 持仓巡检 + 共享模拟器）

- 日期：2026-07-10
- 状态：用户全权委托，已定案
- 前置：P1 已合入（HEAD 1a80742）；C1 `metrics-batch` 与 C2 假稳 `flags` 已实现

## 0. 已定决策（不再讨论）

| 决策点 | 结论 |
|---|---|
| 推送通道 | 本期只用邮件（已有 QQ 邮箱配置）；通道层留一个 `notify_send()` 薄封装作扩展点，不做新集成 |
| 巡检驱动 | 纯引擎判据（触发才发邮件，平时沉默）；CC headless 深分析只预留 `--llm` 参数位（本期报"未实现"），不实现 |
| 定时载体 | 本地 launchd（云端 /schedule 摸不到本地 `~/.quantfox`，不可用）；Mac 睡眠不跑，launchd 唤醒后补跑 |
| 周报节奏 | 每周五 21:30；持仓巡检每交易日 21:35；盘中巡检（可选装）交易日 14:30——15:00 cutoff 前还来得及操作 |
| 报告口径 | 全类型（含债基）、每类 top-10、邮件附 PDF（QQ 邮箱不跑 JS） |
| 事件日历 | 尽力而为：akshare 宏观日历接口可用则周报加"下周事件"节，探测不稳则整节省略并在报告注明——绝不编数据 |

## 1. 共享组件（三个，先建）

### 1.1 路径模拟器 `simulate_paths()`（`quantfox/forecast.py` 内新增）

周报 250 日扇形图与巡检/对话 5-7 日波动锥共用同一引擎：

```python
def simulate_paths(prices: pd.DataFrame, horizon_days: int, n_paths: int = 1000,
                   block: int = 20, conditional_pct: float | None = None,
                   seed: int = 20260710) -> dict
```

- 从历史日收益做**块状自助抽样**（moving block bootstrap，block=20 保留波动聚集）拼接出 `n_paths` 条未来 `horizon_days` 逐日路径。
- `conditional_pct` 给定（当前估值分位）时，抽样块的起点限于历史估值分位在 `±0.15` 邻域内的时段；符合条件的历史日 <250 个则**自动降级为无条件**并在返回里置 `degraded_to_unconditional: true`。
- 固定 seed（可复现）；返回逐日百分位矩阵：`{"days": [1..H], "p10": [...], "p25": [...], "p50": [...], "p75": [...], "p90": [...], "prob_positive_terminal": float, "n_paths", "conditional": bool, "degraded_to_unconditional": bool}`（值为相对当前净值的累计收益率小数）。
- 输入不足 500 个交易日 → 返回附 `warning: "样本不足，仅供参考"`；不足 120 日 → 返回 `None`（诚实弃权）。

CLI：`quantfox forecast <code> --short 5` → 用 `simulate_paths(horizon_days=5)` 输出逐日 p10/p25/p50/p75/p90 + 本周正收益概率，JSON；文案里固定一行水印：**“历史统计推演，非预测承诺”**。估值分位 >0.85 时自动带 `conditional_pct`。

### 1.2 DataHealth-lite（`quantfox/health.py` 新建）

- 纯数据结构 + 聚合函数：每次批量取数（周报扫描、巡检取价）逐标的记 `{"symbol", "status": "ok"|"stale"|"failed", "as_of": 最新净值日, "note"}`。
- `summarize_health(items) -> dict`：`{"ok": n, "stale": n, "failed": n, "healthy": bool}`；**只要有 failed 或 stale，healthy=false，任何摘要/报告头部必须显示明细行，禁止输出"一切正常"**（框架 v14 落库留痕铁律的邻条，本期写进框架 v15 一句话）。
- stale 判定：最新净值日早于最近一个交易日（用 calendar_cn）。

### 1.3 本地调度 helper（`quantfox/schedule_mac.py` 新建）

- `quantfox schedule install [--intraday]` / `uninstall` / `status`：生成/删除/检查 `~/Library/LaunchAgents/` 下三个 plist：
  - `com.quantfox.weekly.plist`：周五 21:30 → `quantfox gold-report --email`
  - `com.quantfox.patrol.plist`：周一至五 21:35 → `quantfox patrol --email`
  - `com.quantfox.intraday.plist`（仅 --intraday 装）：周一至五 14:30 → `quantfox patrol --intraday --email`
- plist 用 `StartCalendarInterval`；执行体为 `bash -lc "<uv tool 安装的 quantfox 绝对路径> ..."`（install 时探测 `shutil.which("quantfox")`，找不到则报错提示先 `uv tool install`）；日志重定向 `~/.quantfox/logs/<name>.log`。
- `status` 输出每个 plist 是否存在 + `launchctl list` 是否加载 + 最近一次日志尾行。
- 非 macOS 平台：命令直接报"仅支持 macOS，请自行 cron"并给出等价 crontab 行。

### 1.4 告警去重状态（`storage.py` 加 `alerts` 表，append-only）

```text
alerts(id INTEGER PK, symbol TEXT, kind TEXT, state TEXT, message TEXT, created_at TEXT)
```

- kinds：`exit_signal / early_warning / valuation_high / pending_confirm / reconcile_mismatch / data_failure`。
- 巡检对每个 (symbol, kind) 算出当前 state（如 `triggered`/`clear`），与该组合**最近一条**比对：状态变化才追加新行并计入本次邮件；状态未变沉默。`Ledger.latest_alert(symbol, kind)`、`Ledger.add_alert(...)`。

## 2. 全景淘金周报 `quantfox gold-report [--email] [--top 10]`

产物：自包含 HTML（交互 ECharts）+ PDF → `~/.quantfox/reports/gold/gold_YYYY-MM-DD.html/.pdf`。

**头部四件套**：大盘估值 regime（market-valuation）、DataHealth 行（1.2，含 stale/failed 明细）、今日金矿摘要（五类各第一名+一句话理由）、免责+幸存者偏差警示。

**数据管线（一次扫描共用）**：对 5 个类型（股票型/混合型/债券型/指数型/QDII）各拉一次 `load_universe`；按各榜准入条件在 rank 列上粗筛出候选池（合计 ≤80 只）；对候选池跑一次 `metrics_batch()`（含 C2 flags）；`metrics_batch` 输出本期**新增一列 `dist_from_52w_high`**（现价距 52 周高点回撤幅度，从已拉净值序列计算，不增加请求）。

**五类榜单（每类 top-10）**：

| 榜 | 准入 | 排序键 | 特别列 |
|---|---|---|---|
| 潜力榜 | `screen(style=balanced)` 既有管线（多周期一致+动能不过热） | 深筛分 | overheated 拥挤警示 |
| 高收益榜 | 1 年收益 top（**特意保留**，满屏警示） | 1 年收益 | 回撤/追高风险标红 |
| 稳健榜 | 候选池内夏普/卡玛 Pareto 非支配集 | 卡玛 | 最大回撤 |
| 回调捡漏榜 | 卡玛 >0.5 且 `dist_from_52w_high` >15% | 打折深度×卡玛 | 距高点跌幅、MA20>MA60 企稳标记 |
| 防守底仓榜 | 债券型且 flags 为空（过假稳三查） | 年化波动升序 | flags 列（有 flag 的展示但沉底标红） |

每张表公共列：估值分位（>0.85 标红）、C2 flags、名实提示（基金名含行业词但该词不在其主题分类时标 `名实待核`——纯字符串启发，不拉持仓）。

**预测曲线**：每榜 top-3 配完整扇形图（历史净值 + `simulate_paths(250)` 的中位路径 + p10/p90、p25/p75 双走廊，悬停"第X天：中位+Y%，80%区间[A,B]"）；其余 7 只每只一条 60 日中位迷你线。估值分位 >0.85 的用条件化采样，降级时图上标注。每图水印：“历史统计推演，非预测承诺”。

**战绩回看（自我打脸机制）**：每期把五榜成分落库——`ledger.db` 新表：

```text
report_issues(id INTEGER PK, issue_date TEXT, board TEXT, rank INTEGER,
              symbol TEXT, name TEXT, nav_at_issue REAL, created_at TEXT)
```

出报告时读取**上一期** issue，对每只算期间实际收益，报告尾部渲染"上期榜单回看"表（含五榜平均 vs 各自基准说明）；首期无上期则该节显示"首期，无回看"。

**事件日历（尽力而为）**：`quantfox/data/events_cn.py` 探测 akshare 宏观日历接口（实现时从 `ak.news_economic_baidu` 类接口试起）；拉取成功 → "下周事件"节列日期+事件名；任何异常 → 整节省略并在 DataHealth 行注明"事件日历不可用"。不做缓存不做重试，失败即弃权。

**邮件**：`--email` 时发 PDF 附件，标题 `[quantfox周报] MM-DD 五类Top10 + 预测曲线`。

## 3. 持仓巡检 `quantfox patrol [--email] [--intraday] [--llm]`

**收盘巡检（默认模式，每交易日 21:35）**，对 watch 清单逐标的：

1. 取价并记 DataHealth；取价失败 → kind=`data_failure` 告警（状态变化才发）。
2. 复用 `monitor.check_holding/check_candidate` → `exit_signal`（需离场）/ `early_warning`（留意）。
3. 估值分位 >0.85 → `valuation_high` 软提示。
4. 有 pending lot 且确认日净值已出 → **自动 `fill_lot` 补记**并在摘要报告；净值仍未出且已过确认日 2 个交易日 → `pending_confirm` 告警。
5. 自动跑 `watch expect` 落库当日预期（复用 P1）；最近一条 reconcile 为 mismatch → `reconcile_mismatch` 提醒。
6. 汇总：有新告警 → 发邮件（纯文本，标题 `[quantfox巡检] MM-DD N条新信号`，正文含 DataHealth 行 + 各告警 + 当日预期收益表）；无新告警 → 沉默（不发"报平安"邮件；周报里自带持仓小节兜底可见）。
7. 周五巡检额外：对每只持仓跑 `simulate_paths(5, conditional)` 波动锥，中位显著转负（p50 < −1%）→ 计入摘要（不单独告警 kind，进邮件正文）。

**盘中巡检（`--intraday`，可选装，14:30）**：复用 `intraday` 命令的官方盘中估值/黄金实时价；单日估算涨跌超 ±2% 或黄金现货超 ±1.5% → 发一封简短邮件（同样走 alerts 去重：kind 复用 `early_warning`，state 带日期避免同日重复）。盘中数据仅提示，不落 reconciliations。

**`--llm`**：本期直接输出 `{"error": "llm 深分析未实现，预留参数位（P3）"}`。

**周报持仓小节**：gold-report 固定含"我的持仓"一节（position + 最近对账 verdict + 5 日波动锥缩略），让每周至少有一次全景可见。

## 4. 框架 v15（一句话增补）

`analysis_framework.md` version 14→15：「产物与留痕铁律」追加一条——**数据健康必须如实呈现：任何摘要/报告只要存在取数失败或 stale，禁止表述为"一切正常"，必须列明细**。7 个 SKILL.md 的共享段出处行改为 v15（文字不变，仅版本号）。

## 5. 非目标（本期不做）

- 新推送通道（Bark/微信/Telegram）；CC headless 自动深分析（仅参数位）；A股/ETF（P3）；盘中高频轮询（一天一次 14:30 已是上限）；事件日历的缓存/重试/多源。

## 6. 测试与验收

- 全量 `uv run pytest -q` 全绿（基线 132+1skip）。
- simulate_paths：固定 seed 可复现；条件化降级路径；样本不足弃权；短序列 None。
- health：stale/failed 判定（注入 calendar）；healthy=false 语义。
- alerts：状态变化才追加；同状态沉默；append-only。
- gold-report：注入 fake universe/prices 出全五榜；issues 落库；第二期能算回看；DataHealth 行出现在 HTML。
- patrol：fake 数据下 exit/early/valuation/pending/mismatch 五类告警触发与去重；无新告警不发邮件（mock send_email 断言未调用）；pending 自动补记。
- schedule_mac：plist 生成内容断言（不真 launchctl load，测试只验文件与 XML 字段）；非 mac 报错文案。
- 真实冒烟（需网络，尽力而为）：`gold-report`（不 --email）生成 HTML+PDF 并 Playwright 验证渲染；`patrol` 对真实持仓跑一遍（只读+expect 落库）。
- 隐私铁律：测试全用合成数据；报告产物只落 `~/.quantfox`。
