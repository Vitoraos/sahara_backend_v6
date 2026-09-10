from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.integrations.supabase_client import SupabaseClient


class ConversationRepository:
    """Async persistence for the safety-critical conversation path."""

    def __init__(self, supabase: SupabaseClient, *, timeout_seconds: float = 5.0) -> None:
        self._db = supabase.client
        self._timeout = timeout_seconds

    async def patient_by_auth_user(self, auth_user_id: UUID) -> dict[str, Any] | None:
        return await self._select_one("patients", "*", {"auth_user_id": str(auth_user_id)})

    async def patient_by_phone(self, phone_number: str) -> dict[str, Any] | None:
        return await self._select_one("patients", "*", {"phone_number": phone_number})

    async def patient_by_id(self, patient_id: UUID) -> dict[str, Any] | None:
        return await self._select_one("patients", "*", {"id": str(patient_id)})

    async def patient_for_access_token(self, access_token: str) -> dict[str, Any] | None:
        if not access_token:
            return None
        response = await asyncio.wait_for(
            self._db.auth.get_user(access_token),
            timeout=self._timeout,
        )
        user = getattr(response, "user", None)
        user_id = getattr(user, "id", None)
        if not user_id:
            return None
        try:
            return await self.patient_by_auth_user(UUID(str(user_id)))
        except ValueError:
            return None

    async def conversation_patient_id(self, conversation_id: UUID) -> UUID | None:
        row = await self._select_one("conversations", "patient_id", {"id": str(conversation_id)})
        if not row or not row.get("patient_id"):
            return None
        return UUID(str(row["patient_id"]))

    async def create_phone_patient(self, phone_number: str) -> UUID:
        existing = await self.patient_by_phone(phone_number)
        if existing:
            return UUID(str(existing["id"]))
        row = await self._insert_one(
            "patients",
            {"phone_number": phone_number, "auth_user_id": None},
        )
        return UUID(str(row["id"]))

    async def create_conversation(self, *, patient_id: UUID, channel: str) -> UUID:
        row = await self._insert_one(
            "conversations",
            {"patient_id": str(patient_id), "channel": channel, "status": "active"},
        )
        return UUID(str(row["id"]))

    async def finish_conversation(self, conversation_id: UUID, *, status: str = "completed") -> None:
        await asyncio.wait_for(
            self._db.table("conversations")
            .update({"ended_at": datetime.now(timezone.utc).isoformat(), "status": status})
            .eq("id", str(conversation_id))
            .execute(),
            timeout=self._timeout,
        )

    async def load_context(self, conversation_id: UUID) -> tuple[int, dict[str, Any]]:
        response = await asyncio.wait_for(
            self._db.table("turns")
            .select("turn_number,extracted_fields")
            .eq("conversation_id", str(conversation_id))
            .order("turn_number")
            .execute(),
            timeout=self._timeout,
        )
        data = response.data
        fields: dict[str, Any] = {}
        max_turn = 0
        if isinstance(data, list):
            for row in data:
                if not isinstance(row, dict):
                    continue
                max_turn = max(max_turn, int(row.get("turn_number") or 0))
                extracted = row.get("extracted_fields")
                if isinstance(extracted, dict):
                    fields.update(extracted)
        return max_turn, fields

    async def record_phone_consent(self, *, conversation_id: UUID, consented: bool) -> None:
        await asyncio.wait_for(
            self._db.table("conversation_recording_consents")
            .upsert(
                {
                    "conversation_id": str(conversation_id),
                    "consented": consented,
                    "consent_recorded_at": datetime.now(timezone.utc).isoformat(),
                },
                on_conflict="conversation_id",
            )
            .execute(),
            timeout=self._timeout,
        )

    async def save_turn(
        self,
        *,
        conversation_id: UUID,
        turn_number: int,
        transcript: str,
        translated_text: str,
        extracted_fields: dict[str, Any],
        detected_language: dict[str, Any],
        asr_provider: str,
    ) -> None:
        await self._insert_one(
            "turns",
            {
                "conversation_id": str(conversation_id),
                "turn_number": turn_number,
                "transcript": transcript,
                "translated_text": translated_text,
                "extracted_fields": extracted_fields,
                "detected_language": detected_language,
                "asr_provider": asr_provider,
            },
        )

    async def upsert_triage_result(
        self,
        *,
        conversation_id: UUID,
        urgency_tier: str,
        danger_signs: list[str],
        summary: str,
    ) -> None:
        await asyncio.wait_for(
            self._db.table("triage_results")
            .upsert(
                {
                    "conversation_id": str(conversation_id),
                    "urgency_tier": urgency_tier,
                    "danger_signs": danger_signs,
                    "summary": summary,
                },
                on_conflict="conversation_id",
            )
            .execute(),
            timeout=self._timeout,
        )

    async def clinician_by_auth_user(self, auth_user_id: UUID) -> dict[str, Any] | None:
        return await self._select_one("clinicians", "*", {"auth_user_id": str(auth_user_id)})

    async def clinician_for_access_token(self, access_token: str) -> dict[str, Any] | None:
        if not access_token:
            return None
        response = await asyncio.wait_for(
            self._db.auth.get_user(access_token),
            timeout=self._timeout,
        )
        user = getattr(response, "user", None)
        user_id = getattr(user, "id", None)
        if not user_id:
            return None
        try:
            return await self.clinician_by_auth_user(UUID(str(user_id)))
        except ValueError:
            return None

    async def appointment_queue_for_clinician(self, doctor_id: UUID) -> list[dict[str, Any]]:
        """Pending/upcoming appointments for one clinician, most urgent first.

        Urgency ordering is done in Python rather than SQL because "tier" is
        a free-text column (RED/AMBER/GREEN, matching PipelineTurn.urgency_tier)
        and Postgres has no built-in ordering for an ad-hoc text enum.
        """
        response = await asyncio.wait_for(
            self._db.table("appointments")
            .select("*")
            .eq("doctor_id", str(doctor_id))
            .neq("status", "completed")
            .order("scheduled_at")
            .execute(),
            timeout=self._timeout,
        )
        rows = response.data if isinstance(response.data, list) else []
        tier_rank = {"RED": 0, "AMBER": 1, "GREEN": 2}
        return sorted(rows, key=lambda row: tier_rank.get(str(row.get("tier")).upper(), 3))

    async def patient_assigned_to_clinician(self, *, patient_id: UUID, doctor_id: UUID) -> bool:
        """Mirrors the RLS policy shape exactly (any appointment linking the
        two, regardless of status) rather than reusing the queue filter,
        which deliberately excludes completed appointments."""
        response = await asyncio.wait_for(
            self._db.table("appointments")
            .select("id")
            .eq("patient_id", str(patient_id))
            .eq("doctor_id", str(doctor_id))
            .limit(1)
            .execute(),
            timeout=self._timeout,
        )
        rows = response.data if isinstance(response.data, list) else []
        return bool(rows)

    async def triage_form_for_patient(self, patient_id: UUID) -> dict[str, Any] | None:
        """Most recent triage result + the fields collected for it, for the
        clinician's per-patient view."""
        conversation = await asyncio.wait_for(
            self._db.table("conversations")
            .select("id,started_at,status")
            .eq("patient_id", str(patient_id))
            .order("started_at", desc=True)
            .limit(1)
            .execute(),
            timeout=self._timeout,
        )
        conv_rows = conversation.data if isinstance(conversation.data, list) else []
        if not conv_rows:
            return None
        conversation_id = conv_rows[0]["id"]
        triage = await self._select_one(
            "triage_results", "*", {"conversation_id": str(conversation_id)}
        )
        _, fields = await self.load_context(UUID(str(conversation_id)))
        return {
            "conversation_id": conversation_id,
            "conversation_started_at": conv_rows[0].get("started_at"),
            "fields": fields,
            "triage_result": triage,
        }

    async def appointments_for_patient(self, patient_id: UUID) -> list[dict[str, Any]]:
        response = await asyncio.wait_for(
            self._db.table("appointments")
            .select("*")
            .eq("patient_id", str(patient_id))
            .order("scheduled_at", desc=True)
            .execute(),
            timeout=self._timeout,
        )
        return response.data if isinstance(response.data, list) else []

    async def create_prescription(
        self,
        *,
        patient_id: UUID,
        doctor_id: UUID,
        medication: str,
        dosage: str,
        instructions: str,
    ) -> dict[str, Any]:
        return await self._insert_one(
            "prescriptions",
            {
                "patient_id": str(patient_id),
                "doctor_id": str(doctor_id),
                "medication": medication,
                "dosage": dosage,
                "instructions": instructions,
                "status": "issued",
            },
        )

    async def prescriptions_for_patient(self, patient_id: UUID) -> list[dict[str, Any]]:
        response = await asyncio.wait_for(
            self._db.table("prescriptions")
            .select("*")
            .eq("patient_id", str(patient_id))
            .order("issued_at", desc=True)
            .execute(),
            timeout=self._timeout,
        )
        return response.data if isinstance(response.data, list) else []

    async def appointment_by_id(self, appointment_id: UUID) -> dict[str, Any] | None:
        return await self._select_one("appointments", "*", {"id": str(appointment_id)})

    async def create_call_recording(
        self, *, appointment_id: UUID, consent_recorded_at: str
    ) -> dict[str, Any]:
        return await self._insert_one(
            "call_recordings",
            {
                "appointment_id": str(appointment_id),
                "consent_recorded_at": consent_recorded_at,
            },
        )

    async def update_call_recording(
        self,
        *,
        call_recording_id: UUID,
        recording_url: str | None = None,
        transcript: str | None = None,
        key_points_summary: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {}
        if recording_url is not None:
            payload["recording_url"] = recording_url
        if transcript is not None:
            payload["transcript"] = transcript
        if key_points_summary is not None:
            payload["key_points_summary"] = key_points_summary
        if not payload:
            return
        await asyncio.wait_for(
            self._db.table("call_recordings")
            .update(payload)
            .eq("id", str(call_recording_id))
            .execute(),
            timeout=self._timeout,
        )

    async def conversation_history_for_patient(self, patient_id: UUID) -> list[dict[str, Any]]:
        response = await asyncio.wait_for(
            self._db.table("conversations")
            .select("id,channel,started_at,ended_at,status")
            .eq("patient_id", str(patient_id))
            .order("started_at", desc=True)
            .execute(),
            timeout=self._timeout,
        )
        conversations = response.data if isinstance(response.data, list) else []
        results: list[dict[str, Any]] = []
        for conversation in conversations:
            triage = await self._select_one(
                "triage_results", "urgency_tier,summary", {"conversation_id": conversation["id"]}
            )
            results.append({**conversation, "triage_result": triage})
        return results

    async def create_patient_profile(
        self, *, name: str, phone_number: str, email: str, auth_user_id: UUID
    ) -> dict[str, Any]:
        return await self._insert_one(
            "patients",
            {
                "name": name,
                "phone_number": phone_number,
                "email": email,
                "auth_user_id": str(auth_user_id),
            },
        )

    async def create_clinician_profile(
        self,
        *,
        name: str,
        phone_number: str,
        email: str,
        auth_user_id: UUID,
        license_number: str,
        specialty: str,
    ) -> dict[str, Any]:
        return await self._insert_one(
            "clinicians",
            {
                "name": name,
                "phone_number": phone_number,
                "email": email,
                "auth_user_id": str(auth_user_id),
                "license_number": license_number,
                "specialty": specialty,
            },
        )

    async def replace_availability(
        self, *, doctor_id: UUID, windows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        await asyncio.wait_for(
            self._db.table("doctor_availability")
            .delete()
            .eq("doctor_id", str(doctor_id))
            .execute(),
            timeout=self._timeout,
        )
        rows: list[dict[str, Any]] = []
        for window in windows:
            rows.append(
                await self._insert_one(
                    "doctor_availability",
                    {
                        "doctor_id": str(doctor_id),
                        "weekday": window["weekday"],
                        "start_time": window["start_time"],
                        "end_time": window["end_time"],
                    },
                )
            )
        return rows

    async def availability_for_doctor(self, doctor_id: UUID) -> list[dict[str, Any]]:
        response = await asyncio.wait_for(
            self._db.table("doctor_availability")
            .select("*")
            .eq("doctor_id", str(doctor_id))
            .order("weekday")
            .execute(),
            timeout=self._timeout,
        )
        return response.data if isinstance(response.data, list) else []

    async def all_availability(self) -> list[dict[str, Any]]:
        response = await asyncio.wait_for(
            self._db.table("doctor_availability")
            .select("*")
            .order("doctor_id")
            .order("weekday")
            .execute(),
            timeout=self._timeout,
        )
        return response.data if isinstance(response.data, list) else []

    async def booked_slots(self, *, since_iso: str, until_iso: str) -> list[dict[str, Any]]:
        response = await asyncio.wait_for(
            self._db.table("appointments")
            .select("doctor_id,scheduled_at")
            .neq("status", "cancelled")
            .gte("scheduled_at", since_iso)
            .lt("scheduled_at", until_iso)
            .execute(),
            timeout=self._timeout,
        )
        return response.data if isinstance(response.data, list) else []

    async def create_appointment(
        self,
        *,
        patient_id: UUID,
        conversation_id: UUID | None,
        tier: str,
        doctor_id: UUID,
        scheduled_at: str,
        status: str = "scheduled",
    ) -> dict[str, Any]:
        return await self._insert_one(
            "appointments",
            {
                "patient_id": str(patient_id),
                "conversation_id": str(conversation_id) if conversation_id else None,
                "tier": tier,
                "doctor_id": str(doctor_id),
                "scheduled_at": scheduled_at,
                "status": status,
            },
        )

    async def triage_for_conversation(self, conversation_id: UUID) -> dict[str, Any] | None:
        return await self._select_one(
            "triage_results", "*", {"conversation_id": str(conversation_id)}
        )

    async def _insert_one(self, table: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await asyncio.wait_for(
            self._db.table(table).insert(payload).execute(),
            timeout=self._timeout,
        )
        data = response.data
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise RuntimeError(f"Supabase insert returned no row for {table}")
        return data[0]

    async def _select_one(
        self, table: str, columns: str, filters: dict[str, str]
    ) -> dict[str, Any] | None:
        query = self._db.table(table).select(columns)
        for key, value in filters.items():
            query = query.eq(key, value)
        response = await asyncio.wait_for(query.limit(1).execute(), timeout=self._timeout)
        data = response.data
        return data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else None
