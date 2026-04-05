"""
Real-world scenario fixtures for madr-tools smoke tests.

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

    PRD-001  "Team Billing"  (approved)
      ^       ^       ^
      |       |       |
    ADR-0001  ADR-0002          ADR-0003
    "Stripe"  "Per-seat"        "Metered billing"
    (accepted) (superseded)----->(accepted)
      ^    ^                       ^
      |    |                       |
      |  SPEC-001 "Billing API"  (approved)
      |    refs: [PRD-001, ADR-0001, ADR-0003]
      |
    SPEC-002 "Stripe Webhooks"  (draft)
      refs: [ADR-0001, SPEC-001]
"""

# ── TOML config shared across all scenarios ──────────────────
#
# warn_on_reference: statuses that are "dead" — referencing them is a problem.
# This is DIFFERENT from terminal statuses (no transitions).
# "implemented" is terminal but healthy. "rejected" is terminal and dead.

MULTI_TYPE_CONFIG = """\
[project]
name = "saas-app"

[tool.doc.types.adr]
dir = "docs/adr"
prefix = "ADR"
digits = 4
initial_status = "proposed"
statuses = ["proposed", "accepted", "rejected", "deprecated", "superseded"]
warn_on_reference = ["rejected", "deprecated", "superseded"]
required_sections = ["Context and Problem Statement", "Considered Options", "Decision Outcome"]

[tool.doc.types.adr.transitions]
proposed = ["accepted", "rejected"]
accepted = ["deprecated", "superseded"]
rejected = []
deprecated = []
superseded = []

[tool.doc.types.adr.actions]
accept = "accepted"
reject = "rejected"
deprecate = "deprecated"
supersede = "superseded"

[tool.doc.types.adr.status_field_requirements]
superseded = ["superseded-by"]

[tool.doc.types.prd]
dir = "docs/prd"
prefix = "PRD"
digits = 3
initial_status = "draft"
statuses = ["draft", "review", "approved", "implemented", "archived"]
warn_on_reference = ["archived"]
required_sections = ["Problem Statement", "Requirements", "Success Criteria"]

[tool.doc.types.prd.transitions]
draft = ["review"]
review = ["approved", "draft"]
approved = ["implemented", "archived"]
implemented = ["archived"]
archived = []

[tool.doc.types.prd.actions]
submit = "review"
approve = "approved"
implement = "implemented"
archive = "archived"

[tool.doc.types.spec]
dir = "docs/spec"
prefix = "SPEC"
digits = 3
initial_status = "draft"
statuses = ["draft", "review", "approved", "implemented"]
warn_on_reference = []
required_sections = ["Overview", "Technical Design", "Testing Strategy"]

[tool.doc.types.spec.transitions]
draft = ["review"]
review = ["approved", "draft"]
approved = ["implemented"]
implemented = []

[tool.doc.types.spec.actions]
submit = "review"
approve = "approved"
implement = "implemented"
"""


# ── Document content builders ────────────────────────────────

def _adr(number, title, status, references=None,
         supersedes=None, superseded_by=None):
    """Build an ADR markdown string."""
    fm_lines = ["---", f"status: {status}", "date: 2026-04-01"]
    if references:
        fm_lines.append(f"references: [{', '.join(references)}]")
    if supersedes:
        fm_lines.append(f"supersedes: {supersedes}")
    if superseded_by:
        fm_lines.append(f"superseded-by: {superseded_by}")
    fm_lines.append("---")
    body = f"""
# ADR-{number:04d} {title}

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
    fm_lines = ["---", f"status: {status}", "date: 2026-03-15"]
    if references:
        fm_lines.append(f"references: [{', '.join(references)}]")
    fm_lines.append("---")
    body = f"""
