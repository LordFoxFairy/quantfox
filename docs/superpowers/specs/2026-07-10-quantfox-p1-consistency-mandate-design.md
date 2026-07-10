# Quantfox P1 设计：收尾 + 一致性 + 全局统一 + 个性化档案

- 日期：2026-07-10
- 状态：已与用户对齐，待实施
- 前置：`docs/HANDOFF-2026-07-10.md`、`docs/skill-improvements.md`（B7-②/A2 即来自其中）

## 0. 总路线图（本文档只实施 P1）

用户三方向（全面打磨 A股+基金 / 用户能力 / 监控实时分析配合 Claude Code）按价值优先分四期：

| 期 | 内容 | 状态 |
|---|---|---|
| **P1** | 七 skill 一致性（B7-②）+ 自动 T+1 对账留痕（A2）+ 全局家目录规范 + InvestorMandate-lite 个性化档案 | 本设计 |
| P2 | 监控闭环：定时巡检（cron 或 /schedule 驱动 Claude Code headless）、盘中实时、类型化触发告警、DataHealth-lite、手机推送通道 | 待设计 |
| P3 | A股市场层 + ETF/LOF 场内品种：指数/行业估值轮动、场内实时价与 T+0/T+1 语义、screen/forecast/backtest 扩展 | 待设计 |
| P4 | A股个股：筛选/分析/监控新资产线，复用 P3 市场层与 P2 监控管道 | 待设计 |

遗留稿《可信决策核心设计》（1135 行）**不整体实现**，归档为北极星参考，各期按回报摘取（P1 摘 InvestorMandate 字段与"数据失败不得报正常"思想；预注册验证协议、内容哈希、canonical JSON 等企业级机制不落地）。

## 1. 全局家目录规范

**问题**：`~/.quantfox/` 已是事实全局家（`config.data_dir()`，`QUANTFOX_HOME` 可覆盖），CLI 报告已落 `data_dir()/reports`；但配置零散（仅 `email.json`）、skill/agent 无"产物写哪"的明文约定（上一个 agent 把 audit 报告写进了仓库 `output/`）、含 SMTP 授权码的文件权限过宽。分析对话中产生的对账结论也无处持久化（见第 4 节）。

**方案**：

1. **统一布局**（`~/.quantfox/`）：
   - `config.json`：统一配置入口，分节 `smtp`（自 `email.json` 迁移）、`notify`、`prefs`。首次读取时若只有 `email.json` 则自动迁移生成 `config.json` 并保留 `email.json` 兼容读取（只读回退，不再写入）。
   - `mandate.json`：个性化档案（第 2 节）。
   - `ledger.db`：账本（既有，新增表见第 4 节）。
   - `reports/`：全部 HTML/PDF/MD 报告（既有）；audit 类归 `reports/audit/`。
   - `logs/`：P2 巡检日志预留目录，本期只建约定不写代码。
2. **产物落盘铁律**：在 `prompts/analysis_framework.md` 与 7 个 SKILL.md 写入——任何报告、导出、中间产物一律写 `QUANTFOX_HOME`（默认 `~/.quantfox/`），**绝不写进代码仓库**。
3. **仓库清理**：`output/` 下两份 main-audit 报告移入 `~/.quantfox/reports/audit/`（移动不删除）；`.gitignore` 追加 `output/` 与 `.gitwarp/`。
4. **权限收紧**：`data_dir()` 创建时 chmod 0700；`config.json`（含授权码）与 `ledger.db` 写入时 chmod 0600。对已存在文件在下次访问时修正。

## 2. InvestorMandate-lite（个性化档案）

**目标**：用户的本金/目标/风险偏好成为结构化档案，所有 skill 的结论基于它个性化，而非通用报告。字段摘自遗留稿 6.1，去掉一切 validated-模型依赖。

**契约**（`~/.quantfox/mandate.json`，`schema_version: "1.0"`）：

```json
{
  "schema_version": "1.0",
  "mandate_as_of": "2026-07-10",
  "currency": "CNY",
  "total_wealth": 100000.0,
  "deployable_capital": 60000.0,
  "minimum_cash_reserve": 40000.0,
  "target_date": "2027-02-10",
  "target_net_return": 0.08,
  "maximum_loss_amount": 10000.0,
  "maximum_single_instrument_weight": 0.20,
  "maximum_theme_weight": 0.35,
  "excluded_instruments": [],
  "notes": ""
}
```

校验：`total_wealth > 0`；`0 < deployable_capital <= total_wealth`；`target_date > mandate_as_of`；金额字段非负；比率在 (0,1]。字段可部分缺省（除 schema_version 外均可选），缺什么就少个性化什么，不阻断。

**CLI**：
- `quantfox mandate set --total-wealth 100000 --deployable 60000 ...`：写档案（覆盖式，保留上一版为 `mandate.json.bak`）。
- `quantfox mandate show`：显示档案 + 派生量（单标的金额上限 = deployable × max_single_weight 等）。

**Skill 接入**：7 个 SKILL.md 的 SOP 加第 0 步"读 mandate"：
- 有档案 → 结论个性化：仓位建议受单标的/主题上限约束（position-sizer 直接消费）、目标与期限进入 forecast 解读（"你的目标是 7 个月 8%，这只 from_similar_valuation 中位只有 X%"）、排除清单直接剔除。
- 无档案 → 一句话提示可建立，**不阻断**分析，输出通用结论。

## 3. B7-② 七 skill 一致性

