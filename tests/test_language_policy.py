from app.dialogue.language_policy import LanguagePolicy, LanguageProfile, LanguageSignal


def test_language_profile_rolls_forward() -> None:
    profile = LanguageProfile.empty()
    policy = LanguagePolicy()
    policy.update_and_get_response_style(profile, LanguageSignal(("en", "pcm")))
    policy.update_and_get_response_style(profile, LanguageSignal(("pcm",)))
    assert profile.dominant_languages()[0] == "pcm"
