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

### 后续（未开始）
- [ ] **P2**：每日 `loop` 定时（headless `--llm`）、回测。
- [ ] **P3**：正式对外发布。

- [x] **发布结构**（2026-07-08）：改造成标准 Claude Code plugin marketplace——根目录 `.claude-plugin/marketplace.json`，skill 位于顶层 `skills/fund-analyze/`。
- [x] **专业化重构**（2026-07-08）：
  - 指标改为库化（`ta`），不再手撸；加指标=加一行。
  - 新增**风险绩效** `metrics.py`（夏普/索提诺/卡玛/VaR/CVaR/回撤/CAGR/胜率/偏峰度，两资产可算）。
  - 新增**专业基本面** `fund_profile.py`（基金经理/持仓/评级/规模费率）——引擎真正的护城河。
  - 技术指标**降级为辅助**；证据卡以 profile + metrics + 估值分位为主。
  - **删除 news 引擎**：舆情由 CC agent 用 WebSearch 自搜自判。
  - SKILL.md 重写为**专业分析 SOP**；分析框架 v3 定优先级（它是什么→贵不贵→险不险→靠不靠谱→风往哪吹→技术面辅助）。

### 已知待办（推广前）
- [ ] 推到 GitHub，把 README 里 `/plugin marketplace add thefoxfairy/money` 换成真实仓库地址。
- [ ] 打包时确保 `quantfox/prompts/*.md` 随 wheel 分发（当前 `uv run` 从源码读取正常）。
- [ ] 基金"名称→代码"解析（当前仅支持 6 位代码或"黄金"）。
