# Quantfox 可信决策核心设计

> **定位：北极星参考，非实施规格。** 按期摘取有回报的部分（P1 已摘 InvestorMandate-lite 字段与"结论落库留痕/数据失败不得报正常"思想）；预注册验证协议、内容哈希、canonical JSON 等企业级机制不落地。路线图见 `docs/superpowers/specs/2026-07-10-quantfox-p1-consistency-mandate-design.md` §0。

- 日期：2026-07-10
- 状态：评审修订版，待复核
- 子项目：顶级量化 skills 的可信契约与账本基础
- 工作方式：当前主仓小步实现，不使用 GitWarp

## 1. 本子项目的职责

Quantfox 的最终目标是一个个人量化主控：用户给出本金、任意目标日期、目标净收益和可承受损失后，系统明确回答买什么、买多少、何时买、何时复查、何时减仓或退出，并持续结算实际结果。

这个目标不能建立在含糊的数据口径或未经验证的概率上。本子项目只建设所有 skills 不可绕过的可信核心：

- 数据 basis、时间点和质量契约。
- 用户目标、现金流和风险预算契约。
- 成本、历史场景、预测和组合目标的不同语义。
- 可执行动作及人工确认生命周期。
- 交易、持仓、决策和 outcome 的不可变账本。
- 风险增加动作与风险降低动作的不同门禁。

本子项目完成后，系统仍不会自动启用 `buy/add`。只有后续预测验证子项目达到晋级门槛，风险增加动作才会解锁。`quant-commander` 的自然语言编排、候选生成和展示流程由下一份独立设计覆盖，但必须消费本设计的契约。

## 2. 目标与非目标

### 2.1 目标

1. 消除单位净值、累计净值和总回报混用。
2. 消除数据失败时的虚假正常状态。
3. 消除毛收益冒充净收益、描述性频率冒充预测概率。
4. 消除 holding/lots 矛盾、错标的结算、选择性结算和历史删除。
5. 为任意正期限和精确目标日期建立统一目标语义。
6. 定义组合级 `DecisionBundle`，确保所有建议共同满足资金和风险约束。
7. 定义用户手动执行后的确认、部分成交、过期和对账流程。

### 2.2 非目标

- 自动下单或接入交易账户。
- 面向公众的多用户产品。
- 在验证门槛通过前输出已校准未来概率。
- 在本子项目中实现候选筛选算法、组合优化器或 `quant-commander` 对话流程。
- 通过免责声明替代数据、统计或风险控制。

## 3. 诚实能力等级

每个模型版本必须处于以下一个等级，等级随输出一起冻结：

### 3.1 `descriptive`

- 只描述历史上发生过什么。
- 输出名称为历史频率、历史分位和估计区间。
- 不得使用 `forecast_probability`、`confidence` 或“目标达成概率”等未来含义。
- 可用于风险教育、候选排除和压力场景，不得单独驱动 `buy/add`。

### 3.2 `shadow`

- 已完成 point-in-time walk-forward 和永久 holdout，但前瞻样本尚未满足晋级门槛。
- 生成 execution_eligible=false 的 PredictiveForecast 和 bundle_mode=shadow 的 hypothetical DecisionBundle，供后续到期评分。
- 不向用户呈现为可执行买入指令。

### 3.3 `validated`

- horizon 对应的回测、永久 holdout 和前瞻影子验证均通过预注册门槛。
- 才允许输出校准后的预测概率，并参与 `buy/add` 门禁。
- 任一实质性模型、特征、成本或目标定义变化后生成新版本，不能继承旧版本验证证据。

风险降低动作 `reduce/exit` 不要求预测模型达到 validated，但必须有足够的持仓、风险和执行数据支持。

## 4. 总体架构

```text
用户目标、现金流、持仓、风险问答
                  |
                  v
             InvestorMandate
                  |
                  v
Provider -> typed snapshots -> DataHealthGate
                  |                 |
                  |                 +-> incomplete / remediation
                  v
 HistoricalScenarioDistribution    PortfolioRiskSnapshot
                  |                 |
     validated model (optional)     |
                  v                 v
          PredictiveForecast -> DecisionContext
                                      |
                          skill judgment + hard gates
                                      |
                                      v
                               DecisionBundle
                                      |
                              user accepts/declines
                                      |
                                      v
                         ExecutionReceipt + Ledger
                                      |
                                      v
                         automatic matured settlement
```

Python 引擎拥有事实、校验、统计、账本和硬门禁。Skill 负责舆情鉴别、反方验证和综合判断，但不能绕过能力等级、数据健康、资金约束或风险预算。

## 5. 通用约定

### 5.1 时间

- 用户目标以 `target_date` 为规范字段。
- 用户说“5 个月”时，从 `mandate_as_of` 按日历月得到精确 target date，不得静默舍入为 3 或 6 个月。
- 引擎按资产交易日历计算 `horizon_trading_sessions`。
- target date 非交易日时，terminal valuation 使用不晚于 target date 的最后可执行交易日；若用户要求 target date 前现金可用，计划必须再扣除申赎确认和到账提前量，不能把 target date 当下单日。
- 1/3/6/12 月只是报告比较锚，不是支持范围限制。
- 所有输入带 `observed_at`、`published_at` 和 `known_at`，point-in-time 消费者只能使用决策时已经 known 的数据。

### 5.2 金额、收益和损失符号

- 币种必须显式，当前仅支持 `CNY`。
- return 使用小数，例如 8% 为 `0.08`。
- `net_profit_amount` 为正表示盈利、负表示亏损。
- 风险损失字段使用正数，例如 `expected_shortfall_loss=0.12` 表示 12% 损失。
- drawdown 使用正损失幅度，例如 `max_drawdown_loss=0.20`。

### 5.3 目标分母

`target_return_basis` 必须是以下之一：

- `total_wealth`：相对全部可计量财富。
- `deployable_capital`：相对本次可投入资金。
- `invested_capital`：相对实际已投入资金。

用户没有明确时，主控必须解释差异并取得确认。不得自行选择最容易达到的分母。

外部现金流不算投资利润。对 target date `T`：

```text
net_profit_amount(T)
= terminal_liquidation_wealth(T)
+ external_withdrawals_through_T
- initial_in_scope_wealth
- external_contributions_through_T
```

