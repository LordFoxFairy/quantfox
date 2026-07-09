---
name: fund-analyze
description: >-
  深度分析一只场外基金或黄金（支付宝可买的那类），一条龙产出：四维评分卡 + 买入/观望/回避结论 + 信心分 +
  深度解读 + 离场信号，并生成一份**可视化 HTML 报告**（K线/净值+回撤+持仓图）在浏览器打开，最后把判断存档以便复盘。
  当用户提到某只基金 6 位代码或"黄金"，问"能不能买 / 现在是买点吗 / 会涨会跌 / 风险大不大 / 怎么看 / 帮我分析下 /
  最近怎么样 / 该不该加仓减仓 / 适合定投吗"等——即使没明说"分析"二字也要触发。
  只适用于场外基金与黄金；A股个股、加密货币不在范围。对比多只用 fund-compare；查历史战绩复盘用 signal-postmortem；仓位定投用 position-sizer；组合体检用 portfolio-manager。
---

# fund-analyze — 单标的深度分析（完整闭环）

一次跑完：**取数 → 四维评分卡 → 深度解读 → 可视化报告 → 存档**。你（CC agent）是分析师，`quantfox` 引擎是你的数据与工具后端。全程中文、透明说依据、结论先行。

## 分工
- 引擎给**专业数据 + 可复盘的预计算**（经理/持仓/评级/净值/OHLC/风险绩效/指标）。
- 你负责**判断 + 舆情（自己 WebSearch）+ 评分 + 深度解读**。技术指标只是辅助，别当主角。
- 首次使用先装依赖：`bash skills/fund-analyze/scripts/setup.sh`。

## 闭环步骤

1. **定标的**：提取基金 6 位代码或识别"黄金"；含糊先问清。
2. **看战绩校准**：`uv run quantfox review <标的>`，历史准就自信、不准就收敛。
3. **取证据卡**：`uv run quantfox evidence <标的> --format json`（字段解读见 `references/evidence-card.md`，首次必读）。
4. **专业地读**（不是只看指标）：**持仓**看它押注什么、**估值分位**看贵不贵、**风险绩效**看险不险、**经理/评级/规模费率**看靠不靠谱。股票/指数基金再跑 `uv run quantfox market-valuation` 看**大盘整体估值分位**（偏贵/贵时追高更谨慎、下调信心）。
5. **舆情自己搜自己判**：WebSearch/WebFetch 搜该标的（或其重仓行业、或黄金对应的实际利率/美元/央行购金）最新新闻政策，鉴别真伪时效与利好利空。
6. **打四维评分卡 + 结论**：严格按 `quantfox/prompts/analysis_framework.md`——趋势动量/稳定性/估值/基本面质量各 0-100，综合出 Verdict + 信心分 + **离场信号(Kill criteria)**。data_quality 缺失要下调信心并说明。
   - **出手纪律（提准，必守）**：默认"观望"，只有多因子共振**且**多周期(近1月/近3月/近1年)方向一致才升到"买/回避"。
   - **回测背书门槛**：出"买/回避"前先跑 `uv run quantfox backtest <标的> --rule combo`。基线 **edge≤0 或 net≤0 → 默认降回"观望"**，除非有具体强力的非机械证据并显式说明为何敢推翻基线。宗旨：极少出手、每次出手都有历史基线撑腰。
   - **反方验证**：下结论前先当"魔鬼代言人"专门反驳自己，列最强反面证据；驳不倒才保留，否则降档/降信心。把这轮攻防写进解读。宁可弃权，不硬猜。
7. **生成可视化报告并打开**（闭环关键，必做）：
   - 把结论写成分析 JSON（结构见 analysis_framework.md 末尾）存到临时文件，如 `/tmp/analysis.json`。
   - `uv run quantfox report <标的> --analysis-file /tmp/analysis.json` → 打印出 HTML 路径。
   - 打开：mac `open <路径>`；linux `xdg-open <路径>`；win `start <路径>`。失败就把绝对路径给用户让其手动打开。
8. **存档预测**（复盘地基，别漏）：
   ```
   # 先把第3步的证据卡 JSON 存文件（如 /tmp/ev.json），冻结"当时为什么这么判"，供日后复盘可信
   uv run quantfox evidence <标的> --format json > /tmp/ev.json
   uv run quantfox log-signal --symbol <代码> --type <otc_fund|gold> \
     --signal <档位> --signal-numeric <2..-2> --confidence <0-1> \
     --price-ref <证据卡最新价> --ts <今天YYYY-MM-DD> --horizons 20,60,120,250 \
     --rationale "<一句话理由>" --evidence-file /tmp/ev.json
   ```
9. **对话里也给结论**：结论先行（信号+信心）+ 四维小结 + 一句风险 + 报告已打开提示 + 免责。

## 情形微调
- "风险多大" → 评分卡里稳定性/估值权重加大，报告解读重点讲最大回撤/VaR/最坏情况。
- "适合定投吗" → 看长期趋势+波动+分位，讲摊薄逻辑而非精确择时。
- "最近怎么样" → 仍走完整闭环，但对话侧简报式。

## 铁律
- 不承诺精确点位/收益；接近随机游走，给的是有依据的概率倾向。
- data_quality 缺失 → 明说 + 降信心，绝不拿 null 当依据。
- 基金无 OHLC → ATR/KDJ/CCI/W%R/ADX 不可用，别硬解读。
- 结尾必附免责，决策与风险由用户承担。