# PRD-{number:03d} {title}

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
    fm_lines = ["---", f"status: {status}", "date: 2026-04-03"]
    if references:
        fm_lines.append(f"references: [{', '.join(references)}]")
    fm_lines.append("---")
    body = f"""
# SPEC-{number:03d} {title}

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
    """Create the pyproject.toml and empty doc directories."""
    (tmp_path / "pyproject.toml").write_text(MULTI_TYPE_CONFIG)
    for d in ("docs/adr", "docs/prd", "docs/spec"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


def write_doc(tmp_path, doc_type, number, title, content):
    """Write a document file to the correct directory."""
    digits = 4 if doc_type == "adr" else 3
    slug = _slug(title)
    filename = f"{number:0{digits}d}-{slug}.md"
    path = tmp_path / f"docs/{doc_type}" / filename
    path.write_text(content)
    return path


# ══════════════════════════════════════════════════════════════
# PASSING scenarios — lint should report 0 errors
# ══════════════════════════════════════════════════════════════

def scenario_happy_path(tmp_path):
    """
    Everything aligned. All references valid. Lint passes clean.

    PRD-001 (approved)
      ^       ^       ^
      |       |       |
    ADR-0001 (accepted)   refs: [PRD-001]
    ADR-0002 (superseded) refs: [PRD-001], superseded-by: ADR-0003
    ADR-0003 (accepted)   refs: [PRD-001], supersedes: ADR-0002
      ^                     ^
      |                     |
    SPEC-001 (approved)   refs: [PRD-001, ADR-0001, ADR-0003]
      ^
      |
    SPEC-002 (draft)      refs: [ADR-0001, SPEC-001]

    Expected: PASS — ADR-0002 is superseded but nothing references it directly.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "Team Billing",
              _prd(1, "Team Billing", "approved"))
    write_doc(proj, "adr", 1, "Use Stripe",
              _adr(1, "Use Stripe", "accepted", references=["PRD-001"]))
    write_doc(proj, "adr", 2, "Per-seat billing",
              _adr(2, "Per-seat billing", "superseded",
                   references=["PRD-001"], superseded_by="ADR-0003"))
    write_doc(proj, "adr", 3, "Metered billing",
              _adr(3, "Metered billing", "accepted",
                   references=["PRD-001"], supersedes="ADR-0002"))
    write_doc(proj, "spec", 1, "Billing API",
              _spec(1, "Billing API", "approved",
                    references=["PRD-001", "ADR-0001", "ADR-0003"]))
    write_doc(proj, "spec", 2, "Stripe Webhooks",
              _spec(2, "Stripe Webhooks", "draft",
                    references=["ADR-0001", "SPEC-001"]))
    return proj


def scenario_shared_adr(tmp_path):
    """
    One ADR serves two PRDs. Shared infrastructure decision.

    PRD-001 (approved)   PRD-002 (approved)
      ^       ^             ^       ^
      |       |             |       |
      +---ADR-0001 (accepted)---+
          refs: [PRD-001, PRD-002]
          ^                 ^
          |                 |
        SPEC-001 (approved) SPEC-002 (draft)

    Expected: PASS — one ADR serving multiple PRDs is valid.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "Real-time Dashboard",
              _prd(1, "Real-time Dashboard", "approved"))
    write_doc(proj, "prd", 2, "Session Caching",
              _prd(2, "Session Caching", "approved"))
    write_doc(proj, "adr", 1, "Use Redis",
              _adr(1, "Use Redis", "accepted", references=["PRD-001", "PRD-002"]))
    write_doc(proj, "spec", 1, "Redis Setup",
              _spec(1, "Redis Setup", "approved",
                    references=["ADR-0001", "PRD-001"]))
    write_doc(proj, "spec", 2, "Cache Layer",
              _spec(2, "Cache Layer", "draft",
                    references=["ADR-0001", "PRD-002"]))
    return proj


def scenario_infra_no_prd(tmp_path):
    """
    Tech debt work. ADR without any PRD. Valid — not all decisions are product-driven.

    ADR-0001 (accepted)  "Migrate to PG16"  refs: []
      ^
      |
    SPEC-001 (draft)     "PG16 Runbook"     refs: [ADR-0001]

    Expected: PASS — no PRD required.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "adr", 1, "Migrate to PostgreSQL 16",
              _adr(1, "Migrate to PostgreSQL 16", "accepted"))
    write_doc(proj, "spec", 1, "PG16 Migration Runbook",
              _spec(1, "PG16 Migration Runbook", "draft",
                    references=["ADR-0001"]))
    return proj


