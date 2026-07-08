"""探测 akshare 的"专业基金数据"接口：经理/持仓/规模费率/同类排名/指数估值分位。"""
import traceback
import akshare as ak


def probe(name, fn):
    try:
        df = fn()
        print(f"\n=== {name} OK ===")
        try:
            print("columns:", list(df.columns))
            print(df.head(4).to_string())
        except Exception:
            print(repr(df)[:800])
    except Exception as e:  # noqa
        print(f"\n=== {name} FAILED: {type(e).__name__}: {e} ===")


# 用一只主动权益基金试：000001 华夏成长混合
probe("基本信息(雪球)", lambda: ak.fund_individual_basic_info_xq(symbol="000001"))
probe("持仓(天天)", lambda: ak.fund_portfolio_hold_em(symbol="000001", date="2024"))
probe("规模", lambda: ak.fund_scale_open_sina(symbol="股票型基金"))
probe("同类排名(天天)", lambda: ak.fund_open_fund_rank_em(symbol="股票型"))
# 指数估值分位（指数基金择时核心）
probe("指数估值分位(funddb)", lambda: ak.index_value_hist_funddb(symbol="沪深300", indicator="市盈率"))
probe("基金评级", lambda: ak.fund_rating_all())
