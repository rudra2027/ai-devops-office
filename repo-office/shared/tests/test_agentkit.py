import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentkit import cache as cache_mod  # noqa: E402
from agentkit.store import SqliteStore  # noqa: E402
from agentkit.uiblocks import UiSplitter, parse_ui  # noqa: E402


def split_stream(chunks):
    sp, shown = UiSplitter(), ""
    for c in chunks:
        shown += sp.feed(c)
    tail, raw = sp.finish()
    return shown + tail, raw


def test_splitter_streams_text_and_hides_ui_even_when_tag_is_split():
    text, raw = split_stream(["Hello the", "re <", "u", "i>{\"mood\":\"upbeat\"}</", "ui>"])
    assert text == "Hello there "
    assert raw == '{"mood":"upbeat"}'


def test_splitter_does_not_swallow_a_lone_angle_bracket():
    text, raw = split_stream(["1 < 2 and 3 > 2"])
    assert text == "1 < 2 and 3 > 2" and raw is None


def test_parse_ui_keeps_valid_blocks_and_drops_invalid():
    p = parse_ui('```json\n{"mood":"celebrate","blocks":[{"type":"card","title":"Hi"},{"type":"nope"},'
                 '{"type":"chart","labels":["a"],"series":[{"name":"s","values":[1]}]}],"quick_replies":["a","b","c","d","e"]}\n```')
    assert p and p.mood == "celebrate"
    assert [b.type for b in p.blocks] == ["card", "chart"]
    assert len(p.quick_replies) == 4


def test_parse_ui_rejects_garbage():
    assert parse_ui("not json") is None
    assert parse_ui("[1,2]") is None


def test_sqlite_store_crud_and_user_isolation(tmp_path):
    async def run():
        s = SqliteStore(str(tmp_path / "t.db"))
        a = await s.insert("messages", {"user_id": "u1", "content": "hi"})
        await s.insert("messages", {"user_id": "u2", "content": "secret"})
        assert [r["content"] for r in await s.select("messages", {"user_id": "u1"})] == ["hi"]
        await s.update("messages", {"id": a["id"]}, {"content": "edited"})
        assert (await s.select("messages", {"id": a["id"]}))[0]["content"] == "edited"
        assert await s.delete("messages", {"user_id": "u2"}) == 1
        assert len(await s.select("messages")) == 1

    asyncio.run(run())


def test_memory_cache_rate_limit(monkeypatch):
    monkeypatch.setattr(cache_mod, "_cache", cache_mod.MemoryCache())
    results = [cache_mod.rate_limited("k", 3, 60) for _ in range(5)]
    assert results == [False, False, False, True, True]


def test_unsafe_sql_identifiers_rejected(tmp_path):
    s = SqliteStore(str(tmp_path / "t.db"))
    with pytest.raises(ValueError):
        s._select('x"; drop table y; --', {}, None, True, 1)
    with pytest.raises(ValueError):
        s._select("ok", {"a') or 1=1 --": 1}, None, True, 1)


def test_apm_reports_golden_signals_and_resets_each_window():
    from agentkit.apm import Apm

    a = Apm("t")
    for ms, status in [(10, 200), (20, 200), (300, 500), (40, 404)]:
        a.record("GET /x", status, ms)
    s = a.snapshot(10)
    assert s["requests"] == 4 and s["errors_5xx"] == 1 and s["errors_4xx"] == 1 and s["error_rate"] == 0.25 and s["rps"] == 0.4
    assert s["latency_p50_ms"] <= s["latency_p95_ms"] <= s["latency_p99_ms"] <= 300
    assert s["memory_mb"] > 0 and s["threads"] >= 1 and s["top_routes"][0] == {"route": "GET /x", "count": 4, "errors": 1, "avg_ms": 92.5}
    assert a.snapshot(10)["requests"] == 0  # the window starts over
