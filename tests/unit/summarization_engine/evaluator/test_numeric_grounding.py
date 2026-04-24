from website.features.summarization_engine.evaluator.numeric_grounding import (
    extract_numeric_tokens,
    ground_numeric_claims,
    numeric_validator,
)


def test_extract_dollar_prices():
    tokens = extract_numeric_tokens("It costs $1,299.99 today.")
    assert "$1,299.99" in tokens


def test_extract_percentages():
    tokens = extract_numeric_tokens("Revenue grew 42% and margin 12.5%.")
    assert "42%" in tokens
    assert "12.5%" in tokens


def test_extract_years():
    tokens = extract_numeric_tokens("Founded in 2019, IPO in 2024.")
    assert "2019" in tokens
    assert "2024" in tokens


def test_extract_iso_dates():
    tokens = extract_numeric_tokens("Released on 2024-03-15 and patched 2024-04-01.")
    assert "2024-03-15" in tokens
    assert "2024-04-01" in tokens


def test_extract_bare_integers_above_100():
    tokens = extract_numeric_tokens("Team of 250 engineers serving 10000 users; 50 offices.")
    assert "250" in tokens
    assert "10000" in tokens
    assert "50" not in tokens


def test_extract_empty_string():
    assert extract_numeric_tokens("") == []


def test_extract_no_numbers():
    assert extract_numeric_tokens("No numerics here at all.") == []


def test_extract_dedupes():
    tokens = extract_numeric_tokens("42% then 42% again.")
    assert tokens.count("42%") == 1


def test_ground_all_grounded():
    summary = "Revenue grew 42% to $1,299 in 2024."
    source = "In 2024 revenue grew 42% to $1,299 quarterly."
    grounded, ungrounded = ground_numeric_claims(summary, source)
    assert grounded is True
    assert ungrounded == []


def test_ground_partial():
    summary = "Revenue grew 42% to $1,299 in 2024."
    source = "Revenue grew 42% in 2024."
    grounded, ungrounded = ground_numeric_claims(summary, source)
    assert grounded is False
    assert "$1,299" in ungrounded


def test_ground_none_grounded():
    summary = "Revenue was $500 in 2024."
    source = "The product launched and customers loved it."
    grounded, ungrounded = ground_numeric_claims(summary, source)
    assert grounded is False
    assert "$500" in ungrounded
    assert "2024" in ungrounded


def test_ground_case_insensitive_alpha_around():
    # numeric token is digit-only; case-insensitive normalization applies to surrounding text
    summary = "Released on 2024-03-15."
    source = "RELEASED ON 2024-03-15 AT NOON."
    grounded, ungrounded = ground_numeric_claims(summary, source)
    assert grounded is True
    assert ungrounded == []


def test_ground_whitespace_normalized():
    summary = "It cost $1,299 last year."
    source = "It    cost\n\t$1,299\nlast year."
    grounded, ungrounded = ground_numeric_claims(summary, source)
    assert grounded is True
    assert ungrounded == []


def test_ground_empty_summary():
    grounded, ungrounded = ground_numeric_claims("", "anything")
    assert grounded is True
    assert ungrounded == []


def test_validator_all_grounded_default_threshold():
    res = numeric_validator(
        "Revenue grew 42% to $1,299 in 2024.",
        "In 2024 revenue grew 42% to $1,299 last quarter.",
    )
    assert res["grounded"] is True
    assert res["ungrounded"] == []
    assert res["ratio"] == 1.0


def test_validator_partial_fails_default_threshold():
    res = numeric_validator(
        "Revenue $500 grew 42% in 2024.",
        "Revenue grew 42% in 2024.",
    )
    assert res["grounded"] is False
    assert "$500" in res["ungrounded"]
    assert 0.0 < res["ratio"] < 1.0


def test_validator_partial_passes_with_lower_threshold():
    res = numeric_validator(
        "Revenue $500 grew 42% in 2024.",
        "Revenue grew 42% in 2024.",
        threshold=0.5,
    )
    assert res["grounded"] is True


def test_validator_no_tokens_is_grounded():
    res = numeric_validator("No numbers.", "Source text.")
    assert res["grounded"] is True
    assert res["ratio"] == 1.0
    assert res["ungrounded"] == []
