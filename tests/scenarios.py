"""
Real-world scenario fixtures for decree smoke tests.

These fixtures model realistic product development lifecycles,
primarily a SaaS company adding "Team Billing" to their product.

Document flow (typical, not enforced):
    PRD (business need) -> ADR (architecture choice) -> SPEC (technical blueprint)

Reference direction (convention, not enforced):
    Downstream documents typically reference upstream documents.
    SPEC references ADRs and PRDs. ADR references PRDs.
    PRDs may reference other PRDs (for lineage when splitting/merging).
    Reverse and lateral references are valid (not directionally enforced).

Key design decisions encoded in these scenarios:
    - "Dead" statuses (warn_on_reference) != terminal statuses
      e.g., "implemented" is terminal (no transitions) but HEALTHY to reference.
      "rejected", "superseded", "deprecated", "archived" are DEAD.
    - Reference direction is NOT enforced. ADR can reference SPEC.
    - Circular references are ALLOWED (co-dependent specs).
    - Staleness is DIRECT only, not transitive.
    - Self-references are FLAGGED as errors.

Relationship graph for the happy-path fixture:

    PRD-00000000000000000000000001  "Team Billing"  (approved)
      ^       ^       ^
      |       |       |
    ADR-00000000000000000000000001  ADR-00000000000000000000000002          ADR-00000000000000000000000003
    "Stripe"  "Per-seat"        "Metered billing"
    (accepted) (superseded)----->(accepted)
      ^    ^                       ^
      |    |                       |
      |  SPEC-00000000000000000000000001 "Billing API"  (approved)
      |    refs: [PRD-00000000000000000000000001, ADR-00000000000000000000000001, ADR-00000000000000000000000003]
      |
    SPEC-00000000000000000000000002 "Stripe Webhooks"  (draft)
      refs: [ADR-00000000000000000000000001, SPEC-00000000000000000000000001]
"""

# ── TOML config shared across all scenarios ──────────────────
#
# warn_on_reference: statuses that are "dead" — referencing them is a problem.
# This is DIFFERENT from terminal statuses (no transitions).
# "implemented" is terminal but healthy. "rejected" is terminal and dead.

MULTI_TYPE_CONFIG = """\
[types.adr]
dir = "docs/adr"
prefix = "ADR"
digits = 4
initial_status = "proposed"
statuses = ["proposed", "accepted", "rejected", "deprecated", "superseded"]
warn_on_reference = ["rejected", "deprecated", "superseded"]
required_sections = ["Context and Problem Statement", "Considered Options", "Decision Outcome"]

[types.adr.transitions]
proposed = ["accepted", "rejected"]
accepted = ["deprecated", "superseded"]
rejected = []
deprecated = []
superseded = []

[types.adr.actions]
accept = "accepted"
reject = "rejected"
deprecate = "deprecated"
supersede = "superseded"

[types.adr.status_field_requirements]
superseded = ["superseded-by"]

[types.prd]
dir = "docs/prd"
prefix = "PRD"
digits = 3
initial_status = "draft"
statuses = ["draft", "review", "approved", "implemented", "archived"]
warn_on_reference = ["archived"]
required_sections = ["Problem Statement", "Requirements", "Success Criteria"]

[types.prd.transitions]
draft = ["review"]
review = ["approved", "draft"]
approved = ["implemented", "archived"]
implemented = ["archived"]
archived = []

[types.prd.actions]
submit = "review"
approve = "approved"
implement = "implemented"
archive = "archived"

[types.spec]
dir = "docs/spec"
prefix = "SPEC"
digits = 3
initial_status = "draft"
statuses = ["draft", "review", "approved", "implemented"]
warn_on_reference = []
required_sections = ["Overview", "Technical Design", "Testing Strategy"]

[types.spec.transitions]
draft = ["review"]
review = ["approved", "draft"]
approved = ["implemented"]
implemented = []

[types.spec.actions]
submit = "review"
approve = "approved"
implement = "implemented"
"""


# ── Document content builders ────────────────────────────────


def _doc_id(prefix: str, number: int) -> str:
    return f"{prefix}-{number:026d}"


def _adr(number, title, status, references=None, supersedes=None, superseded_by=None):
    """Build an ADR markdown string."""
    doc_id = _doc_id("ADR", number)
    fm_lines = ["---", f"id: {doc_id}", f"status: {status}", "date: 2026-04-01"]
    if references:
        fm_lines.append(f"references: [{', '.join(references)}]")
    if supersedes:
        fm_lines.append(f"supersedes: {supersedes}")
    if superseded_by:
        fm_lines.append(f"superseded-by: {superseded_by}")
    fm_lines.append("---")
    body = f"""
# {doc_id} {title}

## Context and Problem Statement

Architectural context for {title.lower()}.

## Considered Options

- Option A
- Option B

## Decision Outcome

Chosen option: the one that works.
"""
    return "\n".join(fm_lines) + body


