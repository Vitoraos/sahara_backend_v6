from __future__ import annotations

from app.dialogue.field_schema import ExtractedFields, RequiredFieldPolicy
from app.dialogue.state_machine import ConversationDecision, decide_next_state


class TriageEngine:
    def __init__(self, required_field_policy: RequiredFieldPolicy | None = None) -> None:
        self._policy = required_field_policy or RequiredFieldPolicy()

    def fields_complete(self, extracted: ExtractedFields) -> bool:
        return self._policy.is_complete(extracted)

    def decide(self, *, required_fields_complete: bool, danger_sign_fired: bool) -> ConversationDecision:
        return decide_next_state(
            required_fields_complete=required_fields_complete,
            danger_sign_fired=danger_sign_fired,
        )
