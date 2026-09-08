from enum import StrEnum

from pydantic import BaseModel


class ConversationState(StrEnum):
    COLLECTING = 'COLLECTING'
    TRIAGE = 'TRIAGE'
    ESCALATE = 'ESCALATE'


class ConversationDecision(BaseModel):
    state: ConversationState
    reason: str


def decide_next_state(*, required_fields_complete: bool, danger_sign_fired: bool) -> ConversationDecision:
    # Non-negotiable safety rule: TRIAGE is reachable only through these two paths.
    if danger_sign_fired:
        return ConversationDecision(state=ConversationState.TRIAGE, reason='danger_sign_fired')
    if required_fields_complete:
        return ConversationDecision(state=ConversationState.TRIAGE, reason='required_fields_complete')
    return ConversationDecision(state=ConversationState.COLLECTING, reason='required_fields_missing')
