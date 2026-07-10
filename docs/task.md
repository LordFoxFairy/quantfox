# 任务状态

## money 量化分析助手

- [x] **P1 / MVP**（2026-07-08 完成）：数据（场外基金+黄金）+ 技术指标 + 历史分位 + 舆情收集 + 证据卡 + 预测账本/复盘 + 分析框架 + CLI + Claude Skill。
  - 设计：`docs/superpowers/specs/2026-07-08-quantfox-assistant-design.md`
  - 计划：`docs/superpowers/plans/2026-07-08-quantfox-assistant-p1.md`
  - 20 个单测全绿；黄金与基金 501018 真实端到端冒烟通过。

- [x] **多-skill 架构 + 可视化报告**（2026-07-08）：
  - 拆成各自闭环的 skill（挂 quantfox 插件）：`fund-analyze`（取数→四维评分卡+情景分析→可视化报告→存档）、`fund-compare`（多标的对比）+ **保留上游原名直接适配**的 `position-sizer`（仓位/定投）、`portfolio-manager`（组合体检+持仓穿透）、`signal-postmortem`（复盘）——均来自 tradermonty/claude-trading-skills，原名保留便于后续同步上游更新。
  - `quantfox report`：自包含 **ECharts HTML 报告**（K线/净值+回撤+持仓饼+四维评分卡），浏览器打开；已用 Playwright 真实渲染验证。
  - 分析框架 v4：四维评分卡 + Verdict/信心 + Kill criteria（适配自 xvary）。
  - 评估并放弃 quantstats（英文通用、重依赖），主报告用 ECharts。

- [x] **更名 quantfox**（2026-07-09）：包名/CLI/marketplace/全部引用统一改为 quantfox。
- [x] **全市场选基 fund-screener**（2026-07-09）：`quantfox screen` 两级漏斗（长周期加权+一致性打分粗筛→精筛降温反追热）。
- [x] **提准四机制**（2026-07-09）：弃权门槛 + 多周期一致 + 反方验证（框架 v6）+ 信心校准表（`storage.calibration()` / `quantfox calibration`）。
- [x] **大盘估值锚**（2026-07-09）：`quantfox market-valuation`（全A股近10年估值分位），框架 v7 纳入判断。
- [x] **报告离线化**（2026-07-09）：内联 echarts.min.js，报告为零外部依赖单文件，Playwright 验证渲染正常；并加"情景分析"板块。

- [x] **诚实修正 + 历史回测**（2026-07-09，回应两位大佬 code review）：
  - outcome 扣交易成本、edge_vs_baserate 去牛市虚高、幸存者偏差警示、框架 v8 重定 KPI（见前）。
  - **`quantfox backtest`**：机械规则基线回测（valuation/trend/combo），point-in-time + 扣成本 + 对比基率与买入持有 + 策略夏普/回撤——**上线前就有的样本外战绩基线**（非 LLM 判断的回测，LLM 应超越）。
  - 修 bug：log-signal 的 schema_version 与证据卡对齐（2.0）；新增 `--evidence-file` 冻结证据快照，fund-analyze SOP 存档时传入。

- [x] **专家二轮 code review 修复**（2026-07-09）：回测收益虚高、结算 start=0 污染、信心 0-1/0-100 口径、回撤低估补日度、净值 staleness、schema 版本、证据快照冻结。
- [x] **回测背书门槛 + 中长期导向**（2026-07-09）：框架 v9 出手前须 backtest 背书；v10 定位"中长期(最短1月)、目标高概率正收益不亏"，默认周期 20/60/120/250。
- [x] **持仓监控 fund-watch**（2026-07-09）：opt-in 清单（`quantfox watch add/list/remove/check`）+ 触发式监控（浮亏/回撤/跌破MA60=需关注，估值高位=软提示），中长期少动、平时沉默；定时由用户自行 /schedule，不擅自建。共 7 skill。
- [x] **P1 一致性+全局统一+mandate+对账留痕**（2026-07-10，spec/plan 见 docs/superpowers/）：
  config.json 统一配置（email.json 自动迁移、0700/0600 权限）；mandate-lite（`quantfox mandate set/show`，7 skill 第0步）；
  框架 v14 诚实铁律唯一出处 + 7 skill 同步 + grep 矩阵测试；交易日历 15:00 cutoff 自动确认日、pending lot、
  `watch confirm/expect/reconcile` + append-only reconciliations 留痕；output/ 清理入 ~/.quantfox，遗留稿归档 docs/reference。

