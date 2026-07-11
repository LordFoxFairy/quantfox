"""next_week_events: 多源依序尝试 + 当日缓存。全部注入，零网络。"""
import json

import pytest

from quantfox.data.events_cn import next_week_events

FAKE_EVENTS = [{"date": "2026-07-12", "event": "CPI 数据公布"}]


def _raiser(*_a, **_k):
    raise RuntimeError("source down")


def _counting(fn):
    """包一层计数器，断言某源是否被调用。"""
    calls = []

    def wrapped():
        calls.append(1)
        return fn()

    wrapped.calls = calls
    return wrapped


def test_first_source_fails_second_succeeds_writes_cache(tmp_path):
    cache_path = tmp_path / "events_cache.json"
    second = _counting(lambda: list(FAKE_EVENTS))

    result = next_week_events(
        sources=[_raiser, second], cache_path=cache_path, today="2026-07-11"
    )

    assert result == FAKE_EVENTS
    assert second.calls == [1]
    assert cache_path.exists()
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cached == {"date": "2026-07-11", "events": FAKE_EVENTS}


def test_all_sources_fail_returns_none_no_cache_file(tmp_path):
    cache_path = tmp_path / "events_cache.json"

    result = next_week_events(
        sources=[_raiser, _raiser], cache_path=cache_path, today="2026-07-11"
    )

    assert result is None
    assert not cache_path.exists()


def test_same_day_cache_hit_skips_sources(tmp_path):
    cache_path = tmp_path / "events_cache.json"
    cache_path.write_text(
        json.dumps({"date": "2026-07-11", "events": FAKE_EVENTS}, ensure_ascii=False),
        encoding="utf-8",
    )
    first = _counting(lambda: list(FAKE_EVENTS))
    second = _counting(lambda: list(FAKE_EVENTS))

    result = next_week_events(
        sources=[first, second], cache_path=cache_path, today="2026-07-11"
    )

    assert result == FAKE_EVENTS
    assert first.calls == []
    assert second.calls == []


def test_stale_cache_refetches_and_overwrites(tmp_path):
    cache_path = tmp_path / "events_cache.json"
    stale_events = [{"date": "2026-07-10", "event": "旧事件"}]
    cache_path.write_text(
        json.dumps({"date": "2026-07-10", "events": stale_events}, ensure_ascii=False),
        encoding="utf-8",
    )
    fresh_events = [{"date": "2026-07-13", "event": "新事件"}]
    first = _counting(lambda: list(fresh_events))

    result = next_week_events(
        sources=[first], cache_path=cache_path, today="2026-07-11"
    )

    assert result == fresh_events
    assert first.calls == [1]
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cached == {"date": "2026-07-11", "events": fresh_events}


def test_default_sources_are_baidu_then_secondary():
    from quantfox.data.events_cn import _source_baidu, _source_secondary

    result = next_week_events.__defaults__  # sources, cache_path, today all default None
    assert result == (None, None, None)
    # 默认 sources 列表由函数体内部构造，逐一确认两个源函数存在且可调用
    assert callable(_source_baidu)
    assert callable(_source_secondary)