从本次现金储备转为基金持仓属于内部转移，不是 external contribution。分红、卖出回款和费用属于组合内部现金流，已进入 terminal liquidation wealth，不能重复加减。

目标事件固定为：

```text
net_profit_amount(T) >= target_net_return * frozen_basis_amount
```

frozen basis amount 在 mandate 确认时保存：total_wealth 使用 initial total wealth；deployable_capital 使用 initial deployable capital；invested_capital 使用计划内现有持仓市值加已批准的拟投入本金。后续外部追加和提现只进入上式现金流调整，不改变已冻结分母；mandate 变更必须创建新版本。

## 6. 核心契约

契约使用 Pydantic discriminated unions，均带 `schema_version`。JSON 是 CLI、skills、报告和账本之间唯一跨层格式。

### 6.1 InvestorMandate

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
  "target_return_basis": "total_wealth",
  "minimum_target_success_probability": 0.60,
  "maximum_loss_amount": 10000.0,
  "maximum_terminal_loss_breach_probability": 0.10,
  "maximum_portfolio_drawdown_loss": 0.10,
  "maximum_drawdown_breach_probability": 0.10,
  "maximum_single_instrument_weight": 0.20,
  "maximum_theme_weight": 0.35,
  "planned_contributions": [],
  "planned_withdrawals": [],
  "liquidity_deadlines": [],
  "excluded_instruments": [],
  "existing_positions": [],
  "risk_source": "user_confirmed_custom"
}
```

规则：

- `total_wealth > 0`，`0 < deployable_capital <= total_wealth`。
- `target_date > mandate_as_of`，支持任意正期限。
- 目标收益明确为 target date 终值事件，不是期间曾经触及目标。
- `maximum_loss_amount` 是用户可理解的主输入；drawdown 和权重可以由风险问答推导，但推导结果必须展示并由用户确认。
- 最大损失金额、最大回撤幅度及各自可接受的违约概率是不同量纲，必须分别确认，禁止互相比大小。
- 自定义数值优先于 profile 名称；profile 只能生成待确认草案。
- 风险预算、现金流或目标分母缺失时，风险增加动作被阻断。

planned contributions/withdrawals 使用统一 ExternalCashFlow：cash_flow_id、kind、amount、currency、effective_date、certainty。只有来自或流向组合外部的现金才进入外部现金流调整；持仓与现金之间的内部转移不进入。

### 6.2 InstrumentRef

```json
{
  "instrument_id": "002611:C:user-confirmed-channel",
  "symbol": "002611",
  "name": "博时黄金ETF联接C",
  "asset_type": "otc_fund",
  "share_class": "C",
  "channel": "user_confirmed_channel",
  "currency": "CNY",
  "tradable": true,
  "availability_as_of": "2026-07-10"
}
```

同一基金不同份额类别是不同 InstrumentRef。费用、可购买渠道和代码必须对应具体 instrument，不能只用模糊基金名称。

### 6.3 PriceSeries

```json
{
  "schema_version": "1.0",
  "instrument_id": "002611:C:user-confirmed-channel",
  "basis": "unit_nav",
  "source": "akshare:fund_open_fund_info_em",
  "source_schema_version": "observed-2026-07",
  "adjustment_version": "raw",
  "calendar": "CN_FUND",
  "rows": [
    {
      "session_date": "2026-07-09",
      "published_at": "2026-07-09T22:00:00+08:00",
      "known_at": "2026-07-09T22:00:00+08:00",
      "value": 2.8274,
      "source_vintage": "sha256:0000000000000000000000000000000000000000000000000000000000000001"
    }
  ],
  "quality": {
    "status": "complete",
    "duplicate_dates": 0,
    "missing_sessions": 0,
    "nonfinite_values": 0,
    "nonpositive_values": 0,
    "stale": false,
    "notes": []
  }
}
```

支持 basis：

- `unit_nav`：基金份额估值和成交对账。
- `cumulative_nav`：保留上游累计净值，不直接计算持仓价值。
- `total_return_index`：基金分红再投资后的策略、历史场景和预测标签。
- `spot_close`：黄金等现货资产价格；成本模型另计点差、保管或渠道费用。

基金总盈亏定义为：交易和分红现金流之和，加当前份额乘 unit NAV，再减全部费用。只有当前估值价格使用 unit NAV；完整盈亏不等于单纯 NAV 比值。

基金绩效、历史场景和预测使用 total return index。黄金使用 spot close 加显式 carry/cost 规则。消费者必须声明允许的 basis，不允许静默回退。

total return index 的 adjustment version 必须解析到不可变方法：分红确认日、再投资 NAV、份额换算、缺失分红处理、输入 vintage 和 rebasing 基准。方法变化生成新版本，旧预测继续引用旧版本。

### 6.4 DataHealth

```json
{
  "status": "complete",
  "as_of": "2026-07-10T09:00:00+08:00",
  "successful_sources": 4,
  "failed_sources": 0,
  "stale_sources": 0,
  "hard_blocks": [],
  "warnings": [],
  "last_success_at": "2026-07-10T08:58:00+08:00"
}
```

状态：

- `complete`：风险增加和风险降低动作所需的关键数据均通过门禁。
- `degraded`：缺失字段已分类；门禁按动作类型判断。
- `incomplete`：关键数据不足，只能产生允许的保护性动作或 no_action。
- `failed`：无法形成 DecisionContext，只能输出系统故障。

未知状态按 incomplete。摘要只有在全部标的成功且新鲜时才能写“一切正常”。

### 6.5 FeeSchedule、CostPolicyScenario 与 PathCostRealization

FeeSchedule 是带版本的具体 instrument/channel 费率规则：

```json
{
  "fee_schedule_id": "002611:user-channel:2026-07-v1",
  "instrument_id": "002611:C:user-confirmed-channel",
  "effective_from": "2026-07-01",
  "subscription_tiers": [
    {
      "amount_lower": 0.0,
      "amount_upper": null,
      "rate": 0.0015,
      "flat_charge": 0.0,
      "charge_basis": "gross_cash"
    }
  ],
  "redemption_age_tiers": [
    {"tier_id": "age-0-7", "calendar_age_lower": 0, "calendar_age_upper": 7, "rate": 0.015, "flat_charge": 0.0},
    {"tier_id": "age-7-30", "calendar_age_lower": 7, "calendar_age_upper": 30, "rate": 0.005, "flat_charge": 0.0},
    {"tier_id": "age-30-365", "calendar_age_lower": 30, "calendar_age_upper": 365, "rate": 0.0025, "flat_charge": 0.0},
    {"tier_id": "age-365-plus", "calendar_age_lower": 365, "calendar_age_upper": null, "rate": 0.0, "flat_charge": 0.0}
  ],
  "minimum_charges": [],
  "spread_rate": 0.0,
  "tax_rules": [],
  "embedded_expenses_in_nav": ["management", "custody"],
  "source": "user_confirmed_or_public_rule",
  "uncertainty": null
}
```

subscription tier 至少包含 amount_lower/upper、rate、flat_charge 和 charge_basis；redemption tier 至少包含 calendar_age_lower/upper、rate、flat_charge 和 lot_selection_compatibility。边界采用左闭右开并在最后一档包含上界，避免 7/30/365 日落入两档或无档。

CostPolicyScenario 与 PathCostRealization 使用计划中的每笔 tranche、实际/假定确认日、持有日龄、赎回顺序和 liquidation date 计算：

```text
shares_obtained
= (tranche_cash_amount - subscription_charge) / confirmed_unit_nav

