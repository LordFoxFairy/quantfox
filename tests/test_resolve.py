import pytest

from money.data.resolve import Asset, resolve


def test_gold_aliases():
    for q in ["gold", "黄金", "AU99.99", "au99.99"]:
        a = resolve(q)
        assert a.type == "gold"
        assert a.symbol == "Au99.99"


def test_fund_code():
    a = resolve("501018")
    assert a.type == "otc_fund"
    assert a.symbol == "501018"


def test_unknown_raises():
    with pytest.raises(ValueError):
        resolve("banana")
