# 证据卡字段解读指南（schema v2）

`quantfox evidence <标的> --format json` 输出一张证据卡。下面逐块说明字段含义与**怎么读成多空/风险信号**。记住：这些是客观证据，最终判断是你的；标准卡没覆盖的，用 `quantfox fetch` 拿原始序列自己算。

## asset
`symbol` / `name` / `type`（otc_fund=场外基金，gold=黄金）。

## price
- `latest` / `latest_date`：最新净值/价及日期（基金 T+1，通常是昨天）。

## returns（区间收益，小数，0.05=+5%）
`1w / 1m / 3m / 6m / 1y / ytd`。多周期背离要留意：如 1y 大涨但 1m 大跌 = 高位回调。

## metrics（风险 / 绩效——本工具的专业内核，两资产都算）
默认无风险利率 2%、年化 √252、VaR/CVaR 为日频历史法 95%。
- `cagr`：年化收益（复合）。长期赚钱能力。
- `ann_vol`：年化波动率。越高越颠簸（黄金/宽基约 0.15~0.30）。
- `max_drawdown`：最大回撤（负数）。**最直观的风险**，-0.5 意味着历史上曾腰斩。
- `sharpe`：夏普 = 单位总风险的超额回报。>1 优秀，0.5~1 尚可，<0 亏。
- `sortino`：索提诺 = 只惩罚下跌波动的夏普，通常比夏普更贴合体感。
- `calmar`：卡玛 = 年化收益 / 最大回撤。衡量"为赚这点钱要承受多大回撤"。
- `var95` / `cvar95`：95% 单日风险价值 / 尾部平均亏损（都是负数）。VaR95=-0.02 ≈ "坏日子里单日约亏 2%"，CVaR 是更坏那 5% 的平均。
- `downside_dev`：下行标准差。
- `win_rate`：日胜率（上涨交易日占比）。
- `skew` / `kurtosis`：偏度/峰度。负偏 + 高峰度 = 尾部有暴跌风险。

## indicators（技术指标）
- `ma`：`ma5/10/20/60/120/250` + `alignment`（多头=偏多，空头=偏空，纠缠=无趋势→倾向观望）。
- `ema`：`ema12/ema26`。
- `macd`：`dif/dea/hist` + `state`（金叉=动能转多，死叉=转空，—=无新交叉，看 hist 正负）。
- `rsi`：`rsi6/rsi12/rsi24`。>70~80 超买（短期或回调），<20~30 超卖（短期或反弹）。
- `roc12` / `mom10`：变动率 / 动量，正=上行动能。
- `boll`：`pos`（上轨附近偏热/下轨附近偏冷/中轨）、`upper/mid/lower`、`bandwidth`（带宽骤缩常预示变盘）。
- `hv`：`hv20/hv60` 历史波动率。
- `price_levels`：`high_52w/low_52w` 近一年高低，`pct_position`（0~1，当前在高低区间的位置；接近 1=贵，接近 0=便宜但要分辨是否下跌趋势中）。
- `ohlc`：**需要最高最低价的指标，仅黄金可算**。
  - `available`：true=黄金；false=基金（下面全为 null，别解读）。
  - `atr14` 真实波幅、`kdj{k,d,j}` 随机指标、`cci14`、`wr14` 威廉、`adx14`（>25 趋势强，<20 震荡）。

## percentile
`price_pct`：最新值在近 N 年的百分位（0~1，point-in-time，无前视偏差）。近 1=历史高位，近 0=历史低位。

## profile（基金基本面——专业分析的核心，仅场外基金）
`applicable=false` 表示黄金（无经理/持仓/评级，看宏观与价格）。
- `basic`：`name/full_name/type/inception/scale/company/manager`。规模过大（数百亿主动基金）常拖累业绩；费率越低越好。
- `holdings`：`top`（前十大重仓 code/name/pct）+ `top10_concentration`（集中度）+ `as_of`（季度）。
  **看重仓能判断这基金到底押注什么行业、风格有没有漂移、集中度风险多大**——这是散户级技术分析给不了的。
- `rating`：`morningstar`（晨星星级）、`shanghai`/`jian` 等评级、`fee` 费率、`type` 分类。

> 舆情不在证据卡里——**你自己用 WebSearch 搜最新新闻/政策/研报并鉴别**，比任何固定数据源都新、都准。

## track_record
该标的历史信号复盘：`past_signals`（累计）、`hit_rate`（命中率）、`ic`（信息系数=预测力）、`vs_benchmark`（相对买入持有超额）。用它校准把握；`None`=还没到期样本。

## data_quality（诚实性字段，最重要）
- `price`：`ok/stale/partial(不足一年)/missing`。
- `ohlc`：`available`（黄金）/`unavailable`（基金，OHLC 指标为 null）。
- `profile`：`ok/partial/n/a`（n/a=黄金）。
- `notes`：具体说明。
- **只要有 partial/missing 或 ohlc=unavailable，必须在结论里明说并相应下调置信度。**
