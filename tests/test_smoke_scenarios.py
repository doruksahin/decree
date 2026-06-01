"""
Smoke tests for real-world document lifecycle scenarios.

These tests define the behavioral contract for multi-type document management.
They are written BEFORE the implementation — they will fail until the
multi-doctype plan is complete.

Design decisions encoded here:
    - warn_on_reference (dead statuses) != terminal_statuses
    - Circular references: ALLOWED
    - Reference direction: NOT ENFORCED
    - Staleness propagation: DIRECT ONLY (not transitive)
    - Self-references: FLAGGED as errors
    - Duplicate IDs: FLAGGED as errors
"""

from tests.scenarios import (
    scenario_adr_dangling_to_prd,
    scenario_archived_prd_cascade,
    scenario_broken_supersede_symmetry,
    scenario_circular_spec_references,
    scenario_competing_adrs,
    scenario_dangling_reference,
    scenario_dangling_supersede_target,
    scenario_dangling_supersedes_field,
    scenario_dead_to_dead_reference,
    scenario_deep_chain_no_transitive_staleness,
    scenario_deprecated_adr_no_replacement,
    scenario_duplicate_ids,
    scenario_empty_project,
    scenario_explicit_empty_references,
    scenario_happy_path,
    scenario_infra_no_prd,
    scenario_lateral_spec_references,
    scenario_malformed_reference_id,
    scenario_mixed_errors_in_one_document,
    scenario_prd_references_prd,
    scenario_prd_split,
    scenario_reference_implemented_spec,
    scenario_rejected_adr_orphaned_spec,
    scenario_reverse_reference,
    scenario_self_reference,
    scenario_shared_adr,
    scenario_spec_before_adr_accepted,
    scenario_stale_spec,
    scenario_supersede_cascade_fixed,
    scenario_supersede_then_cascade,
    scenario_superseded_by_without_status,
    scenario_unknown_prefix_reference,
)

# ── Helpers ──────────────────────────────────────────────────


def lint_project(proj_path, monkeypatch):
    """Run lint on a scenario project. Returns (exit_code, error_lines)."""
    monkeypatch.chdir(proj_path)
    import io
    import sys

    from decree.commands.lint import run

    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        exit_code = run(None)
    finally:
        sys.stdout = old_stdout

    errors = [line for line in captured.getvalue().strip().splitlines() if line]
    return exit_code, errors


def collect_all_docs(proj_path, monkeypatch):
    """Load all documents across all types. Returns list of DocDocuments."""
    monkeypatch.chdir(proj_path)
    from decree.parser import load_all_types

    return load_all_types()


# ══════════════════════════════════════════════════════════════
# PASSING scenarios
# ══════════════════════════════════════════════════════════════


