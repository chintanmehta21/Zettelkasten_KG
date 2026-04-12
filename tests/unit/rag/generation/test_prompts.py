from website.features.rag_pipeline.generation.prompts import (
    CHAIN_OF_THOUGHT_PREFIX,
    SYSTEM_PROMPT,
    USER_TEMPLATE,
)


def test_system_prompt_contains_seven_rules() -> None:
    for number in range(1, 8):
        assert f"{number}." in SYSTEM_PROMPT


def test_user_template_has_context_xml_and_query_placeholders() -> None:
    assert "{context_xml}" in USER_TEMPLATE
    assert "{user_query}" in USER_TEMPLATE


def test_cot_prefix_exists_as_separate_constant() -> None:
    assert "<scratchpad>" in CHAIN_OF_THOUGHT_PREFIX

