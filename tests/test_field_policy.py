from app.dialogue.field_schema import ExtractedFields, RequiredFieldPolicy


def test_required_field_policy_requires_all_configured_fields() -> None:
    policy = RequiredFieldPolicy(fields=("field_a", "field_b"))
    assert policy.is_complete(ExtractedFields(fields={"field_a": "x"})) is False
    assert policy.is_complete(ExtractedFields(fields={"field_a": "x", "field_b": "y"})) is True


def test_empty_policy_never_auto_triages() -> None:
    assert RequiredFieldPolicy().is_complete(ExtractedFields(fields={"anything": "x"})) is False