def _prd(number, title, status, references=None):
    """Build a PRD markdown string."""
    doc_id = _doc_id("PRD", number)
    fm_lines = ["---", f"id: {doc_id}", f"status: {status}", "date: 2026-03-15"]
    if references:
        fm_lines.append(f"references: [{', '.join(references)}]")
    fm_lines.append("---")
    body = f"""
# {doc_id} {title}

## Problem Statement

Business need for {title.lower()}.

## Requirements

- Requirement 1
- Requirement 2

## Success Criteria

- Revenue impact measurable within Q2.
"""
    return "\n".join(fm_lines) + body


def _spec(number, title, status, references=None):
    """Build a SPEC markdown string."""
    doc_id = _doc_id("SPEC", number)
    fm_lines = ["---", f"id: {doc_id}", f"status: {status}", "date: 2026-04-03"]
    if references:
        fm_lines.append(f"references: [{', '.join(references)}]")
    fm_lines.append("---")
    body = f"""
# {doc_id} {title}

## Overview

Technical design for {title.lower()}.

## Technical Design

The detailed blueprint.

## Testing Strategy

Integration tests against staging Stripe.
"""
    return "\n".join(fm_lines) + body


def _slug(title):
    return title.lower().replace(" ", "-").replace("(", "").replace(")", "")


# ── Project scaffolding ──────────────────────────────────────


def scaffold_project(tmp_path):
    """Create the decree.toml and empty doc directories."""
    (tmp_path / "decree.toml").write_text(MULTI_TYPE_CONFIG)
    for d in ("docs/adr", "docs/prd", "docs/spec"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


def write_doc(tmp_path, doc_type, number, title, content):
    """Write a document file to the correct directory."""
    slug = _slug(title)
    filename = f"{_doc_id(doc_type.upper(), number).lower()}-{slug}.md"
    path = tmp_path / f"docs/{doc_type}" / filename
    path.write_text(content)
    return path


# ══════════════════════════════════════════════════════════════
# PASSING scenarios — lint should report 0 errors
# ══════════════════════════════════════════════════════════════


def scenario_happy_path(tmp_path):
    """
    Everything aligned. All references valid. Lint passes clean.

    PRD-00000000000000000000000001 (approved)
      ^       ^       ^
      |       |       |
    ADR-00000000000000000000000001 (accepted)   refs: [PRD-00000000000000000000000001]
    ADR-00000000000000000000000002 (superseded)
      refs: [PRD-00000000000000000000000001]
      superseded-by: ADR-00000000000000000000000003
    ADR-00000000000000000000000003 (accepted)
      refs: [PRD-00000000000000000000000001]
      supersedes: ADR-00000000000000000000000002
      ^                     ^
      |                     |
    SPEC-00000000000000000000000001 (approved)
      refs: [PRD-00000000000000000000000001, ADR-00000000000000000000000001,
             ADR-00000000000000000000000003]
      ^
      |
    SPEC-00000000000000000000000002 (draft)      refs: [ADR-00000000000000000000000001, SPEC-00000000000000000000000001]

    Expected: PASS — ADR-00000000000000000000000002 is superseded but nothing references it directly.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "Team Billing", _prd(1, "Team Billing", "approved"))
    write_doc(
        proj,
        "adr",
        1,
        "Use Stripe",
        _adr(1, "Use Stripe", "accepted", references=["PRD-00000000000000000000000001"]),
    )
    write_doc(
        proj,
        "adr",
        2,
        "Per-seat billing",
        _adr(
            2,
            "Per-seat billing",
            "superseded",
            references=["PRD-00000000000000000000000001"],
            superseded_by="ADR-00000000000000000000000003",
        ),
    )
    write_doc(
        proj,
        "adr",
        3,
        "Metered billing",
        _adr(
            3,
            "Metered billing",
            "accepted",
            references=["PRD-00000000000000000000000001"],
            supersedes="ADR-00000000000000000000000002",
        ),
    )
    write_doc(
        proj,
        "spec",
        1,
        "Billing API",
        _spec(
            1,
            "Billing API",
            "approved",
            references=[
                "PRD-00000000000000000000000001",
                "ADR-00000000000000000000000001",
                "ADR-00000000000000000000000003",
            ],
        ),
    )
    write_doc(
        proj,
        "spec",
        2,
        "Stripe Webhooks",
        _spec(
            2,
            "Stripe Webhooks",
            "draft",
            references=["ADR-00000000000000000000000001", "SPEC-00000000000000000000000001"],
        ),
    )
    return proj


def scenario_shared_adr(tmp_path):
    """
    One ADR serves two PRDs. Shared infrastructure decision.

    PRD-00000000000000000000000001 (approved)   PRD-00000000000000000000000002 (approved)
      ^       ^             ^       ^
      |       |             |       |
      +---ADR-00000000000000000000000001 (accepted)---+
          refs: [PRD-00000000000000000000000001, PRD-00000000000000000000000002]
          ^                 ^
          |                 |
        SPEC-00000000000000000000000001 (approved) SPEC-00000000000000000000000002 (draft)

    Expected: PASS — one ADR serving multiple PRDs is valid.
    """
    proj = scaffold_project(tmp_path)
    write_doc(
        proj,
        "prd",
        1,
        "Real-time Dashboard",
        _prd(1, "Real-time Dashboard", "approved"),
    )
    write_doc(proj, "prd", 2, "Session Caching", _prd(2, "Session Caching", "approved"))
    write_doc(
        proj,
        "adr",
        1,
        "Use Redis",
        _adr(
            1, "Use Redis", "accepted", references=["PRD-00000000000000000000000001", "PRD-00000000000000000000000002"]
        ),
    )
    write_doc(
        proj,
        "spec",
        1,
        "Redis Setup",
        _spec(
            1,
            "Redis Setup",
            "approved",
            references=["ADR-00000000000000000000000001", "PRD-00000000000000000000000001"],
        ),
    )
    write_doc(
        proj,
        "spec",
        2,
        "Cache Layer",
        _spec(
            2, "Cache Layer", "draft", references=["ADR-00000000000000000000000001", "PRD-00000000000000000000000002"]
        ),
    )
    return proj


def scenario_infra_no_prd(tmp_path):
    """
    Tech debt work. ADR without any PRD. Valid — not all decisions are product-driven.

    ADR-00000000000000000000000001 (accepted)  "Migrate to PG16"  refs: []
      ^
      |
    SPEC-00000000000000000000000001 (draft)     "PG16 Runbook"     refs: [ADR-00000000000000000000000001]

    Expected: PASS — no PRD required.
    """
    proj = scaffold_project(tmp_path)
    write_doc(
        proj,
        "adr",
        1,
        "Migrate to PostgreSQL 16",
        _adr(1, "Migrate to PostgreSQL 16", "accepted"),
    )
    write_doc(
        proj,
        "spec",
        1,
        "PG16 Migration Runbook",
        _spec(1, "PG16 Migration Runbook", "draft", references=["ADR-00000000000000000000000001"]),
    )
    return proj


def scenario_lateral_spec_references(tmp_path):
    """
    SPEC-00000000000000000000000002 extends SPEC-00000000000000000000000001 (same-type lateral reference).

    SPEC-00000000000000000000000001 (approved)  refs: [ADR-00000000000000000000000001]
      ^
      |
    SPEC-00000000000000000000000002 (draft)     refs: [SPEC-00000000000000000000000001]

    Expected: PASS — same-type references are valid.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "Team Billing", _prd(1, "Team Billing", "approved"))
    write_doc(
        proj,
        "adr",
        1,
        "Use Stripe",
        _adr(1, "Use Stripe", "accepted", references=["PRD-00000000000000000000000001"]),
    )
    write_doc(
        proj,
        "spec",
        1,
        "Core Billing API",
        _spec(1, "Core Billing API", "approved", references=["ADR-00000000000000000000000001"]),
    )
    write_doc(
        proj,
        "spec",
        2,
        "Billing Webhooks",
        _spec(2, "Billing Webhooks", "draft", references=["SPEC-00000000000000000000000001"]),
    )
    return proj


