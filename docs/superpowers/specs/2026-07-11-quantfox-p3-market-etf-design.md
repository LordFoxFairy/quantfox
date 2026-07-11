# Quantfox P3 设计：A股市场层 + ETF 场内全链路 + yield-seeker 收尾 + llm 深分析

- 日期：2026-07-11
- 状态：用户全权委托（"全面都弄"），已定案
- 前置：P2 已合入（origin/main eb05c5e，177 passed / 1 skipped）
- 执行拆分：两份计划——**P3a**（W1+W2+W5，引擎完善）先行，**P3b**（W3+W4，ETF 全链路 + llm）随后

## 0. 已定决策

| 决策点 | 结论 |
|---|---|
| ETF 优先级 | 用户暂无券商账户但确定后续会开：**全链路接入**（分析/榜单/巡检/记账全通），不做阉割版 |
| llm 深分析 | 触发式（有新告警才起）+ 成本护栏（默认关、每日≤1次、超时降级）；定时任务默认不带 `--llm` |
| 对外发布 | **不在 P3**：质量/隐私/免责门槛需单独立项并过用户确认 |
| A股个股 | P4，不在本期 |
| 行业轮动数据 | 板块资金流接口已知限流（HANDOFF §4）：优先用指数/行业指数行情算动量，board 接口失败即整块弃权并入 DataHealth，不编数据 |

## W1. yield-seeker 收尾（C3/C4/C5 + SOP）

### C3 名实核对（真持仓版）
- `quantfox/evidence.py`：holdings 段加 `theme_guess`——前十大持仓股名/行业按关键词表聚类出主题猜测（纯本地字符串启发，词表复用 `gold_report._INDUSTRY_WORDS` 抽到共享常量模块 `quantfox/themes.py`；聚类=计数最多的行业词，无命中→None）。
- 卡片顶层 `name_theme_mismatch: bool`（基金名行业词 ∉ theme_guess 时 true；任一侧缺失→false）。schema 2.1→2.2。
- fund-analyze / fund-screener SOP 补一句：`name_theme_mismatch=true 时必须向用户点明"名实不符，舆情按实际持仓主题搜"`。

### C4 forecast 小样本警示（引擎字段化）
- `forecast()` 输出：任一 horizon 的分布若 `n < 200`，该分布 dict 附 `"warning": "样本不足，谨慎参考"`；基金历史 `< 3 年`（len(prices) < 756）时顶层附 `"age_warning": "成立不足3年，全部前瞻打折看待"`。已有的 `all<60 别当真` 语义保留不变。
- SOP（analyze/screener）：带 warning 的数字必须打折表述——已在铁律，补一句引用字段名。

### C5 `quantfox next-confirm`
- 新命令：`quantfox next-confirm [--at "YYYY-MM-DD HH:MM"]`（缺省=现在）→ 输出 `{"order_at":..., "nav_date":..., "note": "15:00 前按当日净值，之后顺延下一交易日"}`，复用 `calendar_cn.nav_date_for_order/trade_dates`。交易类 skill SOP 提一句可用。

### SOP 文本落地
- `skills/fund-screener/SKILL.md` 加「第 0 步 · 诉求校准与风偏探测」章节（yield-seeker spec §1-2 压缩：预期阶梯表口径 + 对话式风偏信号，不发问卷）；
- 共享段（7 skill 引用的框架 v16）补两条：假稳三查（flags 字段消费）与名实核对（theme_guess 消费）。

## W2. A股市场层 `quantfox market`（新模块 `quantfox/market.py`）

- **指数估值**：沪深300/中证500/创业板指/科创50/中证红利 的 PE 分位（近10年）——akshare 指数估值接口（实现时从 `stock_index_pe_lg`/`index_value_hist_funddb` 类接口探测选稳者；单指数失败记 DataHealth，不阻断整体）。
- **指数动量**：各指数 20/60 日收益 + MA20>MA60 标记（指数日线 `stock_zh_index_daily` 类接口）。
- **市场宽度**：全A站上 MA60 比例或涨跌家数比（探测 `stock_zh_a_spot_em` 聚合；不可得→该行弃权）。
- **行业轮动**：申万一级或中证行业指数近 1/3 月动量 top5/bottom5（行业指数行情接口；限流/失败→整块省略并入 DataHealth 行）。
- 输出：JSON（各块数据 + `regime_line` 一句话结论，如"整体估值中位偏上，成长强价值弱，热点：半导体/军工"）+ `--brief` 只出结论行。
- **消费**：gold-report 头部 regime 从 `market-valuation`（全A单一锚）升级为 `market --brief` 结论行（拉取失败降级回 market-valuation，再失败显示"regime 不可用"）；分析框架 v16 把"看大盘 regime"的动作指到 `quantfox market`。
- 全部尽力而为 + DataHealth 明细，任何一块失败不虚报。

## W5. 事件日历多源 + 当日缓存

- `events_cn.py`：源列表 `[news_economic_baidu, <实现时探测的第二宏观日历接口>]` 依序尝试；首个成功即用。
- 成功结果缓存 `~/.quantfox/events_cache.json`（键=日期，当日有效）；读缓存优先。全失败仍返回 None（弃权语义不变）。

## W3. ETF/LOF 场内全链路

