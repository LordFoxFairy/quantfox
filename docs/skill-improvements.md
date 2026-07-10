# Skill 改进待办（实战暴露的问题 · 供 skills 下一步打磨）

> 来源：2026-07-10 实战会话（记账博时黄金 002611 + 全市场深筛选基）。
> 每条：场景 / 问题 / 建议 / 优先级 / 影响 skill。
> 配套：操作教训见 `docs/lesson.md`；深筛+舆情完整设计见 `docs/superpowers/specs/2026-07-10-deep-screening-sentiment-design.md`。
> 新增（2026-07-10 晚会话）："收益诉求"端到端 SOP + C1-C6 工程项，见 `docs/superpowers/specs/2026-07-10-yield-seeker-sop-design.md`（预期校准/风偏探测/假稳过滤/名实核对/触发式进场卡）。

## 0. 先明确"已建成、别重造"（避免重复劳动）

打磨前务必确认当前代码状态，**以下已实现，不要重写**：
- ✅ **多因子深筛**：`screen.py` 已有 `score_universe/screen`，含 4 风格（balanced/steady/momentum/pullback）、反过热(剔抛物线>55%、罚超买)、回调加分、A/C 去重、每主题限流；`cli.py screen --style/--per-theme/--exclude-overheated` 已接；`test_screen.py` 4 测试全绿。（commit 0320773）
- ✅ **单只精筛证据卡**：`evidence`（估值分位/回撤/RSI/夏普/52周位置）。
- ✅ **舆情**：`fund-screener` 技能已把舆情设计为**第4步 WebSearch 研判**（板块见顶/高低切换/政策），由 agent 执行，非代码。
- ⚠️ **教训**：本会话我一度读到 stale 的旧 `screen.py/cli.py`（会话中途文件被更新），差点重造深筛。**打磨前先 `git log`/读现文件确认真实状态**。

---

## ✅ 已完成（2026-07-10，commit 见 git）
- **A1/A2/A3 记账重构**：新增 `lots` 表 + `add_lot/position/list_lots`（storage.py）；`watch buy --amount <金额> --nav <确认净值>` 按金额分批记账（不覆盖、自动折算份额+加权成本）；`watch position` 看分笔+加权成本+现值+浮盈亏；SOP 写清 T+1/15:00 cutoff、优先让用户报 App 确认成本。测试 `test_lots.py` 3 绿。
- **B1 估值闸门**：fund-screener 铁律点明"深筛分是相对分≠能买"，短名单必须过 evidence 估值分位闸门(>0.85 剔除)，区分相对分 vs 绝对估值位。
- **B4 深筛初筛报告**：新增 `quantfox screen-report`（+`screen_report.py`+模板）→ 含大盘估值+主题分布+Top-k表(过热标红)的自包含 HTML，`--pdf` 转 PDF（复用 html_to_pdf）发邮件。测试 `test_screen_report_html_renders` 绿。
- **B2 大盘 regime 前置**：screen-report 报告头含 `market-valuation`；fund-screener SOP 第1步先跑 market-valuation，偏贵→建议 steady/pullback。
- **B5 前瞻收益分布**：新增 `quantfox forecast`（+`forecast.py`）→ 持有20/60/120/250日的正收益概率/中位/p10-p90/极值，且带**估值条件化** `from_similar_valuation`（从当前估值分位买入的历史下场，量化"别在山顶买"）。框架 v13 接入：收益区间用 forecast、看中位不看均值、优先条件化。测试 `test_forecast.py` 3 绿。
- **B6 选基方法论内核**：新增 `docs/quant-fund-selection-methodology.md`（10 条心智模型，每条一个检查动作）；fund-screener SOP 精筛引用之 + 加 forecast/卡玛/归因。
- 仍待：A2 的自动 T+1 对账（现为 SOP 指南，非代码）。
- **B3 已定（2026-07-10）**：保持 WebSearch 舆情，重量化模块暂缓（复验：北向可用但粗、板块流限流；先验证 alpha）。→ backlog 已清，A/B 主体完成。

## A. 持仓记账（P1 · 影响 portfolio-manager / fund-watch / position-sizer）

### A1. holdings 无法表达"多笔分批建仓"（multi-lot）
- **场景**：用户 7.7、7.8 两笔不同金额买入同一只基金。
- **问题**：`holdings` 表（storage.py）只有单个 `entry_price`+`entry_date`，无份额/金额/多笔；只能人工折算加权成本塞一条，**丢分笔明细**，`watch buy` 还会覆盖上一次。
- **建议**：新增 `lots` 表（symbol/金额/下单日/确认净值/份额），holdings 由 lots 聚合出加权成本；`watch check` 离场判断基于聚合成本。

