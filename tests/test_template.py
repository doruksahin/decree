"""Tests for decree.template — pure template rendering."""

from decree.doctypes import ADR_DEFAULT, DocType
from decree.template import render_template

ADR_ID = "ADR-00000000000000000000000001"


def test_replaces_placeholders():
    raw = "---\nid: __ID__\nstatus: proposed\ndate: __DATE__\n---\n\n# __ID__ __TITLE__\n"
    result = render_template(raw, doc_id=ADR_ID, title="Use PuLP", slug="use-pulp", today="2026-04-02")
    assert "date: 2026-04-02" in result
    assert f"# {ADR_ID} Use PuLP" in result


def test_appends_missing_required_sections():
    """Sections in doc_type.required_sections not in template are appended."""
    raw = (
        "---\nid: __ID__\nstatus: proposed\ndate: __DATE__\n---\n\n# __ID__ __TITLE__\n\n"
        "## Context and Problem Statement\n\nText.\n\n"
        "## Considered Options\n\n- A\n\n"
        "## Decision Outcome\n\nChosen.\n"
    )
    # ADR_DEFAULT has required_sections: Context and Problem Statement, Considered Options, Decision Outcome
    # Those are already in the template, so nothing should be appended.
    result = render_template(
        raw,
        doc_id=ADR_ID,
        title="Test",
        slug="test",
        today="2026-04-02",
        doc_type=ADR_DEFAULT,
    )
    # Only the 3 sections already present — no extras
    assert result.count("## ") == 3


def test_appends_extra_required_sections():
    """Sections not in the template are appended when doc_type has them."""
    custom_type = DocType(
        name="adr",
        prefix="ADR",
        dir="docs/adr",
        initial_status="proposed",
        statuses=("proposed", "accepted"),
        transitions={"proposed": ("accepted",), "accepted": ()},
        actions={"accept": "accepted"},
        required_sections=(
            "Context and Problem Statement",
            "Considered Options",
            "Decision Outcome",
            "Consequences",
            "Affected Files",
        ),
        section_descriptions={
            "Consequences": "Describe consequences.",
            "Affected Files": "List affected files.",
        },
    )
    raw = (
        "---\nid: __ID__\nstatus: proposed\ndate: __DATE__\n---\n\n# __ID__ __TITLE__\n\n"
        "## Context and Problem Statement\n\nText.\n\n"
        "## Considered Options\n\n- A\n\n"
        "## Decision Outcome\n\nChosen.\n"
    )
    result = render_template(
        raw,
        doc_id=ADR_ID,
        title="Test",
        slug="test",
        today="2026-04-02",
        doc_type=custom_type,
    )
    assert "## Consequences" in result
    assert "## Affected Files" in result


def test_appended_section_without_description_is_explicit():
    """Missing section guidance should be explicit, not a TODO placeholder."""
    custom_type = DocType(
        name="adr",
        prefix="ADR",
        dir="docs/adr",
        initial_status="proposed",
        statuses=("proposed", "accepted"),
        transitions={"proposed": ("accepted",), "accepted": ()},
        actions={"accept": "accepted"},
        required_sections=("Context", "Unconfigured Section"),
        section_descriptions={"Context": "Describe context."},
    )
    result = render_template(
        "# __ID__ __TITLE__\n\n## Context\n\nText.\n",
        doc_id=ADR_ID,
        title="Test",
        slug="test",
        today="2026-04-02",
        doc_type=custom_type,
    )
    assert "## Unconfigured Section" in result
    assert "No section guidance configured." in result
    assert "TODO" not in result


def test_no_extra_sections_without_doc_type():
    """Without doc_type, only placeholder substitution is performed."""
    raw = "# __ID__ __TITLE__\n"
    result = render_template(raw, doc_id=ADR_ID, title="Test", slug="test", today="2026-04-02")
    assert "## Consequences" not in result
    assert "## Affected Files" not in result
