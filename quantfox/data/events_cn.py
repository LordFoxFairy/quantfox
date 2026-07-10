"""下周宏观事件（尽力而为）：接口异常/结构变化一律返回 None——省略整节，绝不编数据。"""
import datetime as _dt


def next_week_events():
    try:
        import akshare as ak
        import pandas as pd

        df = ak.news_economic_baidu()
        col_date = "日期" if "日期" in df.columns else df.columns[0]
        col_name = "事件" if "事件" in df.columns else df.columns[1]
        today = _dt.date.today()
        end = today + _dt.timedelta(days=7)
        out = []
        for _, r in df.iterrows():
            d = pd.to_datetime(r[col_date]).date()
            if today <= d <= end:
                out.append({"date": d.isoformat(), "event": str(r[col_name])})
        return out or None
    except Exception:  # noqa - 任何异常都弃权
        return None
