# 任务状态

## money 量化分析助手

- [x] **P1 / MVP**（2026-07-08 完成）：数据（场外基金+黄金）+ 技术指标 + 历史分位 + 舆情收集 + 证据卡 + 预测账本/复盘 + 分析框架 + CLI + Claude Skill。
  - 设计：`docs/superpowers/specs/2026-07-08-money-quant-assistant-design.md`
  - 计划：`docs/superpowers/plans/2026-07-08-money-quant-assistant-p1.md`
  - 20 个单测全绿；黄金与基金 501018 真实端到端冒烟通过。

### 后续（未开始）
- [ ] **P2**：每日 `loop` 定时（headless `--llm` 走 Claude API）、回测（vectorbt/backtrader）、更多结构化数据源。
- [ ] **P3**：网页 K 线看板、正式对外发布与文档。

### 已知待办（推广前）
- [ ] 打包时确保 `money/prompts/*.md` 随 wheel 分发（当前 `uv run` 从源码读取正常）。
- [ ] 基金"名称→代码"解析（当前仅支持 6 位代码或"黄金"）。
