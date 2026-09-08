from app.dialogue.state_machine import ConversationState, decide_next_state


def test_triage_requires_complete_fields_or_danger_sign() -> None:
    assert decide_next_state(required_fields_complete=False, danger_sign_fired=False).state == ConversationState.COLLECTING


def test_danger_sign_allows_triage() -> None:
    assert decide_next_state(required_fields_complete=False, danger_sign_fired=True).state == ConversationState.TRIAGE


def test_complete_fields_allow_triage() -> None:
    assert decide_next_state(required_fields_complete=True, danger_sign_fired=False).state == ConversationState.TRIAGE
