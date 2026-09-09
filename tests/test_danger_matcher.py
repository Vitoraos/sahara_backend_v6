from app.dialogue.danger_matcher import DangerMatcher


def test_danger_matcher_matches_raw_transcript() -> None:
    matcher = DangerMatcher(("difficulty breathing", "severe bleeding"))
    result = matcher.match("The patient has difficulty breathing")
    assert result.matched is True
    assert "difficulty breathing" in result.matched_phrases


def test_negated_danger_phrase_does_not_fire():
    matcher = DangerMatcher(("severe chest pain",))
    result = matcher.match("I do not have severe chest pain")
    assert result.matched is False
