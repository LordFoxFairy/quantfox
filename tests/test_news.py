from pathlib import Path

import pandas as pd

from money.data.news import load_news
from money.data.resolve import Asset

FX = Path(__file__).parent / "fixtures"


def _fetcher(asset, limit):
    return pd.read_json(FX / "news_sample.json")


def test_load_news_normalized():
    a = Asset(symbol="Au99.99", type="gold")
    items = load_news(a, fetcher=_fetcher, limit=5)
    assert isinstance(items, list) and len(items) <= 5
    for it in items:
        assert set(it.keys()) == {"title", "source", "date", "url", "summary"}


def test_fetcher_failure_returns_empty():
    a = Asset(symbol="Au99.99", type="gold")

    def _boom(asset, limit):
        raise RuntimeError("network down")

    assert load_news(a, fetcher=_boom) == []
