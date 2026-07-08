import pandas as pd

from .resolve import Asset

# 列名映射（实测见 docs/akshare-interfaces.md）
_COL = {
    "title": ["新闻标题", "title", "标题"],
    "source": ["文章来源", "source", "来源"],
    "date": ["发布时间", "date", "时间"],
    "url": ["新闻链接", "url", "链接"],
    "summary": ["新闻内容", "content", "内容", "摘要"],
}


def _pick(row, cands):
    for c in cands:
        if c in row and pd.notna(row[c]):
            return str(row[c])
    return ""


def _query_for(asset: Asset) -> str:
    return "黄金" if asset.type == "gold" else asset.symbol


def _default_fetcher(asset: Asset, limit: int) -> pd.DataFrame:
    import akshare as ak

    return ak.stock_news_em(symbol=_query_for(asset))


def load_news(asset: Asset, fetcher=None, limit: int = 10) -> list[dict]:
    fetcher = fetcher or _default_fetcher
    try:
        df = fetcher(asset, limit)
    except Exception:
        return []
    items = []
    for _, row in df.head(limit).iterrows():
        items.append({k: _pick(row, cands) for k, cands in _COL.items()})
    return items