def scenario_reference_implemented_spec(tmp_path):
    """
    SPEC-00000000000000000000000002 references implemented SPEC-00000000000000000000000001.
    The referenced SPEC is terminal but healthy.

    SPEC-00000000000000000000000001 (implemented)
      refs: [ADR-00000000000000000000000001]  <-- terminal status, but NOT dead
      ^
      |
    SPEC-00000000000000000000000002 (draft)        refs: [SPEC-00000000000000000000000001]  <-- should be valid!

    Expected: PASS — "implemented" is not in warn_on_reference for SPEC.
    This is the critical test that distinguishes terminal from dead.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "adr", 1, "Use Stripe", _adr(1, "Use Stripe", "accepted"))
    write_doc(
        proj,
        "spec",
        1,
        "Billing API",
        _spec(1, "Billing API", "implemented", references=["ADR-00000000000000000000000001"]),
    )
    write_doc(
        proj,
        "spec",
        2,
        "Billing Webhooks",
        _spec(2, "Billing Webhooks", "draft", references=["SPEC-00000000000000000000000001"]),
    )
    return proj


def scenario_circular_spec_references(tmp_path):
    """
    Two SPECs that co-depend. Common in real projects (e.g., Auth API and
    Session Management that reference each other).

    SPEC-00000000000000000000000001 (approved)  refs: [SPEC-00000000000000000000000002]
      ^                          |
      |                          v
    SPEC-00000000000000000000000002 (approved)  refs: [SPEC-00000000000000000000000001]

    Expected: PASS — circular references are allowed.
    """
    proj = scaffold_project(tmp_path)
    write_doc(
        proj,
        "spec",
        1,
        "Auth API",
        _spec(1, "Auth API", "approved", references=["SPEC-00000000000000000000000002"]),
    )
    write_doc(
        proj,
        "spec",
        2,
        "Session Management",
        _spec(2, "Session Management", "approved", references=["SPEC-00000000000000000000000001"]),
    )
    return proj


def scenario_spec_before_adr_accepted(tmp_path):
    """
    SPEC written speculatively before ADR is formally accepted.
    "proposed" is not a dead status — this is valid permissive behavior.

    ADR-00000000000000000000000001 (proposed)   <-- NOT yet accepted
      ^
      |
    SPEC-00000000000000000000000001 (draft)      refs: [ADR-00000000000000000000000001]

    Expected: PASS — "proposed" is not in warn_on_reference.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "adr", 1, "Auth via JWT", _adr(1, "Auth via JWT", "proposed"))
    write_doc(
        proj,
        "spec",
        1,
        "JWT Token API",
        _spec(1, "JWT Token API", "draft", references=["ADR-00000000000000000000000001"]),
    )
    return proj


