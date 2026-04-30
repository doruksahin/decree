from decree.doctypes import ADR_DEFAULT, DocType


def test_adr_default_has_expected_statuses():
    assert ADR_DEFAULT.statuses == (
        "proposed",
        "accepted",
        "rejected",
        "deprecated",
        "superseded",
    )


def test_adr_default_prefix():
    assert ADR_DEFAULT.prefix == "ADR"
    assert ADR_DEFAULT.digits == 4


def test_adr_default_transitions():
    assert ADR_DEFAULT.transitions["proposed"] == ("accepted", "rejected")
    assert ADR_DEFAULT.transitions["rejected"] == ()


def test_adr_default_ref_re():
    assert ADR_DEFAULT.ref_re.match("ADR-0001")
    assert not ADR_DEFAULT.ref_re.match("PRD-001")


def test_adr_default_filename_re():
    assert ADR_DEFAULT.filename_re.match("0001-use-redis.md")
    assert not ADR_DEFAULT.filename_re.match("001-use-redis.md")  # needs 4 digits


def test_adr_default_actions():
    assert ADR_DEFAULT.actions["accept"] == "accepted"
    assert ADR_DEFAULT.actions["supersede"] == "superseded"


def test_adr_default_required_sections():
    assert "Context and Problem Statement" in ADR_DEFAULT.required_sections
    assert "Considered Options" in ADR_DEFAULT.required_sections
    assert "Decision Outcome" in ADR_DEFAULT.required_sections


def test_adr_default_initial_status():
    assert ADR_DEFAULT.initial_status == "proposed"


def test_adr_default_status_field_requirements():
    assert ADR_DEFAULT.status_field_requirements["superseded"] == ("superseded-by",)
    assert ADR_DEFAULT.status_field_requirements["proposed"] == ()


def test_doctype_format_id():
    assert ADR_DEFAULT.format_id(1) == "ADR-0001"
    assert ADR_DEFAULT.format_id(42) == "ADR-0042"


def test_doctype_parse_number_from_id():
    assert ADR_DEFAULT.parse_number("ADR-0001") == 1
    assert ADR_DEFAULT.parse_number("ADR-0042") == 42


def test_doctype_terminal_statuses():
    """Statuses with no valid transitions are terminal."""
    assert "rejected" in ADR_DEFAULT.terminal_statuses
    assert "deprecated" in ADR_DEFAULT.terminal_statuses
    assert "superseded" in ADR_DEFAULT.terminal_statuses
    assert "proposed" not in ADR_DEFAULT.terminal_statuses


def test_prd_doctype():
    prd = DocType(
        name="prd",
        prefix="PRD",
        digits=3,
        dir="docs/prd",
        initial_status="draft",
        statuses=("draft", "review", "approved", "implemented", "archived"),
        transitions={
            "draft": ("review",),
            "review": ("approved", "draft"),
            "approved": ("implemented",),
            "implemented": ("archived",),
            "archived": (),
        },
        actions={
            "submit": "review",
            "approve": "approved",
            "implement": "implemented",
            "archive": "archived",
        },
        required_sections=("Problem Statement", "Requirements", "Success Criteria"),
    )
    assert prd.ref_re.match("PRD-001")
    assert not prd.ref_re.match("PRD-0001")  # 3 digits, not 4
    assert prd.format_id(1) == "PRD-001"
    assert prd.filename_re.match("001-user-auth.md")