### 资产模型
- `resolve.py`：`AssetType = Literal["otc_fund", "gold", "etf"]`。识别规则：
  - 显式覆盖：`etf:512880` / `512880.SH`（后缀去掉入库，symbol 存 6 位码）。
  - 前缀启发：`50/51/52/53/56/58` 开头 → 沪市 ETF；`15` 开头 → 深市 ETF；`16` 开头 → LOF（按 etf 处理，场内口径）。
  - 其余 6 位码 → `otc_fund`（现行为不变，兼容既有账本）。
- Asset 增加只在 etf 时填的 `market: "SH"|"SZ"`。

### 数据
- 日线：`data/prices.py` 加 etf 分支（`fund_etf_hist_em` 类接口，收盘价规范化成现有 date/value 格式，OHLC 可得则保留）。
- 实时：`intraday.py` 加 `etf_intraday`（`fund_etf_spot_em` 现价/涨跌幅），patrol --intraday 与对话 `quantfox intraday` 消费。
- Universe：`data/etf_universe.py`——`fund_etf_spot_em` 全列表 → 规模/成交额流动性过滤（默认 日均成交额 ≥ 5000 万），输出 code/name/规模/成交额/涨跌幅。

### 交易语义与费用
- `storage.round_trip_cost` 加 `etf` 分支：佣金双边 `2×0.025%`（万2.5，最低5元忽略）+ 冲击/价差近似 `0.1%` → 约 0.15%，无申购赎回费、无印花税。
- 记账语义：场内成交**即时确认**——`watch buy <etf> --amount --nav <成交价>` 时 `confirm_date=entry_date`（不走 15:00 cutoff 推算；CLI 检测 asset.type=="etf" 跳过日历分支）；对账口径与场外一致（App/券商日盈亏 vs expected）。
- SOP 明示："场内 T+1 交割、卖出资金当日可用再买；跨境 ETF 部分 T+0——涉及品种时如实告知不确定处"。

### 全链路打通
- evidence/metrics/forecast/simulate_paths/metrics-batch/backtest：价格序列进来即工作，唯 `evidence` 的 profile 段对 etf 置 `{"applicable": false}`（无经理/申赎费语义）；percentile/估值闸门照用。
- `quantfox screen --etf`：对 etf_universe 流动性池跑 metrics-batch，按卡玛排序输出（复用 flags）。
- gold-report 第六榜「ETF 精选」：etf_universe 流动性过滤 → metrics-batch → 卡玛 top-10（列同五榜公共列 + 日均成交额）；ETF 失败整榜省略入 DataHealth。
- patrol：etf 持仓走同一状态机；盘中阈值沿用 ±2%。
- mandate/单标的上限/主题上限语义不变。

## W4. `patrol --llm` 触发式深分析

- 触发条件：`--llm` 显式给定 **且** 本次 `new_alerts` 非空 **且** 当日尚未跑过（alerts 表 kind=`llm_run`、state=`YYYY-MM-DD` 去重）。
- 实现 `quantfox/llm_review.py`：
  - 输入打包：new_alerts + 各告警标的的 evidence JSON（复用 build_evidence）写入临时文件；
  - 调用：`subprocess.run(["claude", "-p", <prompt>], timeout=300)`——prompt 模板固定：以框架 v16 铁律为约束（禁点数字承诺、看中位、高位条件化、给"继续持有/减仓观察"档位而非指令），输出 ≤300 字人话判断；
  - `shutil.which("claude")` 不存在 / 超时 / 非零退出 → 降级：邮件仍发纯引擎版，正文注明"llm 深分析不可用（原因）"。
- 输出并入 patrol 邮件正文（"AI 判断（仅供参考，非投资建议）"段）。
- 默认关闭；`schedule install` 不带；`schedule install --llm` 允许显式开（plist patrol 命令加 --llm）。
- 测试：subprocess 全注入 fake（成功/超时/缺 CLI 三分支），绝不真调。

## 非目标（本期不做）

- 对外发布（P4 单独立项过用户门槛）；A股个股（P4）；自动下单/券商接口；ETF 分钟级/盘口数据；llm 深分析进周报（只进巡检邮件）。

## 测试与验收

- 基线 `uv run pytest -q` = 177 passed, 1 skipped；每任务后全绿。
- W1：theme_guess 聚类与 mismatch 判定（合成持仓）；forecast warning 两阈值；next-confirm 三场景（盘前/盘后/周末）。
- W2：market 各块注入 fake 数据出 JSON + regime_line；单块失败 → DataHealth 明细且其余块正常；gold-report 头部消费与双重降级。
- W3：resolve 前缀/显式/兼容三组；etf prices 规范化；round_trip_cost etf 分支；watch buy etf 即时确认（不走日历）；screen --etf 与第六榜（合成 universe）；evidence profile 不适用分支。
- W4：三分支注入测试；当日去重；降级文案。
- W5：双源顺序、当日缓存命中、全失败弃权。
- 真实冒烟（尽力而为）：`quantfox market`、`quantfox evidence etf:512880` + `forecast`、`gold-report` 含 ETF 榜、`next-confirm`；llm 若本机有 claude CLI 则真实触发一次并贴输出。
- 隐私铁律与产物落盘铁律照旧。