def scenario_reverse_reference(tmp_path):
    """
    ADR references a SPEC (reverse direction). "See also" link.
    Reference direction is convention, not enforced.

    ADR-00000000000000000000000001 (accepted)   refs: [SPEC-00000000000000000000000001]   <-- "backwards" but valid
    SPEC-00000000000000000000000001 (approved)   refs: [ADR-00000000000000000000000001]

    Expected: PASS — direction is not enforced.
    """
    proj = scaffold_project(tmp_path)
    write_doc(
        proj,
        "adr",
        1,
        "Use Stripe",
        _adr(1, "Use Stripe", "accepted", references=["SPEC-00000000000000000000000001"]),
    )
    write_doc(
        proj,
        "spec",
        1,
        "Stripe Integration",
        _spec(1, "Stripe Integration", "approved", references=["ADR-00000000000000000000000001"]),
    )
    return proj


def scenario_competing_adrs(tmp_path):
    """
    Multiple proposed ADRs for the same problem. Common during design phase.

    PRD-00000000000000000000000001 (approved)
      ^       ^       ^
      |       |       |
    ADR-00000000000000000000000001 (proposed)  "JWT"     refs: [PRD-00000000000000000000000001]
    ADR-00000000000000000000000002 (proposed)  "OAuth2"  refs: [PRD-00000000000000000000000001]
    ADR-00000000000000000000000003 (proposed)  "SAML"    refs: [PRD-00000000000000000000000001]

    Expected: PASS — multiple proposed ADRs is valid workflow.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "User Auth", _prd(1, "User Auth", "approved"))
    write_doc(
        proj,
        "adr",
        1,
        "Auth via JWT",
        _adr(1, "Auth via JWT", "proposed", references=["PRD-00000000000000000000000001"]),
    )
    write_doc(
        proj,
        "adr",
        2,
        "Auth via OAuth2",
        _adr(2, "Auth via OAuth2", "proposed", references=["PRD-00000000000000000000000001"]),
    )
    write_doc(
        proj,
        "adr",
        3,
        "Auth via SAML",
        _adr(3, "Auth via SAML", "proposed", references=["PRD-00000000000000000000000001"]),
    )
    return proj


def scenario_prd_references_prd(tmp_path):
    """
    PRD-00000000000000000000000002 extends PRD-00000000000000000000000001 (lateral PRD reference for enterprise tier).

    PRD-00000000000000000000000001 (approved)  "Team Billing"
      ^
      |
    PRD-00000000000000000000000002 (approved)  "Enterprise Billing"  refs: [PRD-00000000000000000000000001]

    Expected: PASS — PRD-to-PRD references are valid.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "Team Billing", _prd(1, "Team Billing", "approved"))
    write_doc(
        proj,
        "prd",
        2,
        "Enterprise Billing",
        _prd(2, "Enterprise Billing", "approved", references=["PRD-00000000000000000000000001"]),
    )
    return proj


def scenario_explicit_empty_references(tmp_path):
    """
    Document with explicit `references: []` in frontmatter.
    Different from omitting the field entirely. Should be treated the same.

    ADR-00000000000000000000000001 (accepted)  references: []  <-- explicit empty list

    Expected: PASS — empty references list is valid, same as absent field.
    """
    proj = scaffold_project(tmp_path)
    # Build manually to emit `references: []` (the builder skips falsy references)
    content = (
        "---\n"
        "id: ADR-00000000000000000000000001\n"
        "status: accepted\n"
        "date: 2026-04-01\n"
        "references: []\n"
        "---\n"
        "\n"
        "# ADR-00000000000000000000000001 Use Stripe\n"
        "\n"
        "## Context and Problem Statement\n"
        "\n"
        "Context.\n"
        "\n"
        "## Considered Options\n"
        "\n"
        "- A\n"
        "\n"
        "## Decision Outcome\n"
        "\n"
        "Chosen option: A.\n"
    )
    write_doc(proj, "adr", 1, "Use Stripe", content)
    return proj


def scenario_empty_project(tmp_path):
    """
    Freshly initialized project. No documents in any directory.

    docs/adr/  (empty)
    docs/prd/  (empty)
    docs/spec/ (empty)

    Expected: PASS — nothing to lint, clean result.
    """
    return scaffold_project(tmp_path)