### A2. 场外基金 T+1 确认时点未建模 → 成本基极易算错
- **场景**：15:00 后下单确认净值顺延，两笔确认时滞可能不同。
- **问题**：确认时点(T vs T+1，取决 15:00 前后)直接决定成本。本次我先猜当日、又猜都 T+1，**都错**，靠用户报的 App 每日收益反推才对齐两笔确认净值（细节脱敏）。
- **建议**：skill 指南明确——① **优先让用户直接报 App 确认成本净值/持仓成本**，别猜确认时点；② 只有金额时，用 App 已知每日/累计收益对账后再落库；③ 文档写清 15:00 cutoff 与 T+1 规则。

### A3. 缺"按金额记账"入口
- **场景**：用户说"帮我建仓、算收益"，输入是金额+日期，不是净值。
- **问题**：`watch buy` 只收 `--entry-price`(净值)，用户手上是金额，须人工折算份额；产品无"已买入→记账→看盈亏"记账流。
- **建议**：`watch buy` 加 `--amount`(金额)，自动用确认净值折算份额记 lot，直接输出份额/加权成本/当前浮盈亏。

---

## B. 深度筛选 / 选基（P1-P2 · 影响 fund-screener）

### B1.（P1）`screen` 无绝对估值闸门 → 高分 ≠ 能买
- **场景**：深筛 top-50 的入围基金，逐只验 `evidence` 后**估值分位全在 96-99%**（整体市场高位）。
- **问题**：`screen` 只用收益列（universe 只有 r_1w..r_3y+费率），**无任何绝对估值/风险维度**，会给 98% 估值的基金也打 100 分。深筛分只代表"幸存者里动能质量最好"，**不代表现在买它安全**。用户极易误把高分当"靠谱可买"。
- **建议**：① 短名单**强制过 `evidence` 估值分位闸门**（>0.85 降级/剔除）再产出，写进 fund-screener 铁律；② 探索在 universe 层加轻量估值/风险代理列；③ 结论里必须区分"深筛分(相对)"与"估值位(绝对)"。

### B2.（P2）无市场 regime / breadth 总览 → 无法提示"现在遍地贵"
- **场景**：全市场深筛全高位，且舆情显示科技拥挤、7月高低切换。
- **问题**：`screen` 在"市场给什么就排什么"，无市场级估值/宽度语境；已有 `market-valuation` 命令但**未与选基流程联动**，用户看不到"当前整体贵不贵、钱在往哪切"。
- **建议**：选基流程开头先跑 `market-valuation` + 简版 regime 判断（哪些板块拥挤/哪些在承接），据此提示"追顶还是承接"，并影响 `--style` 建议（高位偏 steady/pullback）。

### B3.（P2）舆情层仅为 agent-WebSearch，未落地为可复用能力 —— 【决定：保持 WebSearch，模块暂缓】
- **场景**：用户想要"配合舆情分析"，期望是系统化的、按权重合成的舆情分。
- **问题**：现状舆情=skill 第4步 WebSearch（agent 手动，不可复用、不可回测）；akshare 资金流/板块接口本环境常 `RemoteDisconnected` 限流，C 路(资金面)数据不稳。
- **决定（2026-07-10 复验后）**：**保持 CC WebSearch 为主**（真读新闻真判断，比拼凑限流的资金流指标更靠谱、更贴 regime）。复验：北向资金 `stock_hsgt_fund_flow_summary_em` ✅ 可用但仅市场级/偏粗；板块资金流 ❌ 仍限流。依据 backlog 自警"先验证有没有 alpha、别做花架子" + 保本优先 + YAGNI，**重量化舆情模块暂缓**。
- **仅当**后续实盘用一阵确有缺口，再做"尽力而为、限流即降级、明确标未验证 alpha"的**轻量北向 helper**（不做重模块、不做量化:舆情加权闭环，直到先证明北向对基金选择真有 alpha）。

### B4.（P2）缺 top-k 深筛"初筛报告"（可视化可排序）
- **场景**：粗筛出 top-50，用户要报告方便排序/对比/分析（"top-k 通常要有报告，k≈50 初步"）。
- **问题**：现有 `report` 只出**单只** K 线报告，无"筛选结果列表"报告。
- **建议**：新增 `quantfox screen-report`（或 `screen --report`）：top-k 渲染成**自包含可排序 HTML**（rank/code/name/theme/score/overheated/多周期收益/费率 + 板块分布 + 幸存者偏差免责），复用 `report` 的自包含+email。首版 k=50、板块分组、表头排序即可；风险列作为短名单二级精筛，不首屏全拉（50 只逐拉 akshare 慢且易限流）。本会话已有一次性原型：`scratchpad/gen_screen_report.py`，可参考落地。

