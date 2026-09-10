from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.config import Settings

logger = logging.getLogger(__name__)

TURN_QUEUE = "sahara:turns"
TRIAGE_QUEUE = "sahara:triage"

_client: aioredis.Redis | None = None
_flusher: asyncio.Task | None = None


def _client_for(settings: Settings) -> aioredis.Redis | None:
    # ponytail: crash-before-flush loses only items popped-but-unflushed
    # (seconds); unflushed list items survive restarts in Redis. Supabase
    # stays source of truth — Redis is a buffer, not storage.
    global _client
    if _client is None and settings.redis_url:
        _client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def persist_turn_result(
    repository: Any,
    settings: Settings,
    *,
    turn: dict[str, Any],
    triage: dict[str, Any] | None,
) -> None:
    """Buffer one turn (+ optional triage) in a single Redis round-trip.

    Falls back to inline Supabase writes when Redis is unset or down, so
    the speech path never depends on Redis availability.
    """
    client = _client_for(settings)
    if client is None:
        await _write_inline(repository, turn=turn, triage=triage)
        return
    try:
        async with client.pipeline() as pipe:
            pipe.rpush(TURN_QUEUE, json.dumps({"kind": "turn", **turn}))
            if triage is not None:
                pipe.rpush(TRIAGE_QUEUE, json.dumps({"kind": "triage", **triage}))
            await pipe.execute()
    except Exception as exc:
        logger.warning("outbox push failed; writing inline", extra={"error_type": type(exc).__name__})
        await _write_inline(repository, turn=turn, triage=triage)


async def _write_inline(repository: Any, *, turn: dict[str, Any], triage: dict[str, Any] | None) -> None:
    await repository.save_turn(
        conversation_id=turn["conversation_id"],
        turn_number=turn["turn_number"],
        transcript=turn["transcript"],
        translated_text=turn["translated_text"],
        extracted_fields=turn["extracted_fields"],
        detected_language=turn["detected_language"],
        asr_provider=turn["asr_provider"],
    )
    if triage is not None:
        await repository.upsert_triage_result(
            conversation_id=triage["conversation_id"],
            urgency_tier=triage["urgency_tier"],
            danger_signs=triage["danger_signs"],
            summary=triage["summary"],
        )


def ensure_flusher(repository: Any, settings: Settings) -> None:
    """Start the per-process background flush task (idempotent)."""
    global _flusher
    if _flusher is not None and not _flusher.done():
        return
    _flusher = asyncio.ensure_future(_flush_loop(repository, settings))


async def _flush_loop(repository: Any, settings: Settings) -> None:
    client = _client_for(settings)
    if client is None:
        return
    while True:
        try:
            item = await client.brpop([TURN_QUEUE, TRIAGE_QUEUE], timeout=1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("outbox pop failed", extra={"error_type": type(exc).__name__})
            await asyncio.sleep(1)
            continue
        if not item:
            continue
        _, payload = item
        for attempt in range(4):
            try:
                data = json.loads(payload)
                if data.get("kind") == "triage":
                    await repository.upsert_triage_result(
                        conversation_id=data["conversation_id"],
                        urgency_tier=data["urgency_tier"],
                        danger_signs=data["danger_signs"],
                        summary=data["summary"],
                    )
                else:
                    await repository.save_turn(
                        conversation_id=data["conversation_id"],
                        turn_number=data["turn_number"],
                        transcript=data["transcript"],
                        translated_text=data["translated_text"],
                        extracted_fields=data["extracted_fields"],
                        detected_language=data["detected_language"],
                        asr_provider=data["asr_provider"],
                    )
                break
            except Exception as exc:
                # ponytail: drop after 4 attempts; dead-letter queue when loss matters.
                logger.warning(
                    "outbox flush failed",
                    extra={"error_type": type(exc).__name__, "attempt": attempt},
                )
                await asyncio.sleep(min(0.25 * (2**attempt), 1.0))