def scenario_deep_chain_no_transitive_staleness(tmp_path):
    """
    Deep chain: PRD -> ADR -> SPEC -> SPEC -> SPEC.
    ADR gets superseded. Only the DIRECT reference is flagged.

    PRD-00000000000000000000000001 (approved)
      ^
      |
    ADR-00000000000000000000000001 (superseded)   superseded-by: ADR-00000000000000000000000002
    ADR-00000000000000000000000002 (accepted)     supersedes: ADR-00000000000000000000000001
      ^
      |
    SPEC-00000000000000000000000001 (approved)
      refs: [ADR-00000000000000000000000001]   <-- STALE (direct ref to superseded)
      ^
      |
    SPEC-00000000000000000000000002 (approved)
      refs: [SPEC-00000000000000000000000001]   <-- NOT stale; referenced SPEC is approved
      ^
      |
    SPEC-00000000000000000000000003 (draft)
      refs: [SPEC-00000000000000000000000002]   <-- NOT stale; referenced SPEC is approved

    Expected: FAIL — but only 1 error (SPEC-00000000000000000000000001 -> ADR-00000000000000000000000001).
    SPEC-00000000000000000000000002 and SPEC-00000000000000000000000003 are NOT flagged.
    Staleness is direct-only.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "Team Billing", _prd(1, "Team Billing", "approved"))
    write_doc(
        proj,
        "adr",
        1,
        "Per-seat billing",
        _adr(
            1,
            "Per-seat billing",
            "superseded",
            references=["PRD-00000000000000000000000001"],
            superseded_by="ADR-00000000000000000000000002",
        ),
    )
    write_doc(
        proj,
        "adr",
        2,
        "Metered billing",
        _adr(
            2,
            "Metered billing",
            "accepted",
            references=["PRD-00000000000000000000000001"],
            supersedes="ADR-00000000000000000000000001",
        ),
    )
    write_doc(
        proj,
        "spec",
        1,
        "Billing Core",
        _spec(1, "Billing Core", "approved", references=["ADR-00000000000000000000000001"]),
    )
    write_doc(
        proj,
        "spec",
        2,
        "Billing Extensions",
        _spec(2, "Billing Extensions", "approved", references=["SPEC-00000000000000000000000001"]),
    )
    write_doc(
        proj,
        "spec",
        3,
        "Billing Webhooks",
        _spec(3, "Billing Webhooks", "draft", references=["SPEC-00000000000000000000000002"]),
    )
    return proj


# ══════════════════════════════════════════════════════════════
# FAILING scenarios — lint should report errors
# ══════════════════════════════════════════════════════════════


def scenario_stale_spec(tmp_path):
    """
    SPEC-00000000000000000000000001 references ADR-00000000000000000000000002 which was superseded.

    SPEC-00000000000000000000000001 (approved)
      refs: [PRD-00000000000000000000000001, ADR-00000000000000000000000001,
             ADR-00000000000000000000000002]
                                                    ^^^^^^^^
                                STALE! ADR-00000000000000000000000002 is superseded.

    Expected: FAIL — 1 error: SPEC-00000000000000000000000001 references ADR-00000000000000000000000002 (superseded)
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "Team Billing", _prd(1, "Team Billing", "approved"))
    write_doc(
        proj,
        "adr",
        1,
        "Use Stripe",
        _adr(1, "Use Stripe", "accepted", references=["PRD-00000000000000000000000001"]),
    )
    write_doc(
        proj,
        "adr",
        2,
        "Per-seat billing",
        _adr(
            2,
            "Per-seat billing",
            "superseded",
            references=["PRD-00000000000000000000000001"],
            superseded_by="ADR-00000000000000000000000003",
        ),
    )
    write_doc(
        proj,
        "adr",
        3,
        "Metered billing",
        _adr(
            3,
            "Metered billing",
            "accepted",
            references=["PRD-00000000000000000000000001"],
            supersedes="ADR-00000000000000000000000002",
        ),
    )
    write_doc(
        proj,
        "spec",
        1,
        "Billing API",
        _spec(
            1,
            "Billing API",
            "approved",
            references=[
                "PRD-00000000000000000000000001",
                "ADR-00000000000000000000000001",
                "ADR-00000000000000000000000002",
            ],
        ),
    )
    return proj


def scenario_rejected_adr_orphaned_spec(tmp_path):
    """
    SPEC building on a rejected ADR.

    ADR-00000000000000000000000001 (rejected)   refs: [PRD-00000000000000000000000001]
      ^
      |
    SPEC-00000000000000000000000001 (draft)      refs: [ADR-00000000000000000000000001]   <-- STALE

    Expected: FAIL — SPEC-00000000000000000000000001 references ADR-00000000000000000000000001 (rejected)
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "User Auth", _prd(1, "User Auth", "approved"))
    write_doc(
        proj,
        "adr",
        1,
        "Auth via JWT",
        _adr(1, "Auth via JWT", "rejected", references=["PRD-00000000000000000000000001"]),
    )
    write_doc(
        proj,
        "spec",
        1,
        "JWT Token API",
        _spec(1, "JWT Token API", "draft", references=["ADR-00000000000000000000000001"]),
    )
    return proj


def scenario_archived_prd_cascade(tmp_path):
    """
    Business killed the feature. PRD archived. All downstream references are stale.

    PRD-00000000000000000000000001 (archived)
      ^       ^       ^
      |       |       |
    ADR-00000000000000000000000001 refs:[PRD-00000000000000000000000001]
    ADR-00000000000000000000000002 refs:[PRD-00000000000000000000000001]
    SPEC-00000000000000000000000001
      refs:[PRD-00000000000000000000000001, ADR-00000000000000000000000001]

    Expected: FAIL — 3 errors.
    ADR-00000000000000000000000001, ADR-00000000000000000000000002,
    and SPEC-00000000000000000000000001 all reference archived PRD.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "Team Billing", _prd(1, "Team Billing", "archived"))
    write_doc(
        proj,
        "adr",
        1,
        "Use Stripe",
        _adr(1, "Use Stripe", "accepted", references=["PRD-00000000000000000000000001"]),
    )
    write_doc(
        proj,
        "adr",
        2,
        "Metered billing",
        _adr(2, "Metered billing", "accepted", references=["PRD-00000000000000000000000001"]),
    )
    write_doc(
        proj,
        "spec",
        1,
        "Billing API",
        _spec(
            1,
            "Billing API",
            "approved",
            references=["PRD-00000000000000000000000001", "ADR-00000000000000000000000001"],
        ),
    )
    return proj


