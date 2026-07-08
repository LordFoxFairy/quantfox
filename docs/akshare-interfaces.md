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

## 财经新闻
- 函数：`ak.stock_news_em(symbol="<关键词或代码>")`（symbol="黄金" 对黄金有效）
- 返回列：`['关键词', '新闻标题', '新闻内容', '发布时间', '文章来源', '新闻链接']`
- 映射：`新闻标题 -> title`，`文章来源 -> source`，`发布时间 -> date`，`新闻链接 -> url`，`新闻内容 -> summary`

## fixtures
- `tests/fixtures/fund_nav_sample.json`（基金 501018 近 120 条）
- `tests/fixtures/gold_sample.json`（Au99.99 近 120 条）
- `tests/fixtures/news_sample.json`（黄金新闻近 30 条）