def scenario_lateral_spec_references(tmp_path):
    """
    SPEC-002 extends SPEC-001 (same-type lateral reference).

    SPEC-001 (approved)  refs: [ADR-0001]
      ^
      |
    SPEC-002 (draft)     refs: [SPEC-001]

    Expected: PASS — same-type references are valid.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "Team Billing",
              _prd(1, "Team Billing", "approved"))
    write_doc(proj, "adr", 1, "Use Stripe",
              _adr(1, "Use Stripe", "accepted", references=["PRD-001"]))
    write_doc(proj, "spec", 1, "Core Billing API",
              _spec(1, "Core Billing API", "approved",
                    references=["ADR-0001"]))
    write_doc(proj, "spec", 2, "Billing Webhooks",
              _spec(2, "Billing Webhooks", "draft",
                    references=["SPEC-001"]))
    return proj


def scenario_reference_implemented_spec(tmp_path):
    """
    SPEC-002 references SPEC-001 which is "implemented" (terminal but healthy).

    SPEC-001 (implemented)  refs: [ADR-0001]  <-- terminal status, but NOT dead
      ^
      |
    SPEC-002 (draft)        refs: [SPEC-001]  <-- should be valid!

    Expected: PASS — "implemented" is not in warn_on_reference for SPEC.
    This is the critical test that distinguishes terminal from dead.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "adr", 1, "Use Stripe",
              _adr(1, "Use Stripe", "accepted"))
    write_doc(proj, "spec", 1, "Billing API",
              _spec(1, "Billing API", "implemented",
                    references=["ADR-0001"]))
    write_doc(proj, "spec", 2, "Billing Webhooks",
              _spec(2, "Billing Webhooks", "draft",
                    references=["SPEC-001"]))
    return proj


def scenario_circular_spec_references(tmp_path):
    """
    Two SPECs that co-depend. Common in real projects (e.g., Auth API and
    Session Management that reference each other).

    SPEC-001 (approved)  refs: [SPEC-002]
      ^                          |
      |                          v
    SPEC-002 (approved)  refs: [SPEC-001]

    Expected: PASS — circular references are allowed.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "spec", 1, "Auth API",
              _spec(1, "Auth API", "approved",
                    references=["SPEC-002"]))
    write_doc(proj, "spec", 2, "Session Management",
              _spec(2, "Session Management", "approved",
                    references=["SPEC-001"]))
    return proj


def scenario_spec_before_adr_accepted(tmp_path):
    """
    SPEC written speculatively before ADR is formally accepted.
    "proposed" is not a dead status — this is valid permissive behavior.

    ADR-0001 (proposed)   <-- NOT yet accepted
      ^
      |
    SPEC-001 (draft)      refs: [ADR-0001]

    Expected: PASS — "proposed" is not in warn_on_reference.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "adr", 1, "Auth via JWT",
              _adr(1, "Auth via JWT", "proposed"))
    write_doc(proj, "spec", 1, "JWT Token API",
              _spec(1, "JWT Token API", "draft",
                    references=["ADR-0001"]))
    return proj


def scenario_reverse_reference(tmp_path):
    """
    ADR references a SPEC (reverse direction). "See also" link.
    Reference direction is convention, not enforced.

    ADR-0001 (accepted)   refs: [SPEC-001]   <-- "backwards" but valid
    SPEC-001 (approved)   refs: [ADR-0001]

    Expected: PASS — direction is not enforced.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "adr", 1, "Use Stripe",
              _adr(1, "Use Stripe", "accepted", references=["SPEC-001"]))
    write_doc(proj, "spec", 1, "Stripe Integration",
              _spec(1, "Stripe Integration", "approved",
                    references=["ADR-0001"]))
    return proj


def scenario_competing_adrs(tmp_path):
    """
    Multiple proposed ADRs for the same problem. Common during design phase.

    PRD-001 (approved)
      ^       ^       ^
      |       |       |
    ADR-0001 (proposed)  "JWT"     refs: [PRD-001]
    ADR-0002 (proposed)  "OAuth2"  refs: [PRD-001]
    ADR-0003 (proposed)  "SAML"    refs: [PRD-001]

    Expected: PASS — multiple proposed ADRs is valid workflow.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "User Auth",
              _prd(1, "User Auth", "approved"))
    write_doc(proj, "adr", 1, "Auth via JWT",
              _adr(1, "Auth via JWT", "proposed", references=["PRD-001"]))
    write_doc(proj, "adr", 2, "Auth via OAuth2",
              _adr(2, "Auth via OAuth2", "proposed", references=["PRD-001"]))
    write_doc(proj, "adr", 3, "Auth via SAML",
              _adr(3, "Auth via SAML", "proposed", references=["PRD-001"]))
    return proj