def scenario_dangling_reference(tmp_path):
    """
    SPEC references an ADR that doesn't exist. Typo or deleted file.

    SPEC-00000000000000000000000001 (draft)  refs: [ADR-00000000000000000000000001, ADR-00000000000000000000000099]
                                        ^^^^^^^^ DANGLING

    Expected: FAIL — ADR-00000000000000000000000099 does not exist
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "Team Billing", _prd(1, "Team Billing", "approved"))
    write_doc(
        proj,
        "adr",
        1,
        "Use Stripe",
        _adr(1, "Use Stripe", "accepted", references=["PRD-00000000000000000000000001"]),
    )
    write_doc(
        proj,
        "spec",
        1,
        "Billing API",
        _spec(
            1, "Billing API", "draft", references=["ADR-00000000000000000000000001", "ADR-00000000000000000000000099"]
        ),
    )
    return proj


def scenario_adr_dangling_to_prd(tmp_path):
    """
    ADR references a PRD that doesn't exist. Different code path from SPEC->ADR dangling.

    ADR-00000000000000000000000001 (accepted)  refs: [PRD-00000000000000000000000099]
                                ^^^^^^^ DANGLING

    Expected: FAIL — PRD-00000000000000000000000099 does not exist
    """
    proj = scaffold_project(tmp_path)
    write_doc(
        proj,
        "adr",
        1,
        "Use Stripe",
        _adr(1, "Use Stripe", "accepted", references=["PRD-00000000000000000000000099"]),
    )
    return proj


def scenario_self_reference(tmp_path):
    """
    Document references itself. Almost certainly a copy-paste mistake.

    SPEC-00000000000000000000000001 (draft)  refs: [SPEC-00000000000000000000000001]
                             ^^^^^^^^ SELF-REFERENCE

    Expected: FAIL — self-reference detected
    """
    proj = scaffold_project(tmp_path)
    write_doc(
        proj,
        "spec",
        1,
        "Billing API",
        _spec(1, "Billing API", "draft", references=["SPEC-00000000000000000000000001"]),
    )
    return proj


def scenario_broken_supersede_symmetry(tmp_path):
    """
    ADR-00000000000000000000000001 claims superseded-by ADR-00000000000000000000000002,
    but the target is missing supersedes. Broken symmetry.

    ADR-00000000000000000000000001 (superseded)  superseded-by: ADR-00000000000000000000000002
    ADR-00000000000000000000000002 (accepted)    supersedes: <MISSING>

    Expected: FAIL — asymmetric supersede chain
    """
    proj = scaffold_project(tmp_path)
    write_doc(
        proj,
        "adr",
        1,
        "Per-seat billing",
        _adr(1, "Per-seat billing", "superseded", superseded_by="ADR-00000000000000000000000002"),
    )
    write_doc(proj, "adr", 2, "Metered billing", _adr(2, "Metered billing", "accepted"))
    # Note: ADR-00000000000000000000000002 does NOT have supersedes: ADR-00000000000000000000000001
    return proj


def scenario_duplicate_ids(tmp_path):
    """
    Two files in the same directory map to the same ID. Bad merge or manual error.

    docs/adr/0001-use-redis.md       -> ADR-00000000000000000000000001
    docs/adr/0001-use-memcached.md   -> ADR-00000000000000000000000001 (collision!)

    Expected: FAIL — duplicate ID detected
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "adr", 1, "Use Redis", _adr(1, "Use Redis", "accepted"))
    # Write a second file that also maps to ADR-00000000000000000000000001
    slug2 = "use-memcached"
    path2 = proj / "docs" / "adr" / f"adr-00000000000000000000000001-{slug2}.md"
    path2.write_text(_adr(1, "Use Memcached", "accepted"))
    return proj


def scenario_dangling_supersede_target(tmp_path):
    """
    ADR-00000000000000000000000001 claims superseded-by ADR-00000000000000000000000099,
    but ADR-00000000000000000000000099 doesn't exist at all.
    Different from broken symmetry — the target file is completely absent.

    ADR-00000000000000000000000001 (superseded)
      superseded-by: ADR-00000000000000000000000099  <-- DANGLING! file doesn't exist.

    Expected: FAIL — dangling supersede reference
    """
    proj = scaffold_project(tmp_path)
    write_doc(
        proj,
        "adr",
        1,
        "Per-seat billing",
        _adr(1, "Per-seat billing", "superseded", superseded_by="ADR-00000000000000000000000099"),
    )
    return proj