**问题**：forecast/看中位/估值闸门等诚实铁律基本只落在 fund-screener 与 fund-analyze，其余 skill 未同步（grep 矩阵见 `skill-improvements.md` B7）。

**方案**：
1. 四条诚实铁律收进 `prompts/analysis_framework.md`（升 v14）作为**唯一出处**：
   - 看中位不看均值（均值被牛市尾部拉高）；
   - 估值闸门：估值分位 > 0.85 剔除/降级，深筛分是相对分 ≠ 能买；
   - 幸存者偏差：榜单/回测顶部天然虚高；
   - forecast 高位必看 `from_similar_valuation`（估值条件化），样本不足（all<60 / conditional<30）不当真。
2. 7 个 SKILL.md 统一加一段"诚实铁律（出处 analysis_framework.md v14）"引用，不各写各的。
3. 补齐 forecast 步骤：`fund-watch`（"这只从当前位置持有/加仓的未来赔率"）、`fund-compare`、`portfolio-manager`（逐持仓 forecast 汇总）。
4. 新增的落盘铁律（第 1 节）与 mandate 第 0 步（第 2 节）同批写入。

**验收**：grep 覆盖矩阵——7 个 SKILL.md ×（中位/估值闸门/幸存者偏差/from_similar_valuation/QUANTFOX_HOME/mandate）全命中；`test_skill_file.py` 扩展为逐 skill 断言关键词。

## 4. A2 自动 T+1 确认 + 对账留痕

**问题一（确认日推算）**：场外基金 15:00 cutoff 与 T+1 确认未建模，成本基历史上靠猜、猜错两次，最后靠用户 App 每日收益反推。
**问题二（结论无处存放，用户实锤痛点）**：对话里算出的"今日预期收益/累计浮盈亏"（示例已脱敏）等对账结论没有持久化，会话一关即失，次日只能重算。

**方案**：

1. **交易日历**：`quantfox/calendar_cn.py`，数据源 akshare `tool_trade_date_hist_sina`（现有依赖），首次拉取后缓存 `~/.quantfox/trade_calendar.json`（含 fetched_at，>30 天自动刷新；拉取失败用缓存并警告，无缓存则要求手动指定确认日，**不静默猜**）。
2. **`watch buy` 自动确认日**：输入金额+下单时间（`--order-at`，缺省当天当前时间）→ 按 15:00 cutoff 与交易日历推确认日 → 取确认日净值折算份额记 lot。`--nav`/`--confirm-date` 仍可手动覆盖；净值尚未公布时提示"确认日 X，净值未出，出值后自动/手动补记"，落一条 pending lot（`nav` 为空，禁止参与成本聚合，`watch position` 明确标注）。
3. **`reconciliations` 表**（append-only，禁 UPDATE/DELETE）：

```text
reconciliations(
  id INTEGER PRIMARY KEY,
  symbol TEXT NOT NULL,
  trade_date TEXT NOT NULL,          -- 净值日
  expected_daily_pnl REAL,           -- 系统预期当日收益（元）
  app_daily_pnl REAL,                -- 用户报的 App 当日收益（元），可空=尚未核对
  delta REAL,                        -- app - expected，可空
  expected_total_pnl REAL,           -- 预期累计浮盈亏
  verdict TEXT,                      -- ok / rounding / mismatch / pending
  note TEXT,
  created_at TEXT NOT NULL
)
```

4. **CLI**：
   - `quantfox watch expect [code]`：按最新净值与 lots 算各持仓"当日预期收益/累计浮盈亏"，**同时落一条 pending reconciliation**。
   - `quantfox watch reconcile <code> --app-profit -20.47 [--date 2026-07-10]`：与当日 expected 比对，|delta|≤0.05 判 ok，≤0.5 判 rounding，否则 mismatch 并提示口径排查（确认日/份额/费率），结果追加落库。
   - `quantfox watch position`：尾部显示最近一次对账（日期/verdict/delta）与 pending lot 提示。
5. **SOP 铁律**：skill 对话中任何"预期收益/对账结论"必须通过 `watch expect` / `watch reconcile` 落库，不允许只留在对话里。

## 5. 遗留稿归档

`docs/superpowers/specs/2026-07-10-quantfox-trustworthy-decision-core-design.md` 移至 `docs/reference/trustworthy-decision-core.md`，首部加注：“北极星参考。按期摘取，非实施规格；P1 已摘 InvestorMandate-lite 与落库留痕思想。”

## 6. 非目标（本期不做）

- 定时巡检、推送通道、盘中实时（P2）。
- A股/ETF 任何能力（P3/P4）。
- 遗留稿的验证协议、能力等级晋级、DecisionBundle、内容哈希。
- 自动下单、接入交易账户。
- 多用户。

## 7. 测试与验收

- 全量 `python -m pytest -q` 全绿（现 78 条 + 新增）。
- 新增单测：mandate 读写校验与部分缺省；config.json 迁移（仅 email.json 存在 → 自动生成）；calendar 缓存与失败降级；watch buy 15:00 前/后、隔周末、pending lot；reconciliations append-only 与 verdict 三档；watch expect 落库。
- grep 覆盖矩阵（第 3 节）全命中。
- 端到端冒烟：`mandate set` → `fund-analyze` SOP 输出含个性化仓位上限；002611 真实数据 `watch expect` → `watch reconcile --app-profit` 全链路。
- 仓库验收：`git status` 无 `output/`、`.gitwarp/` 噪音；`~/.quantfox` 权限 0700。
