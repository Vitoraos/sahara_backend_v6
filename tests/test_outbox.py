import asyncio
import json
from types import SimpleNamespace

import pytest

import app.persistence_outbox as outbox
from app.routes import deps


class StubPipeline:
    def __init__(self, store: dict) -> None:
        self._store = store

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def rpush(self, queue: str, payload: str) -> None:
        self._store.setdefault(queue, []).append(payload)

    async def execute(self):
        return [1]


class StubRedis:
    def __init__(self) -> None:
        self.store: dict = {}
        self.kv: dict = {}

    def pipeline(self):
        return StubPipeline(self.store)

    async def brpop(self, keys: list, timeout: int = 0):
        for key in keys:
            if self.store.get(key):
                return (key, self.store[key].pop(0))
        await asyncio.sleep(0)
        return None

    async def get(self, key: str):
        return self.kv.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.kv[key] = value


class StubRepo:
    def __init__(self) -> None:
        self.turns: list = []
        self.triage: list = []
        self.flushed = asyncio.Event()

    async def save_turn(self, **kwargs) -> None:
        self.turns.append(kwargs)
        self._maybe_set()

    async def upsert_triage_result(self, **kwargs) -> None:
        self.triage.append(kwargs)
        self._maybe_set()

    def _maybe_set(self) -> None:
        if self.turns and self.triage:
            self.flushed.set()


def _turn() -> dict:
    return {
        "conversation_id": "conv-1",
        "turn_number": 1,
        "transcript": "I cannot breathe",
        "translated_text": "I cannot breathe",
        "extracted_fields": {},
        "detected_language": {},
        "asr_provider": "intron",
    }


def _triage() -> dict:
    return {
        "conversation_id": "conv-1",
        "urgency_tier": "RED",
        "danger_signs": ["cannot breathe"],
        "summary": "Emergency",
    }


@pytest.mark.asyncio
async def test_persist_buffers_both_payloads(monkeypatch) -> None:
    redis = StubRedis()
    monkeypatch.setattr(outbox, "_client", redis)
    settings = SimpleNamespace(redis_url="rediss://x")
    await outbox.persist_turn_result(SimpleNamespace(), settings, turn=_turn(), triage=_triage())
    turn = json.loads(redis.store[outbox.TURN_QUEUE][0])
    triage = json.loads(redis.store[outbox.TRIAGE_QUEUE][0])
    assert (turn["kind"], turn["turn_number"]) == ("turn", 1)
    assert (triage["kind"], triage["urgency_tier"]) == ("triage", "RED")


@pytest.mark.asyncio
async def test_flush_drains_queues_to_repository(monkeypatch) -> None:
    redis = StubRedis()
    redis.store[outbox.TURN_QUEUE] = [json.dumps({"kind": "turn", **_turn()})]
    redis.store[outbox.TRIAGE_QUEUE] = [json.dumps({"kind": "triage", **_triage()})]
    monkeypatch.setattr(outbox, "_client", redis)
    repo = StubRepo()
    task = asyncio.ensure_future(outbox._flush_loop(repo, SimpleNamespace(redis_url="rediss://x")))
    await asyncio.wait_for(repo.flushed.wait(), timeout=5)
    task.cancel()
    assert repo.turns[0]["transcript"] == "I cannot breathe"
    assert repo.triage[0]["urgency_tier"] == "RED"


@pytest.mark.asyncio
async def test_no_redis_falls_back_to_inline_writes() -> None:
    repo = StubRepo()
    settings = SimpleNamespace(redis_url="")
    await outbox.persist_turn_result(repo, settings, turn=_turn(), triage=_triage())
    assert len(repo.turns) == 1 and len(repo.triage) == 1


@pytest.mark.asyncio
async def test_auth_cache_hit_skips_lookup(monkeypatch) -> None:
    import hashlib

    redis = StubRedis()
    key = "sahara:auth:patient:" + hashlib.sha256(b"tok").hexdigest()
    redis.kv[key] = json.dumps({"id": "patient-1"})
    monkeypatch.setattr(deps, "RedisClient", lambda settings: SimpleNamespace(client=redis))

    async def lookup(token: str):
        raise AssertionError("lookup should not run on cache hit")

    row = await deps._cached_profile(
        SimpleNamespace(), SimpleNamespace(redis_url="rediss://x"),
        token="tok", kind="patient", lookup=lookup,
    )
    assert row == {"id": "patient-1"}


@pytest.mark.asyncio
async def test_auth_cache_miss_calls_lookup_and_stores(monkeypatch) -> None:
    redis = StubRedis()
    monkeypatch.setattr(deps, "RedisClient", lambda settings: SimpleNamespace(client=redis))

    async def lookup(token: str):
        assert token == "tok"
        return {"id": "patient-9"}

    row = await deps._cached_profile(
        SimpleNamespace(), SimpleNamespace(redis_url="rediss://x"),
        token="tok", kind="patient", lookup=lookup,
    )
    assert row == {"id": "patient-9"}
    assert json.loads(next(iter(redis.kv.values()))) == {"id": "patient-9"}