def scenario_prd_references_prd(tmp_path):
    """
    PRD-002 extends PRD-001 (lateral PRD reference for enterprise tier).

    PRD-001 (approved)  "Team Billing"
      ^
      |
    PRD-002 (approved)  "Enterprise Billing"  refs: [PRD-001]

    Expected: PASS — PRD-to-PRD references are valid.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "Team Billing",
              _prd(1, "Team Billing", "approved"))
    write_doc(proj, "prd", 2, "Enterprise Billing",
              _prd(2, "Enterprise Billing", "approved", references=["PRD-001"]))
    return proj


def scenario_explicit_empty_references(tmp_path):
    """
    Document with explicit `references: []` in frontmatter.
    Different from omitting the field entirely. Should be treated the same.

    ADR-0001 (accepted)  references: []  <-- explicit empty list

    Expected: PASS — empty references list is valid, same as absent field.
    """
    proj = scaffold_project(tmp_path)
    # Build manually to emit `references: []` (the builder skips falsy references)
    content = (
        "---\n"
        "status: accepted\n"
        "date: 2026-04-01\n"
        "references: []\n"
        "---\n"
        "\n"
        "# ADR-0001 Use Stripe\n"
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

    PRD-001 (approved)
      ^
      |
    ADR-0001 (superseded)   superseded-by: ADR-0002
    ADR-0002 (accepted)     supersedes: ADR-0001
      ^
      |
    SPEC-001 (approved)     refs: [ADR-0001]   <-- STALE (direct ref to superseded)
      ^
      |
    SPEC-002 (approved)     refs: [SPEC-001]   <-- NOT stale (SPEC-001 is approved)
      ^
      |
    SPEC-003 (draft)        refs: [SPEC-002]   <-- NOT stale (SPEC-002 is approved)

    Expected: FAIL — but only 1 error (SPEC-001 -> ADR-0001).
    SPEC-002 and SPEC-003 are NOT flagged because staleness is direct-only.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "Team Billing",
              _prd(1, "Team Billing", "approved"))
    write_doc(proj, "adr", 1, "Per-seat billing",
              _adr(1, "Per-seat billing", "superseded",
                   references=["PRD-001"], superseded_by="ADR-0002"))
    write_doc(proj, "adr", 2, "Metered billing",
              _adr(2, "Metered billing", "accepted",
                   references=["PRD-001"], supersedes="ADR-0001"))
    write_doc(proj, "spec", 1, "Billing Core",
              _spec(1, "Billing Core", "approved",
                    references=["ADR-0001"]))
    write_doc(proj, "spec", 2, "Billing Extensions",
              _spec(2, "Billing Extensions", "approved",
                    references=["SPEC-001"]))
    write_doc(proj, "spec", 3, "Billing Webhooks",
              _spec(3, "Billing Webhooks", "draft",
                    references=["SPEC-002"]))
    return proj


# ══════════════════════════════════════════════════════════════
# FAILING scenarios — lint should report errors
# ══════════════════════════════════════════════════════════════

def scenario_stale_spec(tmp_path):
    """
    SPEC-001 references ADR-0002 which was superseded.

    SPEC-001 (approved)  refs: [PRD-001, ADR-0001, ADR-0002]
                                                    ^^^^^^^^
                                STALE! ADR-0002 is superseded.

    Expected: FAIL — 1 error: SPEC-001 references ADR-0002 (superseded)
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "Team Billing",
              _prd(1, "Team Billing", "approved"))
    write_doc(proj, "adr", 1, "Use Stripe",
              _adr(1, "Use Stripe", "accepted", references=["PRD-001"]))
    write_doc(proj, "adr", 2, "Per-seat billing",
              _adr(2, "Per-seat billing", "superseded",
                   references=["PRD-001"], superseded_by="ADR-0003"))
    write_doc(proj, "adr", 3, "Metered billing",
              _adr(3, "Metered billing", "accepted",
                   references=["PRD-001"], supersedes="ADR-0002"))
    write_doc(proj, "spec", 1, "Billing API",
              _spec(1, "Billing API", "approved",
                    references=["PRD-001", "ADR-0001", "ADR-0002"]))
    return proj