def scenario_deprecated_adr_no_replacement(tmp_path):
    """
    ADR deprecated (tech is EOL). Unlike superseded, there's no replacement.
    Error message should reflect this.

    ADR-00000000000000000000000001 (deprecated)   <-- no superseded-by, just deprecated
      ^
      |
    SPEC-00000000000000000000000001 (approved)     refs: [ADR-00000000000000000000000001]   <-- STALE

    Expected: FAIL — ADR-00000000000000000000000001 is deprecated (different from superseded)
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "adr", 1, "Use Legacy API", _adr(1, "Use Legacy API", "deprecated"))
    write_doc(
        proj,
        "spec",
        1,
        "Legacy Integration",
        _spec(1, "Legacy Integration", "approved", references=["ADR-00000000000000000000000001"]),
    )
    return proj


def scenario_unknown_prefix_reference(tmp_path):
    """
    SPEC references an ID with a prefix that is not a configured document type.

    SPEC-00000000000000000000000001 (draft)  refs: [RFC-001]
                             ^^^^^^^ RFC is not a configured type.

    Expected: FAIL — RFC-001 does not match any known type, treated as dangling.
    """
    proj = scaffold_project(tmp_path)
    write_doc(
        proj,
        "spec",
        1,
        "Billing API",
        _spec(1, "Billing API", "draft", references=["RFC-001"]),
    )
    return proj


def scenario_malformed_reference_id(tmp_path):
    """
    References field contains IDs with wrong format.

    SPEC-00000000000000000000000001 (draft)  refs: [ADR-1, adr-0001]
                             ^^^^^  ^^^^^^^^
                         Wrong digits  Lowercase prefix

    Expected: FAIL — malformed IDs should be flagged (dangling or format error).
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "adr", 1, "Use Stripe", _adr(1, "Use Stripe", "accepted"))
    write_doc(
        proj,
        "spec",
        1,
        "Billing API",
        _spec(1, "Billing API", "draft", references=["ADR-1", "adr-0001"]),
    )
    return proj


def scenario_prd_split(tmp_path):
    """
    PRD-00000000000000000000000001 was too broad, gets archived.
    It splits into PRD-00000000000000000000000002 and PRD-00000000000000000000000003.
    Downstream ADR still references the archived parent.

    PRD-00000000000000000000000001 (archived)                  <-- split, archived
      ^       ^       ^
      |       |       |
    PRD-00000000000000000000000002 refs:[PRD-00000000000000000000000001] (approved)
      <-- lineage trace to archived parent is stale
    PRD-00000000000000000000000003 refs:[PRD-00000000000000000000000001] (approved)
      <-- lineage trace to archived parent is stale
    ADR-00000000000000000000000001 refs:[PRD-00000000000000000000000001] (accepted)
      <-- STALE; should ref one of the split PRDs

    Expected: FAIL — 3 errors.
    PRD-00000000000000000000000002, PRD-00000000000000000000000003,
    and ADR-00000000000000000000000001 all ref archived PRD-00000000000000000000000001.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "Billing", _prd(1, "Billing", "archived"))
    write_doc(
        proj,
        "prd",
        2,
        "Team Billing",
        _prd(2, "Team Billing", "approved", references=["PRD-00000000000000000000000001"]),
    )
    write_doc(
        proj,
        "prd",
        3,
        "Enterprise Billing",
        _prd(3, "Enterprise Billing", "approved", references=["PRD-00000000000000000000000001"]),
    )
    write_doc(
        proj,
        "adr",
        1,
        "Use Stripe",
        _adr(1, "Use Stripe", "accepted", references=["PRD-00000000000000000000000001"]),
    )
    return proj


def scenario_dangling_supersedes_field(tmp_path):
    """
    ADR-00000000000000000000000002 claims supersedes ADR-00000000000000000000000099,
    but ADR-00000000000000000000000099 doesn't exist.
    Reverse direction of scenario_dangling_supersede_target.

    ADR-00000000000000000000000002 (accepted)  supersedes: ADR-00000000000000000000000099  <-- DANGLING

    Expected: FAIL — referenced ADR does not exist
    """
    proj = scaffold_project(tmp_path)
    write_doc(
        proj,
        "adr",
        2,
        "Metered billing",
        _adr(2, "Metered billing", "accepted", supersedes="ADR-00000000000000000000000099"),
    )
    return proj


def scenario_superseded_by_without_status(tmp_path):
    """
    ADR-00000000000000000000000001 has superseded-by field but status is still "accepted".
    Inconsistent — field says superseded, status disagrees.

    ADR-00000000000000000000000001 (accepted)  superseded-by: ADR-00000000000000000000000002  <-- inconsistent!
    ADR-00000000000000000000000002 (accepted)

    Expected: FAIL — status/field mismatch
    Note: Current Pydantic model may NOT catch this since status_field_requirements
    only checks that superseded status REQUIRES the field, not the reverse.
    This scenario documents that the reverse check is also desired.
    """
    proj = scaffold_project(tmp_path)
    # Must build manually — the Pydantic model might reject this at parse time
    content = (
        "---\n"
        "id: ADR-00000000000000000000000001\n"
        "status: accepted\n"
        "date: 2026-04-01\n"
        "superseded-by: ADR-00000000000000000000000002\n"
        "---\n"
        "\n"
        "# ADR-00000000000000000000000001 Per-seat billing\n"
        "\n"
        "## Context and Problem Statement\n\nContext.\n"
        "\n## Considered Options\n\n- A\n"
        "\n## Decision Outcome\n\nChosen option: A.\n"
    )
    write_doc(proj, "adr", 1, "Per-seat billing", content)
    write_doc(proj, "adr", 2, "Metered billing", _adr(2, "Metered billing", "accepted"))
    return proj


def scenario_mixed_errors_in_one_document(tmp_path):
    """
    SPEC-00000000000000000000000001 has both a dangling reference AND a stale reference.
    Linter must report both without short-circuiting.

    ADR-00000000000000000000000001 (rejected)
    SPEC-00000000000000000000000001 (draft)  refs: [ADR-00000000000000000000000099, ADR-00000000000000000000000001]
                             ^^^^^^^^  ^^^^^^^^
                             DANGLING  STALE (rejected)

    Expected: FAIL — 2 errors (one dangling, one stale)
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "adr", 1, "Auth via JWT", _adr(1, "Auth via JWT", "rejected"))
    write_doc(
        proj,
        "spec",
        1,
        "JWT Token API",
        _spec(
            1, "JWT Token API", "draft", references=["ADR-00000000000000000000000099", "ADR-00000000000000000000000001"]
        ),
    )
    return proj