### B5.（P1）缺"前瞻收益预测"命令（概率分布，非点估计）
- **场景**：用户要"未来 1/3/6 月大概收益率"才能判断值不值得买。
- **问题**：产品只有历史区间收益，无前瞻预测；而点预测="算命"必是虚假。
- **建议**：新增 `quantfox forecast <code>`：用该基金历史滚动，算持有 20/60/120 交易日(1/3/6月)的**前瞻收益分布**——正收益概率 / 中位(最可能) / 均值 / p10–p90 / 历史极值。**铁律**：① 报告必须强调"看中位别看均值"(均值被牛市尾部拉高)；② 明确这是历史统计推断、样本偏牛市、当前高估值应向下打折；③ 绝不输出单一点数字冒充"预测"。本会话原型：`scratchpad/forecast.py` + `gen_forecast_report.py`（已出 2 页 PDF）。

### B6.（P1·方法论内核）把"顶级量化选基思考框架"沉淀进 fund-screener
- **场景**：从上万只里选"有潜力、靠谱、有收益"的，用户要的是**大佬级的分析思考能力**，不是跑个排序。
- **问题**：现状 skill 偏"操作步骤"，缺一套显式的、可复用的**量化选基心智模型**，容易退化成看收益/看分数。
- **建议**：在 fund-screener 增加"分析思维"章节，把下列心智模型写成**每条都能落到一个具体检查动作**：
  1. **风险调整收益 > 绝对收益**：排序看夏普/索提诺/**卡玛(年化÷回撤)**，不是看谁涨最多。（本会话 519770 卡玛4.19 就是这么捞出来的）
  2. **有效前沿思维**：找"同等回撤下收益最高 / 同等收益下回撤最小"的 Pareto 最优，而非榜首。
  3. **概率分布 > 点预测**：任何前瞻都给分布(P正/中位/区间/尾部)，看中位不看均值，诚实标不确定性。
  4. **幸存者偏差 + 数据窥探偏差**：榜单/回测顶部天然虚高；警惕在一段牛市里过拟合；重 out-of-sample 与跨 regime 一致性。
  5. **Regime / 择势**：基金业绩是 regime 依赖的；先判断当前风格(拥挤/切换/估值位)，再决定 `--style` 与板块取舍。
  6. **估值锚 + 安全边际**：买在 52 周/3 年高分位(>85%)本身即负 alpha，动能再强也要减配/等回调（呼应 B1 估值闸门）。
  7. **收益归因：alpha vs beta/运气**：这只是经理真本事(跨行情稳定、低回撤高卡玛)还是单押一个热门赛道的 beta？看回撤控制与多周期一致性。
  8. **base-rate/贝叶斯**：从无条件基率出发(如"任意时点持有3月正收益率")，再用当前条件更新，别被近期暴涨单点带偏。
  9. **成本与容量**：费率、赎回费(7日1.5%)、规模过大导致的收益衰减，纳入净收益。
  10. **保本优先 + 诚实边界**：先不亏再求收益；永不承诺、永不用点数字包装确定性——"高收益+高概率+短期"若互斥，必须当面点破。
- 可另起 `docs/quant-fund-selection-methodology.md` 展开，fund-screener 引用之。

### B7.（P1·真正的"打磨整个 skills"）跨 skill 一致性 —— 新能力/v13 铁律只落在 fund-screener 一家
- **场景**：接管后 grep 7 个 SKILL.md 发现，本会话建的能力与诚实铁律**大多只写进了 fund-screener**，其它 skill 未同步 → 用户在别的入口（尤其单只分析）体验不到。
- **实测覆盖缺口**（2026-07-10 grep）：
  - `forecast` 前瞻分布：仅 fund-screener 有；**fund-analyze（单只深度分析）竟无**——正是用户本轮"没前瞻没法判断"的痛点入口；fund-watch（持仓）也该有"从当前位置买/持有的未来赔率"。
  - `看中位不看均值`：仅 fund-screener；fund-analyze / fund-compare 都报收益，须同步。
  - `估值闸门(>0.85)`：analyze/screener/sizer 有；fund-compare / portfolio-manager / fund-watch 缺。
- **建议（我作为 owner 的打磨主线）**：
  1. ✅ **【已完成 2026-07-10】fund-analyze SOP 加 `quantfox forecast <code>`**：新增第5步"前瞻收益分布"（含 `from_similar_valuation` 估值条件化）+ 铁律"看中位不看均值/高位打折/样本不足别当真" + 对话侧给前瞻一句话 + description 列出前瞻。`test_skill_file.py` 4 绿。
  2. fund-watch 持仓监控加 forecast（"这只从现在起未来赔率"）。
  3. 把"看中位不看均值 / 估值闸门 / 幸存者偏差"三条诚实铁律，抽成一段共享话术，**7 个 skill 统一引用**（避免各写各的、漏的漏）。
- **非 gap（已核实，别重做）**：保本优先在 `prompts/analysis_framework.md` 框架层，全 skill 隐式遵循；forecast 小样本已保护（all≥60 / conditional≥30）。

### 剩余代码项（P1）
- **A2 自动 T+1 对账**：现为 SOP 指南，唯一未落代码的记账项。可选实现：`watch buy` 按 15:00 cutoff + 交易日历自动推确认日/净值，或对账用户报的 App 收益。
