from __future__ import annotations


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Standard word-level WER via edit distance: (substitutions +
    deletions + insertions) / len(reference words).

    Returns 0.0 for an empty reference with an empty hypothesis, and 1.0
    (100% error) for an empty reference with any hypothesis words.
    """
    ref_words = reference.split()
    hyp_words = hypothesis.split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0

    n, m = len(ref_words), len(hyp_words)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref_words[i - 1] == hyp_words[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(
                    dp[i - 1][j],      # deletion
                    dp[i][j - 1],      # insertion
                    dp[i - 1][j - 1],  # substitution
                )
    return dp[n][m] / n


def clinical_entity_accuracy(
    reference_fields: dict[str, object], extracted_fields: dict[str, object]
) -> float:
    """Fraction of reference fields correctly recovered by extraction.

    A field counts as correct if present in extracted_fields with a
    case-insensitive substring match against the reference value — exact
    equality is too strict for free-text clinical fields. Fields the
    model added beyond the reference are not penalized (this measures
    recall against ground truth, not precision).
    """
    if not reference_fields:
        return 1.0
    correct = 0
    for key, ref_value in reference_fields.items():
        extracted_value = extracted_fields.get(key)
        if extracted_value is None:
            continue
        if str(ref_value).strip().lower() in str(extracted_value).strip().lower():
            correct += 1
    return correct / len(reference_fields)
