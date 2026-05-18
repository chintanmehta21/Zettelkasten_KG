from __future__ import annotations

from website.features.summarization_engine.core.models import DetailedSummarySection
from website.features.summarization_engine.post_summary_transformation import (
    normalize_markdown_headings,
    transform_detailed_summary_sections,
)


def test_transform_splits_inline_h3_from_bullets_into_subsection() -> None:
    sections = [
        DetailedSummarySection(
            heading="F-strings",
            bullets=[
                "The debug feature remains unchanged. ### Quote Reuse",
                "The same quote character can be used inside expressions.",
                "Backslashes are now allowed. ### Backslashes",
                "Escape sequences work inside expression parts.",
            ],
        )
    ]

    transformed = transform_detailed_summary_sections(sections)

    assert len(transformed) == 1
    assert transformed[0].heading == "F-strings"
    assert transformed[0].bullets == ["The debug feature remains unchanged."]
    assert transformed[0].sub_sections == {
        "Quote Reuse": [
            "The same quote character can be used inside expressions.",
            "Backslashes are now allowed.",
        ],
        "Backslashes": ["Escape sequences work inside expression parts."],
    }


def test_transform_splits_inline_h2_and_h3_into_section_hierarchy() -> None:
    sections = [
        DetailedSummarySection(
            heading="Overview",
            bullets=[
                "The case exposed institutional failures. ## Chapter walkthrough ### Early Life",
                "Ross Ulbricht developed libertarian views during his studies.",
            ],
        )
    ]

    transformed = transform_detailed_summary_sections(sections)

    assert [section.heading for section in transformed] == ["Overview", "Chapter walkthrough"]
    assert transformed[0].bullets == ["The case exposed institutional failures."]
    assert transformed[1].bullets == []
    assert transformed[1].sub_sections == {
        "Early Life": ["Ross Ulbricht developed libertarian views during his studies."]
    }


def test_transform_does_not_split_markers_inside_inline_code() -> None:
    sections = [
        DetailedSummarySection(
            heading="Markdown",
            bullets=[
                "The literal code span `### not a heading` should remain inline. ### Rendered Heading",
                "The following point belongs under the rendered heading.",
            ],
        )
    ]

    transformed = transform_detailed_summary_sections(sections)

    assert transformed[0].bullets == [
        "The literal code span `### not a heading` should remain inline."
    ]
    assert transformed[0].sub_sections == {
        "Rendered Heading": ["The following point belongs under the rendered heading."]
    }


def test_transform_splits_heading_after_unbalanced_inline_code() -> None:
    # Real failure: a code example the LLM split across two bullets leaves an
    # unterminated backtick, which used to flip code-mode permanently and
    # swallow every following heading marker.
    sections = [
        DetailedSummarySection(
            heading="F-strings",
            bullets=[
                "Backslashes are now allowed inside expression parts (e.g., `f\"{'",
                "'.join(items)}\"`). ### Comments",
                "The hash character is now permitted inside multi-line f-strings.",
            ],
        )
    ]

    transformed = transform_detailed_summary_sections(sections)

    assert transformed[0].sub_sections == {
        "Comments": [
            "The hash character is now permitted inside multi-line f-strings.",
        ]
    }
    # The unterminated-backtick bullet is preserved as plain text, heading split out.
    assert any(
        "'.join(items)}\"`)." in bullet for bullet in transformed[0].bullets
    )


def test_transform_keeps_balanced_multi_backtick_span_inline() -> None:
    sections = [
        DetailedSummarySection(
            heading="Markdown",
            bullets=[
                "Use ``code with ` inside`` and ``### still not a heading``. ### Real Heading",
                "Belongs under the real heading.",
            ],
        )
    ]

    transformed = transform_detailed_summary_sections(sections)

    assert transformed[0].bullets == [
        "Use ``code with ` inside`` and ``### still not a heading``."
    ]
    assert transformed[0].sub_sections == {
        "Real Heading": ["Belongs under the real heading."]
    }


def test_normalize_markdown_headings_handles_unbalanced_code_and_trailing_hashes() -> None:
    raw = (
        "- '.join(items)}\"`). ### Comments\n"
        "- Format and speakers ## Chapter walkthrough ###\n"
        "- Format: walkthrough."
    )

    assert normalize_markdown_headings(raw) == (
        "- '.join(items)}\"`).\n\n"
        "### Comments\n"
        "- Format and speakers\n\n"
        "## Chapter walkthrough\n"
        "- Format: walkthrough."
    )


def test_normalize_markdown_headings_splits_inline_markers_for_legacy_rows() -> None:
    raw = (
        "- Their designation is described in RFC 2606 and RFC 6761. ## Availability and Registration\n"
        "- These domains are not available for registration. ## Web Service Provisioning ### Usage\n"
        "- They are examples."
    )

    assert normalize_markdown_headings(raw) == (
        "- Their designation is described in RFC 2606 and RFC 6761.\n\n"
        "## Availability and Registration\n"
        "- These domains are not available for registration.\n\n"
        "## Web Service Provisioning\n\n"
        "### Usage\n"
        "- They are examples."
    )
