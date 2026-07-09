# money — 量化分析助手（CLI + Claude Skill）

对**场外基金**与**黄金**取数、算技术指标、收集舆情，打包成一张"证据卡"；由 Claude（通过 Claude Code Skill）综合推理，给出**可解释的买入/观望/回避信号**，并把每次预测存档以便**复盘评估**。

不做黑箱预测，判断可解释、可追溯、可复盘。

## 设计要点：一条缝 + 两个契约
- **一条缝**：CLI（确定层）只产出客观数据的"证据卡"JSON，永不下结论；Skill（判断层 = Claude）只依赖证据卡 schema 做推理。
- **两个契约**：证据卡 schema（`money/evidence.py`）+ 分析框架（`quantfox/prompts/analysis_framework.md`）。
- **复盘飞轮**：每次预测 append-only 存档，到期用真实净值算命中率/IC/超额收益，Claude 分析前先看战绩自我校准。

## 作为 Claude Code Skill 安装（推荐，可发布分享）

本仓库本身是一个 **Claude Code plugin marketplace**（清单在 `.claude-plugin/marketplace.json`），
里面的 `quantfox` 插件带 `fund-analyze` 技能。别人这样装：

```
/plugin marketplace add thefoxfairy/money      # 换成本仓库的 GitHub 地址
/plugin install quantfox@quantfox
```

本地开发/自测（在仓库根目录）：

```
/plugin marketplace add .
/plugin install quantfox@quantfox
```

首次使用前，安装引擎依赖：`bash skills/fund-analyze/scripts/setup.sh`。
装好后，直接对话："帮我看看黄金能不能买"。

## 手动安装引擎（不走 marketplace 时）
```bash
uv sync
```

## CLI 用法
```bash
uv run quantfox evidence 000001 --format markdown  # 完整证据卡（基本面+风险绩效+估值+指标）
uv run quantfox profile 000001                      # 基金基本面：经理/持仓/评级
uv run quantfox metrics 000001                      # 风险绩效：夏普/索提诺/卡玛/VaR/回撤…
uv run quantfox indicators gold                     # 技术指标（辅助）
uv run quantfox fetch 000001                        # 原始净值/价格序列
uv run quantfox review 000001 / --all               # 历史战绩
```

**分工**：引擎提供**专业数据**（基金经理/持仓/评级/规模费率 + 净值/OHLC）+ 库化预计算（`ta` 算指标、
风险绩效）+ 复盘存档；**舆情/宏观由 CC agent 自己用 WebSearch 搜并鉴别**（比固定数据源更新更准）；
技术指标只是**辅助**。需要最高最低价的 KDJ/ATR/CCI/W%R/ADX 仅黄金可算。

## Skill 用法（推荐日常入口）
在 Claude Code 里直接说：**"帮我分析下 501018"** 或 **"看看黄金现在能不能买"**。
`fund-analyze` 技能会自动取证据卡、补最新舆情、按分析框架推理、给出信号并存档。

## 数据源
[akshare](https://akshare.akfun.com/)，免费无需 key。接口清单见 `docs/akshare-interfaces.md`。

## ⚠️ 免责声明
本工具基于公开数据提供**理性参考**，**不是投资建议，不保证盈利**。基金/黄金有风险，
任何买卖决策与由此产生的盈亏，均由使用者自行承担。历史表现不代表未来收益。

## 文档
- 设计：`docs/superpowers/specs/2026-07-08-quantfox-assistant-design.md`
- 实现计划：`docs/superpowers/plans/2026-07-08-quantfox-assistant-p1.md`