def scenario_rejected_adr_orphaned_spec(tmp_path):
    """
    SPEC building on a rejected ADR.

    ADR-0001 (rejected)   refs: [PRD-001]
      ^
      |
    SPEC-001 (draft)      refs: [ADR-0001]   <-- STALE

    Expected: FAIL — SPEC-001 references ADR-0001 (rejected)
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "User Auth",
              _prd(1, "User Auth", "approved"))
    write_doc(proj, "adr", 1, "Auth via JWT",
              _adr(1, "Auth via JWT", "rejected", references=["PRD-001"]))
    write_doc(proj, "spec", 1, "JWT Token API",
              _spec(1, "JWT Token API", "draft", references=["ADR-0001"]))
    return proj


def scenario_archived_prd_cascade(tmp_path):
    """
    Business killed the feature. PRD archived. All downstream references are stale.

    PRD-001 (archived)
      ^       ^       ^
      |       |       |
    ADR-0001 refs:[PRD-001]  ADR-0002 refs:[PRD-001]  SPEC-001 refs:[PRD-001, ADR-0001]

    Expected: FAIL — 3 errors (ADR-0001, ADR-0002, SPEC-001 all reference archived PRD)
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "Team Billing",
              _prd(1, "Team Billing", "archived"))
    write_doc(proj, "adr", 1, "Use Stripe",
              _adr(1, "Use Stripe", "accepted", references=["PRD-001"]))
    write_doc(proj, "adr", 2, "Metered billing",
              _adr(2, "Metered billing", "accepted", references=["PRD-001"]))
    write_doc(proj, "spec", 1, "Billing API",
              _spec(1, "Billing API", "approved",
                    references=["PRD-001", "ADR-0001"]))
    return proj


def scenario_dangling_reference(tmp_path):
    """
    SPEC references an ADR that doesn't exist. Typo or deleted file.

    SPEC-001 (draft)  refs: [ADR-0001, ADR-0099]
                                        ^^^^^^^^ DANGLING

    Expected: FAIL — ADR-0099 does not exist
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "Team Billing",
              _prd(1, "Team Billing", "approved"))
    write_doc(proj, "adr", 1, "Use Stripe",
              _adr(1, "Use Stripe", "accepted", references=["PRD-001"]))
    write_doc(proj, "spec", 1, "Billing API",
              _spec(1, "Billing API", "draft",
                    references=["ADR-0001", "ADR-0099"]))
    return proj


def scenario_adr_dangling_to_prd(tmp_path):
    """
    ADR references a PRD that doesn't exist. Different code path from SPEC->ADR dangling.

    ADR-0001 (accepted)  refs: [PRD-099]
                                ^^^^^^^ DANGLING

    Expected: FAIL — PRD-099 does not exist
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "adr", 1, "Use Stripe",
              _adr(1, "Use Stripe", "accepted", references=["PRD-099"]))
    return proj


def scenario_self_reference(tmp_path):
    """
    Document references itself. Almost certainly a copy-paste mistake.

    SPEC-001 (draft)  refs: [SPEC-001]
                             ^^^^^^^^ SELF-REFERENCE

    Expected: FAIL — self-reference detected
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "spec", 1, "Billing API",
              _spec(1, "Billing API", "draft",
                    references=["SPEC-001"]))
    return proj


def scenario_broken_supersede_symmetry(tmp_path):
    """
    ADR-0001 claims superseded-by ADR-0002, but ADR-0002 is missing the
    supersedes field. Broken symmetry.

    ADR-0001 (superseded)  superseded-by: ADR-0002
    ADR-0002 (accepted)    supersedes: <MISSING>

    Expected: FAIL — asymmetric supersede chain
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "adr", 1, "Per-seat billing",
              _adr(1, "Per-seat billing", "superseded",
                   superseded_by="ADR-0002"))
    write_doc(proj, "adr", 2, "Metered billing",
              _adr(2, "Metered billing", "accepted"))
    # Note: ADR-0002 does NOT have supersedes: ADR-0001
    return proj


def scenario_duplicate_ids(tmp_path):
    """
    Two files in the same directory map to the same ID. Bad merge or manual error.

    docs/adr/0001-use-redis.md       -> ADR-0001
    docs/adr/0001-use-memcached.md   -> ADR-0001 (collision!)

    Expected: FAIL — duplicate ID detected
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "adr", 1, "Use Redis",
              _adr(1, "Use Redis", "accepted"))
    # Write a second file that also maps to ADR-0001
    slug2 = "use-memcached"
    path2 = proj / "docs" / "adr" / f"0001-{slug2}.md"
    path2.write_text(_adr(1, "Use Memcached", "accepted"))
    return proj


def scenario_dangling_supersede_target(tmp_path):
    """
    ADR-0001 claims superseded-by ADR-0099, but ADR-0099 doesn't exist at all.
    Different from broken symmetry — the target file is completely absent.

    ADR-0001 (superseded)  superseded-by: ADR-0099  <-- DANGLING! file doesn't exist.

    Expected: FAIL — dangling supersede reference
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "adr", 1, "Per-seat billing",
              _adr(1, "Per-seat billing", "superseded",
                   superseded_by="ADR-0099"))
    return proj


