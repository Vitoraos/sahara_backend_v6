from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.scheduling import route_appointment, split_window, upcoming_slots

MONDAY_8AM = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)  # a Monday


def test_split_window_uses_25_minute_blocks() -> None:
    assert split_window("09:00", "10:00") == [("09:00", "09:25"), ("09:25", "09:50")]
    assert split_window("09:00", "09:30") == [("09:00", "09:25")]
    assert split_window("09:00", "09:20") == []


def test_upcoming_slots_match_weekday_and_skip_booked() -> None:
    windows = [{"doctor_id": "doc-1", "weekday": 0, "start_time": "09:00", "end_time": "10:00"}]
    assert upcoming_slots(windows, set(), now=MONDAY_8AM) == [
        ("doc-1", "2026-09-14T09:00:00+00:00"),
        ("doc-1", "2026-09-14T09:25:00+00:00"),
    ]
    booked = {("doc-1", "2026-09-14T09:00:00+00:00")}
    assert upcoming_slots(windows, booked, now=MONDAY_8AM) == [
        ("doc-1", "2026-09-14T09:25:00+00:00")
    ]


def test_upcoming_slots_skip_past_and_empty_windows() -> None:
    late = datetime(2026, 9, 14, 9, 30, tzinfo=timezone.utc)
    windows = [{"doctor_id": "doc-1", "weekday": 0, "start_time": "09:00", "end_time": "09:30"}]
    assert upcoming_slots(windows, set(), now=late, days=1) == []
    assert upcoming_slots([], set(), now=MONDAY_8AM) == []


@pytest.mark.asyncio
async def test_route_books_earliest_free_slot() -> None:
    created: list[dict] = []

    class Repo:
        async def all_availability(self) -> list[dict]:
            return [{"doctor_id": "doc-2", "weekday": 0, "start_time": "09:00", "end_time": "09:30"}]

        async def booked_slots(self, *, since_iso: str, until_iso: str) -> list[dict]:
            return []

        async def create_appointment(self, **kwargs) -> dict:
            created.append(kwargs)
            return {"id": "appt-1", "scheduled_at": str(kwargs["scheduled_at"])}

    result = await route_appointment(
        Repo(), patient_id=uuid4(), conversation_id=uuid4(), tier="AMBER", now=MONDAY_8AM
    )
    assert result["scheduled_at"] == "2026-09-14T09:00:00+00:00"
    assert len(created) == 1


@pytest.mark.asyncio
async def test_route_retries_on_conflict_then_succeeds() -> None:
    calls: list[str] = []

    class Repo:
        async def all_availability(self) -> list[dict]:
            return [{"doctor_id": "doc-1", "weekday": 0, "start_time": "09:00", "end_time": "10:00"}]

        async def booked_slots(self, *, since_iso: str, until_iso: str) -> list[dict]:
            return []

        async def create_appointment(self, **kwargs) -> dict:
            calls.append(str(kwargs["scheduled_at"]))
            if len(calls) == 1:
                raise RuntimeError("duplicate key (appointments_doctor_slot_key)")
            return {"id": "appt-2"}

    result = await route_appointment(
        Repo(), patient_id=uuid4(), conversation_id=None, tier="RED", now=MONDAY_8AM
    )
    assert result["id"] == "appt-2"
    assert calls == ["2026-09-14T09:00:00+00:00", "2026-09-14T09:25:00+00:00"]


@pytest.mark.asyncio
async def test_route_raises_when_no_availability() -> None:
    class Repo:
        async def all_availability(self) -> list[dict]:
            return []

        async def booked_slots(self, *, since_iso: str, until_iso: str) -> list[dict]:
            return []

    with pytest.raises(RuntimeError, match="No doctor availability"):
        await route_appointment(Repo(), patient_id=uuid4(), conversation_id=None, tier="AMBER", now=MONDAY_8AM)
