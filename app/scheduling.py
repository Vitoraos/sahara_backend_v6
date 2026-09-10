from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

SLOT_MINUTES = 25
HORIZON_DAYS = 7
MAX_BOOK_ATTEMPTS = 10


def split_window(start: str, end: str, *, block_minutes: int = SLOT_MINUTES) -> list[tuple[str, str]]:
    """Split one HH:MM window into block-sized slots; partial tail dropped."""
    start_h, start_m = (int(part) for part in start.split(":"))
    end_h, end_m = (int(part) for part in end.split(":"))
    cursor = start_h * 60 + start_m
    stop = end_h * 60 + end_m
    slots: list[tuple[str, str]] = []
    while cursor + block_minutes <= stop:
        slots.append((_fmt(cursor), _fmt(cursor + block_minutes)))
        cursor += block_minutes
    return slots


def upcoming_slots(
    windows: list[dict[str, Any]],
    booked: set[tuple[str, str]],
    *,
    days: int = HORIZON_DAYS,
    now: datetime | None = None,
) -> list[tuple[str, str]]:
    """Chronological (doctor_id, slot_iso) pairs for the next `days` UTC days.

    `windows` rows carry doctor_id/weekday/start_time/end_time; `booked`
    holds taken (doctor_id, slot_iso) pairs. Slots starting at or before
    `now` are excluded.
    """
    current = now or datetime.now(timezone.utc)
    by_doctor: dict[str, list[dict[str, Any]]] = {}
    for window in windows:
        by_doctor.setdefault(str(window["doctor_id"]), []).append(window)
    slots: list[tuple[str, str]] = []
    for offset in range(days):
        day = current + timedelta(days=offset)
        weekday = day.weekday()
        day_str = day.date().isoformat()
        for doctor_id in sorted(by_doctor):
            for window in by_doctor[doctor_id]:
                if int(window["weekday"]) != weekday:
                    continue
                for start, _ in split_window(str(window["start_time"])[:5], str(window["end_time"])[:5]):
                    slot = datetime.fromisoformat(f"{day_str}T{start}:00+00:00")
                    if slot <= current:
                        continue
                    key = (doctor_id, slot.isoformat())
                    if key not in booked:
                        slots.append(key)
    return slots


async def route_appointment(
    repository: Any,
    *,
    patient_id: UUID,
    conversation_id: UUID | None,
    tier: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Book the earliest free 25-min slot across all doctors.

    # ponytail: earliest-wins, no urgency jump or load balancing; add when
    # RED waits too long. Retries next slot on unique-violation races.
    """
    now = now or datetime.now(timezone.utc)
    horizon = now + timedelta(days=HORIZON_DAYS)
    windows = await repository.all_availability()
    booked_rows = await repository.booked_slots(
        since_iso=now.isoformat(), until_iso=horizon.isoformat()
    )
    booked = {(str(row["doctor_id"]), str(row["scheduled_at"])) for row in booked_rows}
    last_error: Exception | None = None
    for doctor_id, slot_iso in upcoming_slots(windows, booked, now=now)[:MAX_BOOK_ATTEMPTS]:
        try:
            return await repository.create_appointment(
                patient_id=patient_id,
                conversation_id=conversation_id,
                tier=tier,
                doctor_id=doctor_id,
                scheduled_at=slot_iso,
            )
        except Exception as exc:  # race on the unique slot index; try the next one
            last_error = exc
    raise RuntimeError("No doctor availability in the next 7 days") from last_error


def _fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"