- [x] **P2 监控闭环**（2026-07-11，spec：`docs/superpowers/specs/2026-07-10-quantfox-p2-monitoring-design.md`；plan：`docs/superpowers/plans/2026-07-10-quantfox-p2-monitoring.md`）：
  共享模拟器 `simulate_paths`+`forecast --short`；DataHealth-lite 数据新鲜度守护；`alerts`/`report_issues` 留痕表；
  launchd 本机调度（`quantfox schedule install/status`，睡眠错过由 launchd 唤醒后补跑）；
  `quantfox gold-report` 全景淘金周报（五榜+扇形图+回看+事件日历尽力而为，PDF 自动生成）；
  `quantfox patrol` 持仓巡检（六类告警去重+自动补记 pending lot+盘中可选+`--llm` 存根）；分析框架 v15。
  全量测试 173 passed / 1 skipped；真实周报冒烟（PDF 860KB）、真实巡检冒烟（8 条新增告警落库）、
  `schedule install`+`status` 均已在本机验证通过。

### 后续（未开始）
- [ ] **P3**：正式对外发布；A 股市场层 + ETF 覆盖；llm 深分析（当前 `--llm` 为存根）；事件日历多源（当前仅尽力而为单源）。
- [ ] **yield-seeker SOP 落地**（2026-07-10 晚会话沉淀）：fund-screener 加"诉求校准/风偏探测"前置章节 + 引擎 C1(metrics-batch)/C2(假稳flags)/C3(名实核对)/C4(forecast小样本警示)/C5(确认日helper)——设计见 `docs/superpowers/specs/2026-07-10-yield-seeker-sop-design.md`。
- [ ] review 口径细分（买入胜率 vs 回避胜率 vs 策略净值胜率）——回测已按此口径，live review 可跟进。
- [x] price_ref_date 对齐场外基金 T+1 —— P1 已建 calendar_cn + watch buy 自动确认日（2026-07-10）。
- [x] **P2**：headless `--llm`（无人值守分析）—— `quantfox patrol --llm` 已实现（存根版，深分析留 P3）。
- [ ] 参考池（P3/P4 设计时按需摘取，不整体引入）：Qlib（ML 选股工作流）/ Backtrader（回测模式）/ easy-fund 类（指标查漏：詹森/信息比率）/ FinNLP·FinGPT（数据清洗流程）。CTA 期货+杠杆与保本优先冲突，未立项。

- [x] **发布结构**（2026-07-08）：改造成标准 Claude Code plugin marketplace——根目录 `.claude-plugin/marketplace.json`，skill 位于顶层 `skills/fund-analyze/`。
- [x] **专业化重构**（2026-07-08）：
  - 指标改为库化（`ta`），不再手撸；加指标=加一行。
  - 新增**风险绩效** `metrics.py`（夏普/索提诺/卡玛/VaR/CVaR/回撤/CAGR/胜率/偏峰度，两资产可算）。
  - 新增**专业基本面** `fund_profile.py`（基金经理/持仓/评级/规模费率）——引擎真正的护城河。
  - 技术指标**降级为辅助**；证据卡以 profile + metrics + 估值分位为主。
  - **删除 news 引擎**：舆情由 CC agent 用 WebSearch 自搜自判。
  - SKILL.md 重写为**专业分析 SOP**；分析框架 v3 定优先级（它是什么→贵不贵→险不险→靠不靠谱→风往哪吹→技术面辅助）。

### 2026-07-09 新增（更名后）
- 更名 quantfox；全市场选基 fund-screener；提准四机制（弃权/多周期/反方/校准）；回测背书门槛；大盘估值锚 market-valuation；离线可视化报告（内联 ECharts）+ 情景板块。
- 两态监控 fund-watch：观测(找买点)/持有(看离场)；持有分"提前预警(留意)/确认离场(需离场)"，重在跌之前示警。
- 邮件推送 `quantfox email`（用户自配 SMTP、本地存储权限600）。
- 专家二轮 review 修复：回测收益虚高、结算 start=0、信心口径、回撤日度、staleness、schema、证据快照；复盘收益改从实际可成交净值起算（T+1）、按买入/回避拆口径；框架 v11 必输出买卖时机+持有期+粗略收益区间。
- 项目文件夹 money→quantfox 更名后重建 venv，54 测试全绿。

### 已知待办
- [x] 推到 GitHub：`https://github.com/LordFoxFairy/quantfox.git`（进行中）。
- [ ] 打包时确保 `quantfox/prompts/*.md`、`skills/**` 随分发（当前 `uv run` 从源码读取正常）。
- [ ] 基金"名称→代码"解析（当前仅支持 6 位代码或"黄金"）。