gross_terminal_proceeds
= shares_obtained * terminal_unit_nav + distribution_cash_flows

net_terminal_value
= gross_terminal_proceeds
- redemption_charges_by_lot_age
- spread_and_channel_charges
- taxes_not_embedded_in_nav
```

已反映在 NAV/TRI 中的管理费、托管费不得重复扣除。未知费率使用明确 lower/base/upper 三个场景，并冻结 fee schedule id/version。费用区间能够反转结论时，风险增加动作被阻断。

CostPolicyScenario 本身也是不可变 Pydantic 契约。它冻结规则和入场份额，但不冻结会随收益路径变化的赎回金额：

```json
{
  "cost_policy_scenario_id": "002611:2027-02-10:upper-v1",
  "scenario": "upper",
  "instrument_id": "002611:C:user-confirmed-channel",
  "fee_schedule_id": "002611:user-channel:2026-07-v1",
  "liquidation_date": "2027-02-10",
  "terminal_valuation_rule": "last_known_unit_nav_then_redeem",
  "lot_disposal_policy": "fifo",
  "tranches": [
    {
      "tranche_id": "tranche-001",
      "cash_amount": 8000.0,
      "order_at": "2026-07-11T10:05:00+08:00",
      "confirmation_rule": "order_before_15h_uses_same_session_nav",
      "assumed_confirmation_date": "2026-07-11",
      "subscription_charge_basis": 8000.0,
      "subscription_charge": 12.0,
      "net_cash_invested": 7988.0,
      "assumed_unit_nav": 2.8219,
      "shares_obtained": 2830.7169,
      "calendar_holding_days_at_liquidation": 214,
      "redemption_tier_id": "age-30-365"
    }
  ],
  "spread_and_channel_charges": 0.0,
  "tax_charges": 0.0,
  "embedded_expenses_excluded_from_explicit_cost": ["management", "custody"],
  "calculation_version": "fund-cost-v1"
}
```

每条历史或预测路径单独生成 PathCostRealization：

```json
{
  "path_cost_realization_id": "path-001:cost-upper-v1",
  "path_id": "path-001",
  "cost_policy_scenario_id": "002611:2027-02-10:upper-v1",
  "path_representation": "total_return_index",
  "gross_terminal_proceeds": 8200.0,
  "distribution_cash_flows": null,
  "redemption_charge_basis": 8200.0,
  "redemption_charge": 20.5,
  "other_explicit_cost": 0.0,
  "net_terminal_value": 8179.5
}
```

使用 total_return_index 的路径已经包含分红再投资，distribution_cash_flows 必须为 null。使用 unit_nav_plus_cash_distributions 的实际账本路径可以添加分红现金流，但不得同时使用 TRI 增长。subscription charge 已通过较少 shares obtained 体现，不再次从 terminal proceeds 扣除；redemption charge 必须按每条路径的 terminal proceeds 和 lot age 重算。风险增加门禁必须在 admissible upper cost policy 下对每条路径重算后仍通过。

### 6.6 HistoricalScenarioDistribution

这是描述性历史对象，不是预测。

```json
{
  "schema_version": "1.0",
  "historical_scenario_id": "historical-scenario-001",
  "capability_level": "descriptive",
  "instrument_id": "002611:C:user-confirmed-channel",
  "origin_as_of": "2026-07-10",
  "target_date": "2027-02-10",
  "horizon_trading_sessions": 144,
  "event": "terminal_net_return",
  "cost_policy_scenario_id": "002611:2027-02-10:base-v1",
  "target_return": 0.08,
  "target_return_basis": "invested_capital",
  "metrics": {
    "median": {"estimate": null, "interval": null, "sufficient": false},
    "q10": {"estimate": null, "interval": null, "sufficient": false},
    "q90": {"estimate": null, "interval": null, "sufficient": false},
    "historical_target_frequency": {"estimate": null, "interval": null, "sufficient": false},
    "expected_shortfall_95_loss": {"estimate": null, "interval": null, "tail_count": 0, "sufficient": false}
  },
  "methodology": {
    "input_artifacts": [
      {
        "artifact_id": "tri-002611-2016-2026-v1",
        "basis": "total_return_index",
        "content_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000005",
        "source_vintage": "akshare-fund-20260710",
        "adjustment_version": "fund-tri-reinvest-distribution-v1"
      },
      {
        "artifact_id": "unit-nav-002611-2016-2026-v1",
        "basis": "unit_nav",
        "content_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000006",
        "source_vintage": "akshare-fund-20260710",
        "adjustment_version": "raw"
      }
    ],
    "eligible_origin_rule_id": "all-known-at-origin-v1",
    "non_overlap_selection_rule": "first-origin-then-step-horizon",
    "quantile_estimator_id": "linear-type7-v1",
    "bootstrap_type": "moving_block_on_origin_returns",
    "bootstrap_interval_method_id": "percentile-two-sided-v1",
    "target_frequency_interval_method_id": "wilson-95-v1",
    "bootstrap_seed": 20260710,
    "bootstrap_replicates": 2000,
    "bootstrap_block_length_origins": 144,
    "calendar_version": "CN_FUND_2026_v1"
  },
  "sample": {
    "eligible_origins": 12,
    "non_overlapping_outcomes": 8,
    "sufficiency": "insufficient",
    "insufficient_metrics": ["median", "q10", "q90", "historical_target_frequency", "expected_shortfall_95_loss"]
  }
}
```

规则：

- insufficient 指标必须为 null，不得保留精确数字。
- 不使用 `p_target`、`p_positive` 或 confidence 等未来语义。
- 相邻重叠窗口不能被当作独立样本。
- 场景分布和估计不确定性分开存储。
- price position 只能作为路径状态，不能命名为 fundamental valuation。
- input artifact、source vintage、adjustment、cost policy、origin rule、quantile estimator 和 interval method 任一变化都生成新的 historical scenario id。

### 6.7 PredictiveForecast

PredictiveForecast 可处于 shadow 或 validated；二者使用同一冻结 schema，只有 validated 才 execution eligible：

以下数值只演示 schema，不代表当前仓库已经拥有 validated 模型或这些实测结果。

```json
{
  "schema_version": "1.0",
  "capability_level": "validated",
  "execution_eligible": true,
  "model_version": "h144-v3",
  "instrument_id": "002611:C:user-confirmed-channel",
  "forecast_origin": "2026-07-10T09:00:00+08:00",
  "target_date": "2027-02-10",
  "event": "terminal_net_return",
  "target_return": 0.08,
  "target_return_basis": "invested_capital",
  "net_return_distribution": {
    "q10": -0.10,
    "median": 0.05,
    "q90": 0.21
  },
  "probability_net_positive": 0.61,
  "probability_net_positive_interval": [0.52, 0.69],
  "probability_target": 0.38,
  "probability_target_interval": [0.29, 0.47],
  "expected_shortfall_95_loss": null,
  "validation_record_id": "h144-v3-validation"
}
```

shadow Forecast 使用相同字段，但 `capability_level=shadow`、`execution_eligible=false`，其概率只进入预注册评分账本，不向用户展示为可执行预测。`confidence` 不再作为无定义单点数字。tail 支持不足时 expected shortfall 必须为 null，即使其他概率通过门槛。

### 6.8 ValidationRecord

任何 PredictiveForecast 和可执行风险增加动作都必须引用不可变 ValidationRecord：

```json
{
  "validation_record_id": "h144-v3-validation",
  "model_lineage_id": "fund-terminal-return-lineage-001",
  "model_scope": "instrument",
  "model_version": "h144-v3",
  "event_definition": {
    "event_id": "terminal-net-positive-h144",
    "kind": "terminal_net_return_at_or_above",
    "threshold": 0.0,
    "target_return_basis": "invested_capital",
    "execution_lag_rule": "next_executable_session",
    "liquidation_cost_rule": "upper_admissible_cost_scenario"
  },
  "horizon_trading_sessions": 144,
  "target_return_basis": "invested_capital",
  "point_in_time_universe_id": "cn-funds-2016-2026-v2",
  "feature_schema_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000002",
  "fee_schedule_family_version": "fund-fees-2026-v1",
  "preregistration_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000003",
  "decision_policy_id": "risk-increase-policy-v1",
  "benchmark_id": "same-category-net-climatology-h144-v1",
  "holdout_registry": {
    "holdout_id": "holdout-2025h2-lineage-001",
    "lineage_first_consumed_at": "2026-01-15T09:00:00+08:00",
    "reusable_by_descendant_versions": false
  },
  "walk_forward": {
    "origins": 96,
    "purge_sessions": 144,
    "embargo_sessions": 144,
    "permanent_holdout_used_once": true
  },
  "shadow": {
    "started_at": "2025-07-01",
    "ended_at": "2026-07-10",
    "eligible_events": 48,
    "settled_events": 48,
    "cluster_adjusted_effective_events": 42
  },
  "metrics": {
    "brier_skill_interval": [0.01, 0.09],
    "crps_skill_interval": [0.01, 0.07],
    "pit_uniformity_test_pvalue": 0.21,
    "return_threshold_grid": [0.0, 0.04, 0.08, 0.12],
    "calibration_intercept_interval": [-0.08, 0.06],
    "calibration_slope_interval": [0.82, 1.17],
    "prediction_interval_nominal_coverage": 0.90,
    "prediction_interval_coverage": 0.89,
    "prediction_interval_sharpness": 0.23,
    "net_benchmark_return_interval": [0.002, 0.031],
    "drawdown_budget_breach_interval": [0.03, 0.09]
  },
  "promotion_result": "validated",
  "issued_at": "2026-07-10T09:00:00+08:00"
}
```

ValidationRecord 的 promotion result 只能由预注册 verifier 根据冻结输入生成。Skill、CLI 参数或用户不能手工把 shadow 改为 validated。

Brier/calibration 只评价 event_definition 中固定阈值的二元事件。任意用户目标从完整 predictive CDF 读取，其有效性由 CRPS、PIT、固定 threshold grid 的 calibration 和 prediction interval coverage 共同证明，不能把不同用户目标混成一个 Brier 事件。

ValidationRecord 可以记录 promotion_result=shadow/rejected/validated。永久 holdout 在 model lineage 首次读取后即被消费；创建新版本不会让同一 holdout 重新变成未见数据。新 lineage 若继承特征、阈值或研究结论，也不能声称该 holdout 未见。

ValidationRecord 的 model_scope 只能是 instrument 或 portfolio_joint。portfolio_joint 记录还必须冻结 ledger/action-set schema、joint scenario policy、cash-flow policy、cost scenario family 和 correlation/dependence method；单标的 validation record 不能提升组合预测能力等级。

### 6.9 PortfolioGoalForecast

单标的预测不能直接回答用户整体赚多少钱。组合目标对象必须包含现金、已有持仓、拟议交易、费用和相关路径：

```json
{
  "schema_version": "1.0",
  "mandate_id": "mandate-001",
  "ledger_snapshot_id": "ledger-20260710-001",
  "proposed_action_set_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000004",
  "cost_policy_scenario_ids": ["002611:2027-02-10:upper-v1"],
  "joint_model_version": "portfolio-joint-h144-v1",
  "validation_record_id": null,
  "calendar_version": "CN_FUND_2026_v1",
  "horizon_trading_sessions": 144,
  "forecast_origin": "2026-07-10T09:00:00+08:00",
  "target_date": "2027-02-10",
  "currency": "CNY",
  "target_return_basis": "total_wealth",
  "baseline_amount": 100000.0,
  "target_net_profit_amount": 8000.0,
  "cash_return_assumption": 0.0,
  "planned_cash_flows": [],
  "net_profit_amount": {
    "p10": -9000.0,
    "median": 3500.0,
    "p90": 15000.0
  },
  "net_return": {
    "p10": -0.09,
    "median": 0.035,
    "p90": 0.15
  },
  "probability_target": null,
  "probability_target_interval": null,
  "probability_drawdown_budget_breach": null,
  "probability_drawdown_budget_breach_interval": null,
  "probability_terminal_loss_breach": null,
  "probability_terminal_loss_breach_interval": null,
  "capability_level": "descriptive"
}
```

描述性组合场景的 probability 字段和 validation_record_id 必须为 null。Validated joint portfolio model 才能填充，并且 capability level 必须由 validation record 派生。ledger snapshot、action-set hash、cost policy scenarios、calendar、target date 或 joint policy 任一不同都不能复用旧 forecast。减少投入只能降低金额风险，不能被描述成提高同一分母下目标收益概率。

### 6.10 PortfolioRiskSnapshot

风险字段必须同 horizon、同组合路径和同分母：

```json
{
  "risk_snapshot_id": "risk-001",
  "mandate_id": "mandate-001",
  "ledger_snapshot_id": "ledger-20260710-001",
  "proposed_action_set_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000004",
  "joint_model_version": "portfolio-joint-h144-v1",
  "validation_record_id": null,
  "cost_policy_scenario_ids": ["002611:2027-02-10:upper-v1"],
  "calendar_version": "CN_FUND_2026_v1",
  "target_date": "2027-02-10",
  "horizon_trading_sessions": 144,
  "baseline_amount": 100000.0,
  "drawdown_event_threshold": 0.10,
  "maximum_drawdown_loss_distribution": {
    "p50": 0.08,
    "p90": 0.16
  },
  "probability_drawdown_budget_breach": null,
  "probability_drawdown_budget_breach_interval": null,
  "terminal_loss_event_amount": 10000.0,
  "probability_terminal_loss_breach": null,
  "probability_terminal_loss_breach_interval": null,
  "expected_shortfall_95_loss": null,
  "expected_shortfall_95_amount": null,
  "single_instrument_weights": {
    "002611:C:user-confirmed-channel": 0.18
  },
  "theme_weights": {
    "gold": 0.18
  },
  "breaches": [],
  "capability_level": "descriptive"
}
```

没有 joint path distribution 时，drawdown/terminal-loss breach probability 和 portfolio expected shortfall 为 null，不得用单资产历史回撤相加冒充。capability level 由对应 joint validation record 派生，不能由调用方填写。

### 6.11 DecisionContext

DecisionContext 是判断层唯一输入，不能由各 skill 自行拼接零散命令输出：

```json
{
  "schema_version": "1.0",
  "context_id": "context-20260710-001",
  "generated_at": "2026-07-10T09:00:00+08:00",
  "mandate_id": "mandate-001",
  "universe_snapshot_id": "cn-funds-20260710",
  "data_health_id": "health-20260710-001",
  "historical_scenario_ids": [],
  "predictive_forecast_ids": [],
  "portfolio_goal_forecast_id": "goal-forecast-001",
  "portfolio_risk_snapshot_id": "risk-001",
  "ledger_snapshot_id": "ledger-20260710-001",
  "capability_level": "descriptive",
  "allowed_actions": ["hold", "reduce", "exit", "avoid", "no_action"],
  "hard_blocks": ["validated_forecast_missing_for_risk_increase"],
  "warnings": []
}
```

Python gate 生成 allowed actions 和 hard blocks。Skill 只能从 allowed actions 中选择，不能通过自由文本或修改 JSON 绕过。

## 7. 可执行动作契约

### 7.1 TypedTrigger

所有条件使用 typed trigger，不存只有人能猜的自由文本：

- `date_reached`
- `unit_nav_at_or_below`
- `unit_nav_at_or_above`
- `data_health_is`
- `valuation_range`
- `trend_confirmed_for_sessions`
- `drawdown_budget_breached`
- `fundamental_fact_changed`
- `decision_expired`

Trigger 包含字段、比较符、阈值、连续确认期、数据源、有效期和解释文本。

```json
{
  "trigger_id": "trigger-001",
  "kind": "trend_confirmed_for_sessions",
  "metric": "ma20_above_ma60",
  "operator": "is_true",
  "threshold": true,
  "confirm_sessions": 3,
  "source_snapshot_type": "price_series",
  "valid_from": "2026-07-10T09:00:00+08:00",
  "valid_until": "2026-07-17T15:00:00+08:00",
  "explanation": "连续三个交易日 MA20 高于 MA60 后重新评估"
}
```

多个 trigger 通过不可变 TriggerExpression 组合：

```json
{
  "expression_id": "expression-001",
  "operator": "all",
  "children": [
    {"trigger_id": "trigger-001"},
    {
      "operator": "sequence",
      "children": [
        {"trigger_id": "trigger-data-complete"},
        {"trigger_id": "trigger-nav-below-limit"}
      ],
      "maximum_gap_sessions": 5
    }
  ],
  "fire_policy": "once",
  "reset_policy": "never",
  "evaluated_at": "2026-07-10T09:00:00+08:00"
}
```

operator 只能是 all/any/sequence。每个 tranche 引用一个 expression id；满足时间是表达式首次整体成立的时间。fire policy、reset/cooldown 和过期行为必须显式，不能由调用方临时解释。

### 7.2 动作专属 payload

`DecisionAction` 是 discriminated union。

所有动作继承 ActionBase：action_id、kind、context_id、priority、valid_from、valid_until、reason_codes、supporting_evidence_ids、counter_evidence_ids。除 bundle-scoped no_action 外，所有动作必须有 instrument_id；涉及现有持仓的 hold/reduce/exit 还必须有 position_snapshot_id。

`proposed_action_set_hash` 使用 `quantfox-canonical-json-v1`：UTF-8、对象键按 Unicode code point 升序、数组保留业务顺序、Decimal 使用去除无意义尾零的十进制字符串、时间统一 RFC3339 UTC、无空白，并在计算时排除 hash 字段本身。序列化版本进入 hash 前缀。

| kind | 核心必填字段 | 不允许含糊的字段 |
|---|---|---|
| `buy` / `add` | instrument_id、max_total_amount、target_weight_after、tranches、forecast_artifact_id、expiry | “适量买入” |
| `hold` | instrument_id、position_snapshot_id、review_by、review_triggers、reduce_triggers、exit_triggers | “继续观察” |
| `reduce` | instrument_id、position_snapshot_id、sell_amount/shares/fraction、target_shares_after、target_weight_after、lot_policy、expiry | “减一点” |
| `exit` | instrument_id、position_snapshot_id、target_shares_after=0、lot_policy、expiry、partial_fill_policy | “考虑离场” |
| `avoid` | instrument_id、reason_code、reconsider_trigger_expression_id、review_by | “暂时谨慎” |
| `no_action` | reason_code、reconsider_trigger_expression_id、review_by；bundle scoped，不含 instrument_id | “暂时谨慎” |

#### Buy/Add

必须包含：

- instrument。
- 最大总金额和目标交易后权重。
- 每笔 tranche 的金额、最早/最晚日期、NAV/条件上限。
- 每笔 tranche_id 和 trigger expression id。
- 取消条件和 Decision expiry。
- 目标日期、forecast artifact reference 和风险预算影响；executable 模式下该 artifact 必须 validated。

#### Hold

必须包含：

- 当前持仓快照。
- 最晚复查日期。
- 提前复查 triggers。
- reduce/exit 的失效条件。

#### Reduce

必须包含：

- 卖出金额、份额或比例中的至少一种。
- 目标交易后份额和权重。
- lot 选择规则及预计费用。
- 最晚执行日期、价格条件和后续复查。

#### Exit

必须包含：

- 目标剩余份额必须为零。
- lot 选择、预计费用、执行期限和未完全成交处理。

#### Avoid/NoAction

必须包含：

- 原因代码。
- 重新考虑的 typed triggers。
- 下次最晚复查日期。

### 7.3 DecisionBundle

```json
{
  "schema_version": "1.0",
  "bundle_id": "server-generated",
  "mandate_id": "mandate-001",
  "decision_at": "server-generated",
  "valid_until": "2026-07-17T15:00:00+08:00",
  "bundle_mode": "informational",
  "execution_eligible": false,
  "capability_level": "descriptive",
  "universe_snapshot_id": "cn-funds-20260710",
  "ranked_candidates": [
    {
      "instrument_id": "002611:C:user-confirmed-channel",
      "rank": 1,
      "selection_status": "descriptive_only"
    }
  ],
  "rejected_candidates": [
    {
      "instrument_id": "000001:A:user-confirmed-channel",
      "reason_code": "data_incomplete"
    }
  ],
  "actions": [
    {
      "action_id": "action-001",
      "kind": "no_action",
      "reason_code": "validated_forecast_missing",
      "reconsider_trigger_expression_id": "expression-001",
      "review_by": "2026-07-17T15:00:00+08:00"
    }
  ],
  "portfolio_after_proposed_actions": {
    "invested_amount": 0.0,
    "cash_balance_after": 100000.0,
    "instrument_weights": {
      "002611:C:user-confirmed-channel": 0.0
    },
    "theme_weights": {
      "gold": 0.0
    }
  },
  "goal_forecast_id": "goal-forecast-001",
  "risk_snapshot_id": "risk-001",
  "supporting_evidence": ["historical-scenario-001"],
  "counter_evidence": ["predictive-validation-missing"],
  "hard_blocks": ["validated_forecast_missing_for_risk_increase"],
  "manual_confirmation_required": false
}
```

规则：

- actions 必须作为一个组合共同校验，金额之和不得超过 deployable capital。
- 风险和目标预测使用 actions 执行后的组合。
- ranked candidate 必须是具体 InstrumentRef；每个 rejected candidate 带原因。
- 风险增加 bundle 必须是 validated；descriptive/shadow bundle 只能记录 hypothetical actions，不得展示为执行指令。
- 风险降低 bundle 可以在较低能力等级下产生，但门禁按第 8 节执行。
- bundle_mode 只能是 informational/shadow/executable/protective。shadow bundle 的 execution_eligible 必须为 false，不能进入 accepted、receipt 或 transaction 状态。protective 只允许 reduce/exit/manual_review。
- capability level、bundle mode 和 execution eligibility 由 Python gate 从 validation records 和 action types 派生，调用方不能自行赋值。

## 8. 动作门禁矩阵

| 条件 | Buy/Add | Hold | Reduce/Exit | Avoid/NoAction |
|---|---|---|---|---|
| 数据 complete | 必须 | 推荐 | 推荐 | 非必须 |
| 数据 degraded | 阻断 | 允许并标警告 | 若持仓和风险字段足够则允许 | 允许 |
| 数据 incomplete | 阻断 | 阻断；改为 data_incomplete no_action | 仅允许明确的保护性人工复核或已确认硬风险 | 允许 |
| validated forecast | 必须 | 非必须 | 非必须 | 非必须 |
| 风险预算缺失 | 阻断 | 允许收集信息 | 允许降低风险 | 允许 |
| 目标不支持 | 阻断新增风险 | 允许 | 不阻断降低风险 | 允许 |
| 交易后仍超集中度 | 阻断 | 标风险 | 只要减少暴露即可允许分步降低 | 允许 |
| 账本不一致 | 阻断 | 阻断正常结论 | 只允许人工核对，不自动计算卖出量 | 允许 |

`reduce/exit` 不能因目标不现实、预测缺失或一次减仓后仍超限而被阻断。它必须证明动作减少了哪项风险，并明确剩余风险。

## 9. 人工执行生命周期

DecisionBundle 状态：

```text
proposed -> accepted -> partially_executed -> executed
proposed -> declined
proposed -> expired
accepted -> cancelled
partially_executed -> cancelled | executed | expired
recorded -> expired
```

只有 bundle_mode=executable/protective 且 execution_eligible=true 的 bundle 可以进入 accepted。informational/shadow 永远停留在 recorded/expired，不得生成 ExecutionReceipt。

用户确认不等于成交。每次实际操作生成 ExecutionReceipt：

```json
{
  "receipt_id": "receipt-001",
  "bundle_id": "bundle-001",
  "action_id": "action-buy-001",
  "tranche_id": "tranche-001",
  "instrument_id": "002611:C:user-confirmed-channel",
  "source_position_snapshot_id": "position-before-001",
  "status": "executed",
  "confirmed_at": "2026-07-11T10:00:00+08:00",
  "order_at": "2026-07-11T10:05:00+08:00",
  "confirmed_nav_date": "2026-07-11",
  "actual_nav": 2.8219,
  "actual_amount": 8000.0,
  "actual_shares": 2834.9693,
  "actual_fees": 12.0,
  "created_lot_ids": ["lot-20260711-001"],
  "consumed_lot_ids": [],
  "ledger_transaction_ids": ["tx-buy-001", "tx-fee-001"],
  "deviation_from_plan": {
    "amount_delta": 0.0,
    "nav_delta": -0.0038,
    "fee_delta": 0.0
  }
}
```

后续持仓判断只能使用已执行 receipt 聚合的真实仓位。拒绝、过期和未完成动作不得进入持仓。

buy/add receipt 必须有 tranche_id，首次 buy 的 source_position_snapshot_id 可以为 null；hold/reduce/exit 必须有 source position snapshot。无 tranche 设计的 reduce/exit receipt 可以令 tranche_id 为 null，但 action id、instrument id 和 ledger transaction ids 始终必填。

TriggerExpression 保持不可变。每次评估单独追加 TriggerEvaluation，记录 expression id、各叶节点输入 snapshot、evaluated_at、结果、首次成立时间、fire count 和是否过期，避免重放时覆盖历史判断。

## 10. 账本与结算

### 10.1 持仓状态

```text
watching -> holding -> closed -> archived
watching -> archived
holding  -> holding  (加仓/部分卖出)
```

存在开放份额时必须是 holding。普通 add 不能执行 holding -> watching。

### 10.2 Append-only 交易账本

事件类型：buy、sell、fee、distribution、adjustment。持仓、平均成本、已实现/未实现收益从事件聚合。remove 只归档 watch 配置，不删除交易历史。

### 10.3 Prediction/outcome

- 服务端生成 decision_at。
- 冻结 instrument、basis、as_of、source vintage、fee schedule、target event 和模型版本。
- outcome 命令只接收 prediction/decision id，从冻结记录解析资产。
- `settle-all-matured` 幂等结算所有 eligible 记录。
- 按 horizon、event、signal 和 model version 独立复盘。
- review 输出 eligible、settled、missing coverage。
- 版本使用整数或语义版本，不用文本字典序。
- 预测 outcome 与用户实际交易 P&L 分开：前者评估模型，后者评估实际执行。

## 11. 统计协议

### 11.1 描述性历史场景

- 目标标签是 forecast origin 之后第一个可执行时点至 target date 的 terminal net return。
- 标签使用当时可知的数据、明确交易日历和冻结费用场景。
- 默认报告所有 eligible origins；重叠数量和保守的 non-overlapping outcomes 分开报告。
- 对按 forecast origin 排序的 terminal return 序列做移动块 bootstrap，固定随机种子并重复 2,000 次；block length 以 origin 间隔计，覆盖至少一个完整 horizon 的重叠范围。它只估计统计量不确定性，不把重复采样当新信息，也不生成新的市场 regime。
- 条件 analog 在独立预测设计通过前不用于可执行动作。

指标级充分性：

- median：至少 20 个 non-overlapping outcomes，否则 null。
- q10/q90：至少 50 个 non-overlapping outcomes，否则 null。
- 历史目标频率：至少 40 个 non-overlapping outcomes，且 Wilson 95% 区间宽度不超过 0.30，否则 null。
- historical expected shortfall 95%：至少 200 个 non-overlapping outcomes、至少 10 个 tail observations，且 95% 区间宽度不超过 0.20，否则 null。

所有指标还必须有有限 estimator interval；return quantile 区间宽度超过 0.30 时标记 insufficient。原始数量达到门槛但精度未达到时仍返回 null。

这些是保守的首版门槛，不是验证模型晋级的充分条件。

### 11.2 Predictive 模型晋级

每个 horizon/model version 预注册：

- 精确 target event 和执行时点。
- point-in-time universe、数据 vintage 和 publication lag。
- 训练窗、验证窗、预测频率和重训频率。
- expanding walk-forward。
- purge 所有与验证标签重叠的训练样本。
- embargo 至少覆盖该 horizon。
- 嵌套调参，不得使用永久 holdout 选模型。
- 永久 holdout 只在候选冻结后评一次。

晋级到 shadow 的最低要求：

- 相对 horizon/类别 climatology 的 Brier skill 下界大于 0。
- calibration intercept/slope 的区间不显示严重系统偏差。
- 预测区间同时报告 coverage 和 sharpness。
- 成本后基准比较、换手和真实日度回撤完整。

晋级到 validated 还要求：

- 至少一个完整 horizon 的前瞻到期记录。
- 至少 40 个 non-overlapping 或按 event cluster 修正后的有效预测事件。
- 全部预注册 eligible forecasts 均已结算，coverage 100%。
- Brier skill、净基准收益和 drawdown budget breach 指标的预注册门槛均通过置信区间检验。
- 结果按 action-selected 和 all-eligible 两种口径同时报告，不能靠高弃权隐藏失败。

具体数值阈值在预测子项目中用基准数据预注册；本核心只负责强制保存和验证 validation record。

## 12. 目标可行性

Feasibility 状态：

- `descriptive_only`：只有历史场景，不得称目标概率。
- `supported`：validated PortfolioGoalForecast 的目标概率区间下界不低于用户确认的 minimum probability，drawdown breach 概率区间上界不高于 maximum_drawdown_breach_probability，且 terminal loss breach 概率区间上界不高于 maximum_terminal_loss_breach_probability。
- `conditional`：当前不满足，但 typed entry conditions 成立后可重新计算；条件本身必须由 validated 模型支持。
- `outside_evidence`：目标高于可验证证据支持范围。
- `insufficient_data`：关键分布或联合路径不可用。

目标事件默认是 target date 的组合净终值，不是期间曾触及。必须纳入：

- 目标分母。
- 现金储备及现金收益假设。
- 已有持仓。
- 分批投入、追加和提现。
- 实际/估计费用和税。
- target date 的清算费用。
- 组合相关路径和集中度。

在 descriptive_only 阶段，系统只能展示历史场景和目标缺口，不能回答“达到目标的未来概率是 X%”。

## 13. 数据和错误处理

- Provider 有连接/读取 timeout、有限重试和全局 deadline。
- 返回 source、schema、known_at 和内容 hash。
- 重复日期、非正值、非有限值、断档、异常复权和 schema 漂移均进入 DataHealth。
- 缓存必须显示最后成功时间，不能伪装为实时数据。
- watch 摘要报告成功、失败、过期数量；false green 定义为存在关键失败却输出 healthy/normal。
- 本地单用户数据目录 0700、账本/凭证 0600。
- 凭证使用隐藏输入，不进入 shell history。
- 默认不采集遥测，不上传账本、持仓、金额或邮箱。
- 调用外部模型前展示将发送的字段；默认去除账户标识、邮箱、实际总资产和未必要的交易明细。
- 本地保存 retention policy、备份位置和最近恢复验证时间；删除使用显式命令并保留审计记录。

报告 HTML 清洗、PDF 禁网、SMTP 去重和打包排除属于单独的安全/发布子项目，不纳入本核心首个实施计划，但不能在启用用户动作前遗漏。

## 14. 数据库迁移

1. 检查当前 schema 和不变量。
2. 创建时间戳备份并验证可打开。
3. 在事务中创建新表和 CHECK/foreign key。
4. 迁移合法 predictions、outcomes、holdings 和 lots。
5. 无法自动解释的数据进入 migration issues，不静默丢弃。
6. 校验份额、金额、事件数、outcome 数和 hash。
7. 原子切换新账本。
8. 提供恢复命令和迁移审计记录。

SQLite 开启 foreign keys、WAL、busy timeout。CLI、Pydantic 和数据库执行三层有限正数、日期和状态校验。

## 15. 测试与验收

### 15.1 已知缺陷回归

- 取价部分或全部失败时不得输出“一切正常”。
- unit NAV/cumulative NAV/total return 不得混算。
- 毛正净负时不得显示正净赔率。
- holding 重复 add 不得降级，lots 保持一致。
- B 的行情不得结算 A 的 prediction。
- 负数、零、NaN、inf、非法日期和 horizon<=0 全部快速拒绝。
- 卖出和 remove 不得删除历史。
- fresh data dir/ledger 权限正确。

### 15.2 契约测试

- 任意 target date：2、5、7、18 个月案例均不舍入。
- target return basis 三种分母计算不同且正确。
- insufficient 历史场景的概率、tail 和 quantile 字段为 null。
- descriptive/shadow bundle 不能产生用户可执行 buy/add。
- 动作专属必填字段和 typed triggers 校验。
- bundle 金额、现金、单标的和主题权重共同守恒。
- risk-increasing/risk-reducing 门禁矩阵全覆盖。
- shadow forecast 能被到期评分，但不能进入 accepted/receipt/transaction。
- validation record 的 target date/horizon/event/basis 与 forecast 不一致时拒绝。
- portfolio forecast 的 ledger snapshot、action-set hash、cost scenarios 或 calendar 与 bundle 不一致时拒绝复用。
- capability level 由 validation record 派生；调用方伪造 validated 时拒绝。

### 15.3 账本测试

- proposed、accepted、declined、expired、partial、executed、cancelled 全状态。
- Decision -> receipt -> transaction -> position 完整追踪。
- 多 tranche receipt 缺 tranche_id、instrument_id 或 ledger transaction id 时拒绝。
- 买入、加仓、部分卖出、全部卖出、分红和费用。
- 事务回滚、并发、重复迁移、备份和恢复。
- 自动全量结算 coverage 100%。

### 15.4 端到端场景

1. 10 万总财富、6 万可投入、7 个月目标 8%、最大亏损 1 万：系统保留精确 target date 和目标分母。
2. 3 个月目标 20%、最大亏损 5,000：descriptive 阶段只显示证据不足；validated 阶段若超证据范围则 outside_evidence。
3. 用户不理解 drawdown：风险问答从可承受金额推导草案并要求确认。
4. 多个候选动作合计超过可投入资金：bundle 校验失败。
5. 数据失败：buy/add 阻断，但已确认硬风险的 reduce/exit 不因目标失败而阻断。
6. 用户只执行第一笔：receipt 标 partial，后续持仓按实际份额重算。
7. Decision 过期后价格触发：不得执行旧指令，必须重新计算。

## 16. 子项目完成定义

本核心完成需要同时证明：

- 契约模型和门禁实现。
- 数据 basis、费用和账本不变量有回归测试。
- 现有账本迁移和恢复演练通过。
- 描述性输出不会出现未来概率措辞。
- 未经 validated record 的风险增加动作无法通过 schema/门禁。
- 任意期限、目标分母、人工执行和组合资金守恒均有端到端证据。

这只证明“可信核心”完成，不代表顶级量化 skills 总目标完成。

## 17. 后续设计顺序

1. `quant-commander` 产品流：风险问答、目标澄清、候选生成、组合冲突处理、动作排序、监控和呈现。
2. 预测验证：point-in-time universe、条件特征、walk-forward、holdout、shadow 和晋级阈值。
3. 7 个 skills 迁移：全部消费 DecisionContext/DecisionBundle。
4. 筛选与组合：具体 InstrumentRef、类别内排名、持仓穿透、相关性和风险贡献。
5. 安全与运行：报告、通知、权限、缓存、CI 和打包。

所有后续设计必须保持本契约的诚实能力等级和动作门禁，不得为了更“敢说”而绕过验证。

## 18. 评审问题关闭记录

- 样本不足却 buy：改为 insufficient 字段 null，descriptive/shadow 禁止执行 buy/add。
- 描述性历史冒充预测：拆分 HistoricalScenarioDistribution 和 PredictiveForecast。
- basis 与盈亏矛盾：拆分估值价格、总回报标签和交易现金流 P&L。
- 费用不可复现：新增 versioned FeeSchedule、lot-age 和费用传播。
- 有效样本与 tail 不成立：增加 metric-specific sufficiency。
- p_target 语义缺失：定义 exact target date、terminal event、分母和区间。
- CVaR/drawdown 不同口径：统一组合 horizon、正损失符号和 joint path 要求。
- 任意月份被舍入：target date 成为规范字段。
- “何时、多少”字段不足：改为 typed triggers 和 action-specific payload。
- 单标的无法回答“买什么”：新增组合级 DecisionBundle 和具体 InstrumentRef。
- 手工执行断链：新增 Decision execution state machine 和 ExecutionReceipt。
- 风险降低被硬阻断：新增 action-specific gate matrix。
