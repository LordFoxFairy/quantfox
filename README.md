# quantfox — 场外基金与黄金的量化投研助手（Claude Code 技能套件）

一套 **Claude Code 技能 + Python 引擎**，覆盖普通用户玩基金/黄金的完整链路：
**选基 → 深度分析 → 观测买点 → 建仓 → 持有监控（提前预警+确认离场）→ 组合体检 → 复盘校准 → 邮件推送**。

## 诚实定位（最值钱的部分）
- **不承诺"稳赚 / 90% 猜涨跌"**——没人做得到，账本也会诚实揭穿。
- 目标是**中长期（最短 1 个月）、大概率"不亏 + 正收益"**，靠：估值不贵才买 + 优质 + 长期持有 + 定投摊薄 + 不追高。
- **引擎只出客观数据，判断由 Claude 按 SOP 做**；每次判断存档、用真实涨跌（扣成本、对比基率）诚实复盘。
- 验收看 **edge_vs_baserate / 扣成本 net_return / 校准 gap / 最大回撤**，不看裸命中率。

## 安装（本仓库即一个 Claude Code 插件市场）
```
/plugin marketplace add LordFoxFairy/quantfox
/plugin install quantfox@quantfox
```
本地自测：`/plugin marketplace add .` 再 install。

**装技能 ≠ 装引擎**：`/plugin install` 只装技能（SOP）；`quantfox` 命令要单独装成全局：
```bash
bash skills/fund-analyze/scripts/setup.sh   # = uv tool install，装完任何目录都能 quantfox
# 或直接： uv tool install .
```
装好后 `quantfox --help` 到处可用（若提示找不到命令，把 `~/.local/bin` 加进 PATH 或 `uv tool update-shell`）。

## 7 个技能（各自内部闭环，共用引擎；自然语言即可触发）
| 技能 | 你说什么会触发 | 干什么 |
|---|---|---|
| **fund-screener** | "帮我选10只稳的股票基金" | 全市场两级漏斗选基，反追热、警示幸存者偏差 |
| **fund-analyze** | "分析下 000001 能不能买" | 四维评分卡+情景+大盘估值+反方验证+回测背书 → **离线可视化报告** → 存档 |
| **fund-compare** | "A 和 B 哪个好" | 多只横向对比选优 |
| **position-sizer** | "我有5万该投多少 / 怎么定投" | 仓位/定投/加减仓熔断纪律 |
| **fund-watch** | "看看我关注的有买点没 / 复查我的持仓" | 两态监控：观测找买点 / 持有看离场（提前预警+确认离场） |
| **portfolio-manager** | "帮我看看我这一篮子" | 组合体检+持仓穿透集中度+再平衡 |
| **signal-postmortem** | "复盘下我的判断准不准" | 命中率/IC/信心校准/成本后 edge |

## 引擎 CLI（供技能调用，也可单跑）
```bash
quantfox screen --type 全部 --top 100         # 全市场粗筛
quantfox evidence 000001                      # 证据卡（基本面+风险绩效+指标+估值）
quantfox market-valuation                     # 大盘估值分位（贵不贵）
quantfox backtest 000001 --rule combo         # 机械规则基线回测（point-in-time、扣成本）
quantfox report 000001 --analysis-file a.json # 离线可视化 HTML 报告
quantfox watch add/buy/remove/check           # 监控清单（观测/持有两态）
quantfox log-signal / outcomes / review / calibration   # 存档与复盘
quantfox email config/send/test               # 邮件推送（自配邮箱）
```

## 邮件推送（用户自配、安全）
```
quantfox email config --smtp-host smtp.163.com --username 你 --password 授权码 --from-addr 你
```
配置存本地（不进仓库、权限 600、密码不打印）。可在 fund-watch 触发买点/离场时把摘要或报告 HTML 邮件推给你。
搭配 Claude Code `/schedule` 可周频自动巡检——**是否定时、是否发邮件都由你选，绝不自动配。**

## 数据与依赖
- 数据：[akshare](https://akshare.akfun.com/)（免费无 key，日频 T+1）；接口清单 `docs/akshare-interfaces.md`。
- 指标：[ta](https://github.com/bukosabino/ta)；报告图：内联 [ECharts](https://echarts.apache.org)（单文件离线可转发）。
- 邮件：标准库 `smtplib`。

## ⚠️ 免责声明
本工具基于公开数据提供**理性参考**，**不是投资建议，不保证盈利**。基金/黄金有风险，
买卖决策与盈亏由使用者自行承担；历史表现不代表未来收益。

## 文档
- 判断框架（唯一真理源）：`quantfox/prompts/analysis_framework.md`
- 设计：`docs/superpowers/specs/2026-07-08-money-quant-assistant-design.md`
- 任务状态与已知边界：`docs/task.md`