def scenario_dead_to_dead_reference(tmp_path):
    """
    A superseded ADR references a rejected ADR. Both are dead.
    We still flag it — the reference is stale regardless of who's looking.

    ADR-00000000000000000000000001 (rejected)
      ^
      |
    ADR-00000000000000000000000002 (superseded)
      refs: [ADR-00000000000000000000000001]
      superseded-by: ADR-00000000000000000000000003
                                  ^^^^^^^^ STALE (ADR-00000000000000000000000001 is rejected)
    ADR-00000000000000000000000003 (accepted)    supersedes: ADR-00000000000000000000000002

    Expected: FAIL — dead-to-dead references are still flagged.
    Rationale: if someone un-supersedes ADR-00000000000000000000000002, the stale ref to ADR-00000000000000000000000001
    should already be visible, not hidden.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "adr", 1, "Auth via JWT", _adr(1, "Auth via JWT", "rejected"))
    write_doc(
        proj,
        "adr",
        2,
        "Auth via OAuth2",
        _adr(
            2,
            "Auth via OAuth2",
            "superseded",
            references=["ADR-00000000000000000000000001"],
            superseded_by="ADR-00000000000000000000000003",
        ),
    )
    write_doc(
        proj,
        "adr",
        3,
        "Auth via Passkeys",
        _adr(3, "Auth via Passkeys", "accepted", supersedes="ADR-00000000000000000000000002"),
    )
    return proj


# ── Two-phase scenarios ──────────────────────────────────────


def scenario_supersede_then_cascade(tmp_path):
    """
    Phase 1: ADR-00000000000000000000000001 superseded, SPEC-00000000000000000000000001 still references it.

    ADR-00000000000000000000000001 (superseded)  superseded-by: ADR-00000000000000000000000002
    ADR-00000000000000000000000002 (accepted)    supersedes: ADR-00000000000000000000000001
    SPEC-00000000000000000000000001 (approved)
      refs: [PRD-00000000000000000000000001, ADR-00000000000000000000000001]   <-- STALE

    Expected: FAIL
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "Team Billing", _prd(1, "Team Billing", "approved"))
    write_doc(
        proj,
        "adr",
        1,
        "Per-seat billing",
        _adr(
            1,
            "Per-seat billing",
            "superseded",
            references=["PRD-00000000000000000000000001"],
            superseded_by="ADR-00000000000000000000000002",
        ),
    )
    write_doc(
        proj,
        "adr",
        2,
        "Metered billing",
        _adr(
            2,
            "Metered billing",
            "accepted",
            references=["PRD-00000000000000000000000001"],
            supersedes="ADR-00000000000000000000000001",
        ),
    )
    write_doc(
        proj,
        "spec",
        1,
        "Billing API",
        _spec(
            1,
            "Billing API",
            "approved",
            references=["PRD-00000000000000000000000001", "ADR-00000000000000000000000001"],
        ),
    )
    return proj


def scenario_supersede_cascade_fixed(tmp_path):
    """Phase 2: SPEC-00000000000000000000000001 updated to reference ADR-00000000000000000000000002. Expected: PASS."""
    proj = scenario_supersede_then_cascade(tmp_path)
    write_doc(
        proj,
        "spec",
        1,
        "Billing API",
        _spec(
            1,
            "Billing API",
            "approved",
            references=["PRD-00000000000000000000000001", "ADR-00000000000000000000000002"],
        ),
    )
    return proj
