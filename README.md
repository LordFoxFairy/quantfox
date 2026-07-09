# quantfox — 场外基金与黄金的量化投研套件（Claude Code 技能）

一套 **Claude Code 技能 + Python 引擎**，帮你把"支付宝能买的场外基金/黄金"做**专业、可解释、可复盘**的投研：
从全市场选基、单只深度分析、生成可视化报告、到仓位定投、组合体检、历史复盘，全流程覆盖。

**诚实定位**：不做黑箱预测，不承诺"稳赚/90% 猜涨跌"（没人做得到）。追求的是 **"只在高把握时出手、出手命中率高、信心可校准、避坑判断稳"**——而且每次判断都存档、用真实涨跌诚实复盘。

## 架构：引擎给数据，CC 当分析师
- **引擎（quantfox）**：取专业数据（akshare：经理/持仓/评级/净值/OHLC/全市场榜单/大盘估值）+ 库化预计算（`ta` 指标、风险绩效）+ 复盘账本。**只出客观数据，永不下结论。**
- **CC agent（技能 SOP 驱动）**：判断、舆情（自己 WebSearch）、评分、反方验证、出报告。
- **提准闭环**：弃权门槛 + 多周期一致 + 反方验证（出手前过滤）→ 信心校准表（出手后复盘反哺）。

## 安装（作为 Claude Code 插件市场，可发布分享）
本仓库即一个 **plugin marketplace**（`.claude-plugin/marketplace.json`）。别人安装：
```
/plugin marketplace add thefoxfairy/money      # 换成本仓库真实 GitHub 地址
/plugin install quantfox@quantfox
```
本地自测：`/plugin marketplace add .` 再 install。
首次装引擎依赖：`bash skills/fund-analyze/scripts/setup.sh`（或 `uv sync`）。

## 6 个技能（各自内部闭环，共用引擎）
| 技能 | 干什么 | 出处 |
|---|---|---|
| **fund-analyze** | 单只深度分析：四维评分卡+情景分析+反方验证 → **离线可视化报告** → 存档 | 原创（评分卡抄 xvary） |
| **fund-screener** | 全市场上万只两级漏斗选基，反追热 | 原创 |
| **fund-compare** | 多只横向对比选优 | 原创 |
| **position-sizer** | 仓位/定投/加减仓熔断纪律 | 适配 tradermonty 同名 |
| **portfolio-manager** | 组合体检+持仓穿透集中度+再平衡 | 适配 tradermonty 同名 |
| **signal-postmortem** | 复盘：命中率/IC/**信心校准表** | 适配 tradermonty 同名 |

日常用法：在 Claude Code 里直接说 **"帮我全市场选10只稳的股票基金"**、**"分析下 000001 能不能买"**、**"我这几只基金组合体检一下"**，对应技能自动触发、跑完整闭环、必要时打开可视化报告。

## 引擎 CLI（供技能调用，也可单跑调试）
```bash
uv run quantfox screen --type 全部 --top 100        # 全市场粗筛候选池
uv run quantfox evidence 000001 --format markdown   # 完整证据卡
uv run quantfox market-valuation                     # 全A股大盘估值分位（贵不贵）
uv run quantfox report 000001 --analysis-file a.json # 生成离线可视化 HTML 报告
uv run quantfox metrics|indicators|profile|fetch <标的>
uv run quantfox log-signal ... / outcomes / review / calibration   # 存档与复盘
```

## 数据源
[akshare](https://akshare.akfun.com/)，免费无需 key。接口清单见 `docs/akshare-interfaces.md`。
可视化报告用内联的 [ECharts](https://echarts.apache.org)（单文件、离线可看、可转发）。

## ⚠️ 免责声明
本工具基于公开数据提供**理性参考**，**不是投资建议，不保证盈利**。基金/黄金有风险，
任何买卖决策与由此产生的盈亏，均由使用者自行承担。历史表现不代表未来收益。

## 文档
- 设计：`docs/superpowers/specs/2026-07-08-money-quant-assistant-design.md`
- 实现计划：`docs/superpowers/plans/2026-07-08-money-quant-assistant-p1.md`
- 任务状态：`docs/task.md`
