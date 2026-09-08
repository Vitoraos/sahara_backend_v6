from app.benchmark.metrics import clinical_entity_accuracy, word_error_rate


def test_wer_identical_strings_is_zero():
    assert word_error_rate("the patient has a fever", "the patient has a fever") == 0.0


def test_wer_empty_reference_and_hypothesis_is_zero():
    assert word_error_rate("", "") == 0.0


def test_wer_empty_reference_with_hypothesis_is_one():
    assert word_error_rate("", "hello") == 1.0


def test_wer_single_substitution():
    # 1 error out of 5 reference words
    assert word_error_rate("the patient has a fever", "the patient has a cough") == 1 / 5


def test_wer_single_deletion():
    # hypothesis is missing one word relative to a 5-word reference
    assert word_error_rate("the patient has a fever", "the patient has fever") == 1 / 5


def test_entity_accuracy_all_correct():
    ref = {"chief_complaint": "fever", "duration": "two days"}
    extracted = {"chief_complaint": "high fever", "duration": "two days now"}
    assert clinical_entity_accuracy(ref, extracted) == 1.0


def test_entity_accuracy_partial():
    ref = {"chief_complaint": "fever", "duration": "two days"}
    extracted = {"chief_complaint": "fever"}
    assert clinical_entity_accuracy(ref, extracted) == 0.5


def test_entity_accuracy_empty_reference_is_one():
    assert clinical_entity_accuracy({}, {"anything": "here"}) == 1.0
