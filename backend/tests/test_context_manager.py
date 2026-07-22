from types import SimpleNamespace

import pytest

from app.core.context_manager import ContextManager


class FakeRedis:
    """Minimal stand-in for the subset of redis-py used by ContextManager —
    keeps this test fast and dependency-free (no real Redis needed)."""

    def __init__(self):
        self.store: dict[str, list[str]] = {}

    def rpush(self, key, value):
        self.store.setdefault(key, []).append(value)

    def expire(self, key, ttl):
        pass

    def llen(self, key):
        return len(self.store.get(key, []))

    def lrange(self, key, start, end):
        items = self.store.get(key, [])
        return items[start:] if end == -1 else items[start : end + 1]

    def delete(self, key):
        self.store.pop(key, None)


@pytest.fixture
def cm(monkeypatch):
    monkeypatch.setenv("SHORT_TERM_BUFFER_MAX_RUNS", "3")
    from app.config import get_settings

    get_settings.cache_clear()
    manager = ContextManager(redis_client=FakeRedis())
    yield manager
    get_settings.cache_clear()


def test_build_context_combines_memories_and_recent_activity(monkeypatch, cm):
    fake_memories = [SimpleNamespace(content="memory one"), SimpleNamespace(content="memory two")]
    monkeypatch.setattr("app.core.context_manager.search_memories", lambda db, q, top_k: fake_memories)

    context = cm.build_context(db=object(), task_id="t1", query="find pain points", skills_text="be terse")
    assert context.relevant_memories == ["memory one", "memory two"]
    assert context.skills_text == "be terse"
    assert "be terse" in context.as_prompt_block()
    assert "memory one" in context.as_prompt_block()


def test_record_activity_below_threshold_does_not_compress(monkeypatch, cm):
    write_calls = []
    monkeypatch.setattr("app.core.context_manager.write_memory", lambda *a, **k: write_calls.append(k))

    for i in range(2):  # threshold is 3 (see fixture)
        cm.record_activity(db=object(), task_id="t1", agent_name="scout", summary={"step": i})

    assert write_calls == []
    assert cm.redis.llen("shortterm:t1") == 2


def test_record_activity_over_threshold_compresses_and_clears_buffer(monkeypatch, cm):
    write_calls = []
    monkeypatch.setattr("app.core.context_manager.write_memory", lambda *a, **k: write_calls.append(k))

    class FakeRouter:
        def complete(self, **kwargs):
            return SimpleNamespace(content="a dense one-paragraph summary")

    cm._router = FakeRouter()

    class FakeDB:
        def commit(self):
            pass

    for i in range(4):  # exceeds threshold of 3
        cm.record_activity(db=FakeDB(), task_id="t1", agent_name="scout", summary={"step": i})

    assert len(write_calls) == 1
    assert write_calls[0]["memory_type"] == "summary"
    assert write_calls[0]["content"] == "a dense one-paragraph summary"
    assert cm.redis.llen("shortterm:t1") == 0  # buffer cleared after compression


def test_compression_falls_back_to_truncated_raw_when_model_unavailable(monkeypatch, cm):
    write_calls = []
    monkeypatch.setattr("app.core.context_manager.write_memory", lambda *a, **k: write_calls.append(k))

    class FailingRouter:
        def complete(self, **kwargs):
            raise RuntimeError("no free model available")

    cm._router = FailingRouter()

    class FakeDB:
        def commit(self):
            pass

    for i in range(4):
        cm.record_activity(db=FakeDB(), task_id="t1", agent_name="scout", summary={"step": i})

    assert len(write_calls) == 1
    assert write_calls[0]["memory_type"] == "summary"
    assert write_calls[0]["content"]  # non-empty fallback text
