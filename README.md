# money — 量化分析助手（CLI + Claude Skill）

对**场外基金**与**黄金**取数、算技术指标、收集舆情，打包成一张"证据卡"；由 Claude（通过 Claude Code Skill）综合推理，给出**可解释的买入/观望/回避信号**，并把每次预测存档以便**复盘评估**。

不做黑箱预测，判断可解释、可追溯、可复盘。

## 设计要点：一条缝 + 两个契约
- **一条缝**：CLI（确定层）只产出客观数据的"证据卡"JSON，永不下结论；Skill（判断层 = Claude）只依赖证据卡 schema 做推理。
- **两个契约**：证据卡 schema（`money/evidence.py`）+ 分析框架（`money/prompts/analysis_framework.md`）。
- **复盘飞轮**：每次预测 append-only 存档，到期用真实净值算命中率/IC/超额收益，Claude 分析前先看战绩自我校准。

## 安装
```bash
uv sync
```

## CLI 用法
```bash
uv run money evidence gold --format markdown   # 黄金证据卡（人类可读）
uv run money evidence 501018 --format json     # 基金证据卡（给 Claude 读）
uv run money fetch 501018                       # 只看原始净值
uv run money indicators gold                    # 只看技术指标
uv run money news 黄金                           # 只看舆情原始信息
uv run money review 501018                      # 看某标的历史战绩
uv run money review --all                       # 全局战绩
```

## Skill 用法（推荐日常入口）
在 Claude Code 里直接说：**"帮我分析下 501018"** 或 **"看看黄金现在能不能买"**。
`fund-analyze` 技能会自动取证据卡、补最新舆情、按分析框架推理、给出信号并存档。

## 数据源
[akshare](https://akshare.akfun.com/)，免费无需 key。接口清单见 `docs/akshare-interfaces.md`。

## ⚠️ 免责声明
本工具基于公开数据提供**理性参考**，**不是投资建议，不保证盈利**。基金/黄金有风险，
任何买卖决策与由此产生的盈亏，均由使用者自行承担。历史表现不代表未来收益。

## 文档
- 设计：`docs/superpowers/specs/2026-07-08-money-quant-assistant-design.md`
- 实现计划：`docs/superpowers/plans/2026-07-08-money-quant-assistant-p1.md`