class TestHappyPath:
    """All references valid, all statuses healthy. 6 docs, 3 types."""

    def test_lint_passes_clean(self, tmp_path, monkeypatch):
        proj = scenario_happy_path(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 0, f"Expected clean lint, got errors: {errors}"

    def test_all_documents_loaded(self, tmp_path, monkeypatch):
        proj = scenario_happy_path(tmp_path)
        docs = collect_all_docs(proj, monkeypatch)
        ids = {d.doc_id for d in docs}
        assert ids == {
            "PRD-00000000000000000000000001",
            "ADR-00000000000000000000000001",
            "ADR-00000000000000000000000002",
            "ADR-00000000000000000000000003",
            "SPEC-00000000000000000000000001",
            "SPEC-00000000000000000000000002",
        }

    def test_supersede_chain_is_symmetric(self, tmp_path, monkeypatch):
        proj = scenario_happy_path(tmp_path)
        docs = collect_all_docs(proj, monkeypatch)
        by_id = {d.doc_id: d for d in docs}
        assert by_id["ADR-00000000000000000000000002"].meta.superseded_by == "ADR-00000000000000000000000003"
        assert by_id["ADR-00000000000000000000000003"].meta.supersedes == "ADR-00000000000000000000000002"

    def test_spec_references_are_all_healthy(self, tmp_path, monkeypatch):
        """SPEC-00000000000000000000000001 references only docs NOT in their type's warn_on_reference."""
        proj = scenario_happy_path(tmp_path)
        docs = collect_all_docs(proj, monkeypatch)
        by_id = {d.doc_id: d for d in docs}
        spec = by_id["SPEC-00000000000000000000000001"]
        for ref_id in spec.meta.references:
            target = by_id[ref_id]
            dead_statuses = target.doc_type.warn_on_reference
            assert target.meta.status not in dead_statuses, (
                f"SPEC-00000000000000000000000001 references {ref_id} which is {target.meta.status} "
                f"(in warn_on_reference for {target.doc_type.name})"
            )


class TestSharedAdr:
    """One ADR serving two PRDs — valid fan-out."""

    def test_lint_passes(self, tmp_path, monkeypatch):
        proj = scenario_shared_adr(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 0, f"Shared ADR should be valid, got: {errors}"

    def test_adr_references_both_prds(self, tmp_path, monkeypatch):
        proj = scenario_shared_adr(tmp_path)
        docs = collect_all_docs(proj, monkeypatch)
        adr = next(d for d in docs if d.doc_id == "ADR-00000000000000000000000001")
        assert set(adr.meta.references) == {"PRD-00000000000000000000000001", "PRD-00000000000000000000000002"}


class TestInfraNoPrd:
    """ADR + SPEC without any PRD. Pure tech debt."""

    def test_lint_passes(self, tmp_path, monkeypatch):
        proj = scenario_infra_no_prd(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 0, f"Infra without PRD should be valid, got: {errors}"

    def test_no_prds_exist(self, tmp_path, monkeypatch):
        proj = scenario_infra_no_prd(tmp_path)
        docs = collect_all_docs(proj, monkeypatch)
        assert not [d for d in docs if d.doc_id.startswith("PRD")]


class TestLateralReferences:
    """SPEC-00000000000000000000000002 extends SPEC-00000000000000000000000001 — same-type lateral reference."""

    def test_lint_passes(self, tmp_path, monkeypatch):
        proj = scenario_lateral_spec_references(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 0, f"Lateral spec refs should be valid, got: {errors}"


class TestReferenceImplementedSpec:
    """
    CRITICAL: "implemented" is terminal but NOT dead.
    This test distinguishes terminal_statuses from warn_on_reference.
    """

    def test_lint_passes(self, tmp_path, monkeypatch):
        """Referencing an implemented SPEC must NOT be flagged."""
        proj = scenario_reference_implemented_spec(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 0, f"Implemented SPEC is healthy to reference, got errors: {errors}"


class TestCircularReferences:
    """Two co-dependent SPECs referencing each other."""

    def test_lint_passes(self, tmp_path, monkeypatch):
        proj = scenario_circular_spec_references(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 0, f"Circular references should be allowed, got: {errors}"


class TestSpecBeforeAdrAccepted:
    """SPEC written before ADR is accepted. Permissive — "proposed" is not dead."""

    def test_lint_passes(self, tmp_path, monkeypatch):
        proj = scenario_spec_before_adr_accepted(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 0, f"Referencing proposed ADR should be valid, got: {errors}"


class TestReverseReference:
    """ADR references SPEC (backwards). Direction is not enforced."""

    def test_lint_passes(self, tmp_path, monkeypatch):
        proj = scenario_reverse_reference(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 0, f"Reverse direction refs should be valid, got: {errors}"


class TestCompetingAdrs:
    """Three proposed ADRs for the same problem. Valid design workflow."""

    def test_lint_passes(self, tmp_path, monkeypatch):
        proj = scenario_competing_adrs(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 0, f"Multiple proposed ADRs should be valid, got: {errors}"


class TestPrdReferencesPrd:
    """PRD-00000000000000000000000002 extends PRD-00000000000000000000000001. Lateral PRD-to-PRD reference."""

    def test_lint_passes(self, tmp_path, monkeypatch):
        proj = scenario_prd_references_prd(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 0, f"PRD-to-PRD references should be valid, got: {errors}"


class TestExplicitEmptyReferences:
    """Document with `references: []`. Same as absent — should not crash or warn."""

    def test_lint_passes(self, tmp_path, monkeypatch):
        proj = scenario_explicit_empty_references(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 0, f"Explicit empty references should be valid, got: {errors}"


class TestEmptyProject:
    """No documents at all. First-run experience."""

    def test_lint_passes(self, tmp_path, monkeypatch):
        proj = scenario_empty_project(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 0, f"Empty project should lint clean, got: {errors}"


# ══════════════════════════════════════════════════════════════
# FAILING scenarios
# ══════════════════════════════════════════════════════════════


class TestStaleSpec:
    """SPEC references superseded ADR."""

    def test_lint_catches_stale_reference(self, tmp_path, monkeypatch):
        proj = scenario_stale_spec(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 1
        assert any("ADR-00000000000000000000000002" in e and "superseded" in e for e in errors), (
            f"Expected stale ref error for ADR-00000000000000000000000002, got: {errors}"
        )

    def test_error_identifies_referencing_doc(self, tmp_path, monkeypatch):
        proj = scenario_stale_spec(tmp_path)
        _, errors = lint_project(proj, monkeypatch)
        assert any("SPEC-00000000000000000000000001" in e for e in errors), (
            f"Expected SPEC-00000000000000000000000001 in error, got: {errors}"
        )


class TestRejectedAdrOrphanedSpec:
    """SPEC building on a rejected ADR. Exactly 1 cross-type error."""

    def test_lint_catches_rejected_reference(self, tmp_path, monkeypatch):
        proj = scenario_rejected_adr_orphaned_spec(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 1
        cross_errors = [e for e in errors if "rejected" in e]
        assert len(cross_errors) == 1, f"Expected exactly 1 rejected-ref error, got: {cross_errors}"
        assert "ADR-00000000000000000000000001" in cross_errors[0]


class TestArchivedPrdCascade:
    """Archived PRD — all 3 downstream docs referencing it are flagged."""

    def test_lint_catches_all_stale_references(self, tmp_path, monkeypatch):
        proj = scenario_archived_prd_cascade(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 1
        prd_errors = [e for e in errors if "PRD-00000000000000000000000001" in e and "archived" in e]
        assert len(prd_errors) >= 3, f"Expected 3+ errors for archived PRD, got: {prd_errors}"

    def test_identifies_each_affected_document(self, tmp_path, monkeypatch):
        proj = scenario_archived_prd_cascade(tmp_path)
        _, errors = lint_project(proj, monkeypatch)
        error_text = "\n".join(errors)
        assert "ADR-00000000000000000000000001" in error_text
        assert "ADR-00000000000000000000000002" in error_text
        assert "SPEC-00000000000000000000000001" in error_text


class TestDanglingReference:
    """SPEC references nonexistent ADR-00000000000000000000000099. Exactly 1 dangling error."""

    def test_lint_catches_dangling(self, tmp_path, monkeypatch):
        proj = scenario_dangling_reference(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 1
        dangling = [e for e in errors if "does not exist" in e]
        assert len(dangling) == 1, f"Expected exactly 1 dangling error, got: {dangling}"
        assert "ADR-00000000000000000000000099" in dangling[0]


class TestAdrDanglingToPrd:
    """ADR references nonexistent PRD-00000000000000000000000099. Different code path, exactly 1 error."""

    def test_lint_catches_dangling(self, tmp_path, monkeypatch):
        proj = scenario_adr_dangling_to_prd(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 1
        dangling = [e for e in errors if "does not exist" in e]
        assert len(dangling) == 1, f"Expected exactly 1 dangling error, got: {dangling}"
        assert "PRD-00000000000000000000000099" in dangling[0]


class TestSelfReference:
    """Document references itself. Exactly 1 self-reference error."""

    def test_lint_catches_self_reference(self, tmp_path, monkeypatch):
        proj = scenario_self_reference(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 1
        self_errors = [e for e in errors if "self" in e.lower()]
        assert len(self_errors) == 1, f"Expected exactly 1 self-ref error, got: {self_errors}"
        assert "SPEC-00000000000000000000000001" in self_errors[0]


class TestBrokenSupersedeSymmetry:
    """ADR-1 says superseded-by ADR-2, but ADR-2 does not say supersedes."""

    def test_lint_catches_asymmetry(self, tmp_path, monkeypatch):
        proj = scenario_broken_supersede_symmetry(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 1
        assert any("ADR-00000000000000000000000001" in e and "ADR-00000000000000000000000002" in e for e in errors), (
            f"Expected supersede asymmetry error, got: {errors}"
        )


class TestDanglingSupersedeTarget:
    """ADR-1 says superseded-by ADR-99, but ADR-99 does not exist."""

    def test_lint_catches_dangling_supersede(self, tmp_path, monkeypatch):
        proj = scenario_dangling_supersede_target(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 1
        assert any("ADR-00000000000000000000000099" in e and "does not exist" in e for e in errors), (
            f"Expected dangling supersede-by error, got: {errors}"
        )


class TestDuplicateIds:
    """Two files map to the same ADR-00000000000000000000000001. Should be detected."""

    def test_lint_catches_duplicate(self, tmp_path, monkeypatch):
        proj = scenario_duplicate_ids(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 1
        assert any("ADR-00000000000000000000000001" in e and "duplicate" in e.lower() for e in errors), (
            f"Expected duplicate ID error, got: {errors}"
        )


class TestDeprecatedAdrNoReplacement:
    """Deprecated ADR (no superseded-by). Exactly 1 error, different from superseded."""

    def test_lint_catches_deprecated_reference(self, tmp_path, monkeypatch):
        proj = scenario_deprecated_adr_no_replacement(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 1
        dep_errors = [e for e in errors if "deprecated" in e]
        assert len(dep_errors) == 1, f"Expected exactly 1 deprecated error, got: {dep_errors}"
        assert "ADR-00000000000000000000000001" in dep_errors[0]


class TestPrdSplit:
    """PRD archived after split. 3 downstream docs reference it."""

    def test_lint_catches_stale_references(self, tmp_path, monkeypatch):
        proj = scenario_prd_split(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 1
        prd_errors = [e for e in errors if "PRD-00000000000000000000000001" in e and "archived" in e]
        assert len(prd_errors) >= 3, f"Expected 3+ errors for archived split PRD, got: {prd_errors}"


class TestUnknownPrefixReference:
    """Reference to RFC-001 where RFC is not a canonical document ID."""

    def test_lint_catches_unknown_prefix(self, tmp_path, monkeypatch):
        proj = scenario_unknown_prefix_reference(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 1
        malformed = [e for e in errors if "RFC-001" in e and "TYPE-ULID" in e]
        assert len(malformed) == 1, f"Expected 1 malformed-ID error for RFC-001, got: {errors}"


class TestMalformedReferenceId:
    """References with wrong digit count or case. Should be flagged."""

    def test_lint_catches_malformed_ids(self, tmp_path, monkeypatch):
        proj = scenario_malformed_reference_id(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 1
        assert any("ADR-1" in e and "TYPE-ULID" in e for e in errors), (
            f"Expected malformed-ID error for ADR-1, got: {errors}"
        )


class TestDanglingSupersedes:
    """ADR-2 says supersedes ADR-99, but ADR-99 does not exist."""

    def test_lint_catches_dangling_supersedes(self, tmp_path, monkeypatch):
        proj = scenario_dangling_supersedes_field(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 1
        assert any("ADR-00000000000000000000000099" in e and "does not exist" in e for e in errors), (
            f"Expected dangling supersedes error, got: {errors}"
        )


class TestSupersededByWithoutStatus:
    """Has superseded-by field but status is 'accepted'. Inconsistency."""

    def test_lint_catches_field_status_mismatch(self, tmp_path, monkeypatch):
        proj = scenario_superseded_by_without_status(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 1
        assert any("ADR-00000000000000000000000001" in e for e in errors), (
            f"Expected field/status mismatch error for ADR-00000000000000000000000001, got: {errors}"
        )


class TestMixedErrorsInOneDocument:
    """One document with both dangling and stale references. Both reported."""

    def test_lint_reports_both_errors(self, tmp_path, monkeypatch):
        proj = scenario_mixed_errors_in_one_document(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 1
        dangling = [e for e in errors if "ADR-00000000000000000000000099" in e and "does not exist" in e]
        stale = [e for e in errors if "ADR-00000000000000000000000001" in e and "rejected" in e]
        assert len(dangling) >= 1, f"Expected dangling error for ADR-00000000000000000000000099, got: {errors}"
        assert len(stale) >= 1, f"Expected stale error for ADR-00000000000000000000000001, got: {errors}"


class TestDeadToDeadReference:
    """Superseded ADR references rejected ADR. Both dead. Still flagged."""

    def test_lint_catches_dead_to_dead(self, tmp_path, monkeypatch):
        proj = scenario_dead_to_dead_reference(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 1
        rejected_errors = [e for e in errors if "ADR-00000000000000000000000001" in e and "rejected" in e]
        assert len(rejected_errors) == 1, f"Expected dead-to-dead ref flagged, got: {errors}"


class TestDeepChainNoTransitiveStaleness:
    """
    ADR superseded, only direct SPEC-00000000000000000000000001 flagged.
    SPEC-00000000000000000000000002 and SPEC-00000000000000000000000003 (indirect chain) are NOT flagged.
    Staleness is direct-only, not transitive.
    """

    def test_lint_fails_with_exactly_one_stale_error(self, tmp_path, monkeypatch):
        proj = scenario_deep_chain_no_transitive_staleness(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 1
        stale_errors = [e for e in errors if "superseded" in e or "does not exist" in e]
        assert len(stale_errors) == 1, f"Expected exactly 1 stale error (direct only), got: {stale_errors}"

    def test_only_spec001_is_flagged(self, tmp_path, monkeypatch):
        proj = scenario_deep_chain_no_transitive_staleness(tmp_path)
        _, errors = lint_project(proj, monkeypatch)
        stale = [e for e in errors if "superseded" in e]
        assert any("SPEC-00000000000000000000000001" in e for e in stale)
        assert not any("SPEC-00000000000000000000000002" in e for e in stale)
        assert not any("SPEC-00000000000000000000000003" in e for e in stale)


# ═════════════════════════════════════════════════════════════��
# Two-phase scenarios
# ══════════════════════════════════════════════════════════════


class TestSupersedeCascade:
    """Phase 1: stale. Phase 2: fixed."""

    def test_phase1_lint_fails(self, tmp_path, monkeypatch):
        proj = scenario_supersede_then_cascade(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 1
        assert any("ADR-00000000000000000000000001" in e and "superseded" in e for e in errors)

    def test_phase2_lint_passes(self, tmp_path, monkeypatch):
        proj = scenario_supersede_cascade_fixed(tmp_path)
        exit_code, errors = lint_project(proj, monkeypatch)
        assert exit_code == 0, f"Fixed cascade should pass, got: {errors}"
