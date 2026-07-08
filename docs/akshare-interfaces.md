# akshare 接口清单（实测钉死，2026-07-08）

数据层严格按此写。列名如未来 akshare 变更，改 `money/data/prices.py` 与 `money/data/news.py` 的候选列表。

## 场外基金历史净值
- 函数：`ak.fund_open_fund_info_em(symbol="<6位代码>", indicator="单位净值走势")`
- 返回列：`['净值日期', '单位净值', '日增长率']`
- 映射：`净值日期 -> date`，`单位净值 -> value`

## 黄金 Au99.99（上海金交所现货）
- 函数：`ak.spot_hist_sge(symbol="Au99.99")`
- 返回列：`['date', 'open', 'close', 'low', 'high']`
- 映射：`date -> date`，`close -> value`

## 专业基金基本面（money/data/fund_profile.py）
- 基本信息：`ak.fund_individual_basic_info_xq(symbol="<代码>")` → item/value 两列（含名称/成立/公司/经理/类型/规模）。
- 持仓：`ak.fund_portfolio_hold_em(symbol="<代码>", date="<年份>")` → `序号/股票代码/股票名称/占净值比例/持股数/持仓市值/季度`。
- 评级：`ak.fund_rating_all()` → `代码/简称/基金经理/基金公司/5星评级家数/上海证券/济安金信/晨星评级/手续费/类型`。
- 同类业绩排名：`ak.fund_open_fund_rank_em(symbol="<类型>")` → 近1周/月/季/半年/1年/3年 收益。

## 舆情：不由引擎负责
新闻/舆情/宏观由 CC agent 自己用 WebSearch/WebFetch 获取并鉴别（比固定数据源更新更准），
不再在引擎里做（原 `stock_news_em` 方案已移除）。

## fixtures
- `tests/fixtures/fund_nav_sample.json`（基金 501018 近 120 条）
- `tests/fixtures/gold_sample.json`（Au99.99 近 120 条）
- `tests/fixtures/news_sample.json`（黄金新闻近 30 条）