def scenario_deprecated_adr_no_replacement(tmp_path):
    """
    ADR deprecated (tech is EOL). Unlike superseded, there's no replacement.
    Error message should reflect this.

    ADR-0001 (deprecated)   <-- no superseded-by, just deprecated
      ^
      |
    SPEC-001 (approved)     refs: [ADR-0001]   <-- STALE

    Expected: FAIL — ADR-0001 is deprecated (different from superseded)
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "adr", 1, "Use Legacy API",
              _adr(1, "Use Legacy API", "deprecated"))
    write_doc(proj, "spec", 1, "Legacy Integration",
              _spec(1, "Legacy Integration", "approved",
                    references=["ADR-0001"]))
    return proj


def scenario_unknown_prefix_reference(tmp_path):
    """
    SPEC references an ID with a prefix that is not a configured document type.

    SPEC-001 (draft)  refs: [RFC-001]
                             ^^^^^^^ RFC is not a configured type.

    Expected: FAIL — RFC-001 does not match any known type, treated as dangling.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "spec", 1, "Billing API",
              _spec(1, "Billing API", "draft",
                    references=["RFC-001"]))
    return proj


def scenario_malformed_reference_id(tmp_path):
    """
    References field contains IDs with wrong format.

    SPEC-001 (draft)  refs: [ADR-1, adr-0001]
                             ^^^^^  ^^^^^^^^
                         Wrong digits  Lowercase prefix

    Expected: FAIL — malformed IDs should be flagged (dangling or format error).
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "adr", 1, "Use Stripe",
              _adr(1, "Use Stripe", "accepted"))
    write_doc(proj, "spec", 1, "Billing API",
              _spec(1, "Billing API", "draft",
                    references=["ADR-1", "adr-0001"]))
    return proj


def scenario_prd_split(tmp_path):
    """
    PRD-001 was too broad, gets archived. Split into PRD-002 and PRD-003.
    Downstream ADR still references the archived parent.

    PRD-001 (archived)                  <-- split, archived
      ^       ^       ^
      |       |       |
    PRD-002 refs:[PRD-001] (approved)   <-- lineage trace (to archived = stale)
    PRD-003 refs:[PRD-001] (approved)   <-- lineage trace (to archived = stale)
    ADR-0001 refs:[PRD-001] (accepted)  <-- STALE, should ref PRD-002 or PRD-003

    Expected: FAIL — 3 errors (PRD-002, PRD-003, ADR-0001 all ref archived PRD-001)
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "Billing",
              _prd(1, "Billing", "archived"))
    write_doc(proj, "prd", 2, "Team Billing",
              _prd(2, "Team Billing", "approved", references=["PRD-001"]))
    write_doc(proj, "prd", 3, "Enterprise Billing",
              _prd(3, "Enterprise Billing", "approved", references=["PRD-001"]))
    write_doc(proj, "adr", 1, "Use Stripe",
              _adr(1, "Use Stripe", "accepted", references=["PRD-001"]))
    return proj


