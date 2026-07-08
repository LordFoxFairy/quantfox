"""开发期手动运行，探测并钉死 akshare 接口，产出离线 fixtures。"""
import json
import traceback
from pathlib import Path

import akshare as ak

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
OUT.mkdir(parents=True, exist_ok=True)


def dump(name, df, rows=120):
    print(f"\n=== {name} OK ===")
    print("columns:", list(df.columns))
    print(df.head(3).to_string())
    (OUT / f"{name}.json").write_text(
        df.tail(rows).to_json(orient="records", force_ascii=False), encoding="utf-8"
    )


def probe(name, fn, rows=120):
    try:
        dump(name, fn(), rows)
    except Exception as e:  # noqa
        print(f"\n=== {name} FAILED: {e} ===")
        traceback.print_exc()


# 场外基金历史净值
probe("fund_nav_sample", lambda: ak.fund_open_fund_info_em(symbol="501018", indicator="单位净值走势"))

# 黄金 Au99.99（上海金交所现货）
probe("gold_sample", lambda: ak.spot_hist_sge(symbol="Au99.99"))

# 财经新闻——多个候选，看哪个可用
probe("news_sample", lambda: ak.stock_news_em(symbol="黄金"), rows=30)