def scenario_dangling_supersedes_field(tmp_path):
    """
    ADR-0002 claims supersedes ADR-0099, but ADR-0099 doesn't exist.
    Reverse direction of scenario_dangling_supersede_target.

    ADR-0002 (accepted)  supersedes: ADR-0099  <-- DANGLING

    Expected: FAIL — referenced ADR does not exist
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "adr", 2, "Metered billing",
              _adr(2, "Metered billing", "accepted",
                   supersedes="ADR-0099"))
    return proj


def scenario_superseded_by_without_status(tmp_path):
    """
    ADR-0001 has superseded-by field but status is still "accepted".
    Inconsistent — field says superseded, status disagrees.

    ADR-0001 (accepted)  superseded-by: ADR-0002  <-- inconsistent!
    ADR-0002 (accepted)

    Expected: FAIL — status/field mismatch
    Note: Current Pydantic model may NOT catch this since status_field_requirements
    only checks that superseded status REQUIRES the field, not the reverse.
    This scenario documents that the reverse check is also desired.
    """
    proj = scaffold_project(tmp_path)
    # Must build manually — the Pydantic model might reject this at parse time
    content = (
        "---\n"
        "status: accepted\n"
        "date: 2026-04-01\n"
        "superseded-by: ADR-0002\n"
        "---\n"
        "\n"
        "# ADR-0001 Per-seat billing\n"
        "\n"
        "## Context and Problem Statement\n\nContext.\n"
        "\n## Considered Options\n\n- A\n"
        "\n## Decision Outcome\n\nChosen option: A.\n"
    )
    write_doc(proj, "adr", 1, "Per-seat billing", content)
    write_doc(proj, "adr", 2, "Metered billing",
              _adr(2, "Metered billing", "accepted"))
    return proj


def scenario_mixed_errors_in_one_document(tmp_path):
    """
    SPEC-001 has both a dangling reference AND a stale reference.
    Linter must report both without short-circuiting.

    ADR-0001 (rejected)
    SPEC-001 (draft)  refs: [ADR-0099, ADR-0001]
                             ^^^^^^^^  ^^^^^^^^
                             DANGLING  STALE (rejected)

    Expected: FAIL — 2 errors (one dangling, one stale)
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "adr", 1, "Auth via JWT",
              _adr(1, "Auth via JWT", "rejected"))
    write_doc(proj, "spec", 1, "JWT Token API",
              _spec(1, "JWT Token API", "draft",
                    references=["ADR-0099", "ADR-0001"]))
    return proj


def scenario_dead_to_dead_reference(tmp_path):
    """
    A superseded ADR references a rejected ADR. Both are dead.
    We still flag it — the reference is stale regardless of who's looking.

    ADR-0001 (rejected)
      ^
      |
    ADR-0002 (superseded)  refs: [ADR-0001]   superseded-by: ADR-0003
                                  ^^^^^^^^ STALE (ADR-0001 is rejected)
    ADR-0003 (accepted)    supersedes: ADR-0002

    Expected: FAIL — dead-to-dead references are still flagged.
    Rationale: if someone un-supersedes ADR-0002, the stale ref to ADR-0001
    should already be visible, not hidden.
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "adr", 1, "Auth via JWT",
              _adr(1, "Auth via JWT", "rejected"))
    write_doc(proj, "adr", 2, "Auth via OAuth2",
              _adr(2, "Auth via OAuth2", "superseded",
                   references=["ADR-0001"], superseded_by="ADR-0003"))
    write_doc(proj, "adr", 3, "Auth via Passkeys",
              _adr(3, "Auth via Passkeys", "accepted",
                   supersedes="ADR-0002"))
    return proj


# ── Two-phase scenarios ──────────────────────────────────────

def scenario_supersede_then_cascade(tmp_path):
    """
    Phase 1: ADR-0001 superseded, SPEC-001 still references it.

    ADR-0001 (superseded)  superseded-by: ADR-0002
    ADR-0002 (accepted)    supersedes: ADR-0001
    SPEC-001 (approved)    refs: [PRD-001, ADR-0001]   <-- STALE

    Expected: FAIL
    """
    proj = scaffold_project(tmp_path)
    write_doc(proj, "prd", 1, "Team Billing",
              _prd(1, "Team Billing", "approved"))
    write_doc(proj, "adr", 1, "Per-seat billing",
              _adr(1, "Per-seat billing", "superseded",
                   references=["PRD-001"], superseded_by="ADR-0002"))
    write_doc(proj, "adr", 2, "Metered billing",
              _adr(2, "Metered billing", "accepted",
                   references=["PRD-001"], supersedes="ADR-0001"))
    write_doc(proj, "spec", 1, "Billing API",
              _spec(1, "Billing API", "approved",
                    references=["PRD-001", "ADR-0001"]))
    return proj


def scenario_supersede_cascade_fixed(tmp_path):
    """Phase 2: SPEC-001 updated to reference ADR-0002. Expected: PASS."""
    proj = scenario_supersede_then_cascade(tmp_path)
    write_doc(proj, "spec", 1, "Billing API",
              _spec(1, "Billing API", "approved",
                    references=["PRD-001", "ADR-0002"]))
    return proj
