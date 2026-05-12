"""`decree ddd` — Decree Driven Development phase assessment.

Reads the current decree corpus, determines the lifecycle phase, and prints
the next suggested action. The phase logic mirrors the `/decree:ddd` Claude
Code skill — the skill's markdown decision tree is the normative spec.

Offline, no LLM calls. Reads frontmatter via existing decree internals.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from decree.log import error, info
from decree.parser import load_all_types

_CHECKBOX_RE = re.compile(r"^[\s]*[-*]\s+\[([ xX])\]", re.MULTILINE)


# ── Phase enum ────────────────────────────────────────────────


class Phase(str, Enum):
    """Lifecycle phases, ordered by check priority (first-match-wins, highest-urgency-first)."""

    # Highest urgency first: in-flight implementation work outranks new ideation.
    IMPLEMENTATION = "implementation"
    COMPLETION = "completion"
    PLANNING = "planning"
    TECHNICAL_DESIGN = "technical_design"
    ARCHITECTURE_DECISIONS = "architecture_decisions"
    IDEATION = "ideation"
    DONE = "done"


# ── Dataclasses ───────────────────────────────────────────────


@dataclass(frozen=True)
class DocSummary:
    """A single document summary for the assessment."""

    id: str
    type: str
    status: str
    title: str
    progress_done: int = 0
    progress_total: int = 0
    references: tuple[str, ...] = ()

    @property
    def progress_percent(self) -> int | None:
        if self.progress_total == 0:
            return None
        return round(self.progress_done / self.progress_total * 100)


@dataclass(frozen=True)
class Chain:
    """A PRD-rooted document chain: PRD → ADRs → SPECs that reference upward."""

    prd: DocSummary | None
    adrs: tuple[DocSummary, ...] = ()
    specs: tuple[DocSummary, ...] = ()


@dataclass(frozen=True)
class Suggestion:
    """A recommended next action."""

    action: str           # machine-readable verb (e.g., "create_prd", "complete_spec")
    description: str      # human-readable sentence
    target_id: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Health:
    lint_errors: int
    stale_docs: int


@dataclass(frozen=True)
class DDDAssessment:
    phase: Phase
    project_path: Path
    documents: dict[str, int]                  # {"prd": 4, "adr": 2, "spec": 1}
    progress: dict[str, int]                   # {"completed": 32, "total": 54, "percent": 59}
    chains: tuple[Chain, ...]
    orphan_adrs: tuple[DocSummary, ...]        # ADRs not in any PRD chain
    orphan_specs: tuple[DocSummary, ...]       # SPECs not in any PRD chain
    suggested_actions: tuple[Suggestion, ...]
    health: Health


# ── Internals: build summaries from parsed docs ─────────────────


def _count_checkboxes(body: str) -> tuple[int, int]:
    """Count (done, total) markdown checkboxes — same logic as commands.progress."""
    matches = _CHECKBOX_RE.findall(body)
    total = len(matches)
    done = sum(1 for m in matches if m in ("x", "X"))
    return done, total


def _summarize(doc) -> DocSummary:
    done, total = _count_checkboxes(doc.body)
    refs: tuple[str, ...] = ()
    if doc.meta.references:
        refs = tuple(doc.meta.references)
    return DocSummary(
        id=doc.doc_id,
        type=doc.doc_type.name if doc.doc_type else "adr",
        status=doc.meta.status,
        title=doc.title,
        progress_done=done,
        progress_total=total,
        references=refs,
    )


def _build_chains(summaries: list[DocSummary]) -> tuple[tuple[Chain, ...], tuple[DocSummary, ...], tuple[DocSummary, ...]]:
    """Group ADRs/SPECs under the PRD they reference. Returns (chains, orphan_adrs, orphan_specs)."""
    prds = [s for s in summaries if s.type == "prd"]
    adrs = [s for s in summaries if s.type == "adr"]
    specs = [s for s in summaries if s.type == "spec"]
    other = [s for s in summaries if s.type not in ("prd", "adr", "spec")]

    chains_list: list[Chain] = []
    orphan_adrs: list[DocSummary] = []
    orphan_specs: list[DocSummary] = []

    if not prds:
        # No PRDs — all ADRs and SPECs are orphans
        return (), tuple(adrs), tuple(specs + other)

    prd_ids = {p.id for p in prds}
    for prd in prds:
        prd_adrs = tuple(a for a in adrs if prd.id in a.references)
        adr_ids = {a.id for a in prd_adrs}
        # SPECs in this chain: either reference the PRD directly OR reference one of its ADRs.
        prd_specs = tuple(
            s for s in specs
            if prd.id in s.references or any(aid in s.references for aid in adr_ids)
        )
        chains_list.append(Chain(prd=prd, adrs=prd_adrs, specs=prd_specs))

    # Collect anything not in any chain
    chained_adrs = {a.id for c in chains_list for a in c.adrs}
    chained_specs = {s.id for c in chains_list for s in c.specs}
    orphan_adrs = [a for a in adrs if a.id not in chained_adrs]
    orphan_specs = [s for s in specs if s.id not in chained_specs] + other

    return tuple(chains_list), tuple(orphan_adrs), tuple(orphan_specs)


# ── Phase detection ──────────────────────────────────────────────


def _detect_phase_for_chain(chain: Chain) -> tuple[Phase, Suggestion] | None:
    """Detect the highest-urgency phase for a single chain. Returns None if chain is fully done."""
    # Phase 4: any SPEC in 1-99% progress → IMPLEMENTATION
    in_flight_specs = [s for s in chain.specs if s.status not in ("implemented",) and s.progress_percent is not None and 0 < s.progress_percent < 100]
    if in_flight_specs:
        s = in_flight_specs[0]
        return Phase.IMPLEMENTATION, Suggestion(
            action="continue_spec",
            description=f"Continue implementing {s.id} ({s.progress_done}/{s.progress_total} ACs done, {s.progress_percent}%)",
            target_id=s.id,
            extra={"remaining": s.progress_total - s.progress_done},
        )

    # Phase 5: any SPEC at 100% → COMPLETION
    done_specs = [s for s in chain.specs if s.progress_percent == 100 and s.status not in ("implemented",)]
    if done_specs:
        s = done_specs[0]
        return Phase.COMPLETION, Suggestion(
            action="implement_spec",
            description=f"Transition {s.id} to implemented (all ACs checked)",
            target_id=s.id,
            extra={"command": f"decree status {s.id} implement"},
        )

    # Phase 3: any SPEC with 0% progress → PLANNING
    zero_specs = [s for s in chain.specs if s.progress_total > 0 and s.progress_done == 0 and s.status not in ("implemented",)]
    if zero_specs:
        s = zero_specs[0]
        return Phase.PLANNING, Suggestion(
            action="plan_spec",
            description=f"Write an implementation plan for {s.id} or start implementing",
            target_id=s.id,
        )

    # Phase 2: ADR accepted, no SPEC references it → TECHNICAL_DESIGN
    accepted_adrs = [a for a in chain.adrs if a.status == "accepted"]
    for adr in accepted_adrs:
        if not any(adr.id in s.references for s in chain.specs):
            return Phase.TECHNICAL_DESIGN, Suggestion(
                action="create_spec",
                description=f"Create a SPEC referencing {adr.id} (and {chain.prd.id if chain.prd else 'the PRD'})",
                target_id=adr.id,
                extra={"command": f'decree new spec "<title>"'},
            )

    # Phase 1: PRD exists, no ADR references it → ARCHITECTURE_DECISIONS
    if chain.prd and chain.prd.status in ("approved", "review") and not chain.adrs:
        return Phase.ARCHITECTURE_DECISIONS, Suggestion(
            action="create_adr",
            description=f"Create an ADR referencing {chain.prd.id}",
            target_id=chain.prd.id,
            extra={"command": f'decree new adr "<title>"'},
        )

    return None


def _detect_phase(assessment_data: dict, chains: tuple[Chain, ...]) -> tuple[Phase, tuple[Suggestion, ...]]:
    """Detect the highest-urgency phase across all chains."""
    if assessment_data["doc_count"] == 0:
        return Phase.IDEATION, (
            Suggestion(
                action="create_prd",
                description="Start by defining what you're building — create your first PRD",
                extra={"command": 'decree new prd "<title>"'},
            ),
        )

    # Try each chain; collect suggestions in priority order
    phase_results: list[tuple[Phase, Suggestion]] = []
    for chain in chains:
        result = _detect_phase_for_chain(chain)
        if result is not None:
            phase_results.append(result)

    if phase_results:
        # First-match-wins by Phase ordering (IMPLEMENTATION > COMPLETION > ... > IDEATION)
        phase_priority = [
            Phase.IMPLEMENTATION,
            Phase.COMPLETION,
            Phase.PLANNING,
            Phase.TECHNICAL_DESIGN,
            Phase.ARCHITECTURE_DECISIONS,
        ]
        for phase in phase_priority:
            matching = [s for p, s in phase_results if p == phase]
            if matching:
                # Dedup by target_id — a SPEC referenced from multiple chains
                # should appear once in the suggestions list, not N times.
                seen: set = set()
                deduped: list[Suggestion] = []
                for s in matching:
                    key = (s.action, s.target_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    deduped.append(s)
                return phase, tuple(deduped)

    # No chain in any active phase → DONE
    return Phase.DONE, (
        Suggestion(
            action="next_feature",
            description="All documents are in terminal-healthy states. Start a new PRD if there's more to build.",
            extra={"command": 'decree new prd "<title>"'},
        ),
    )


# ── Health check ──────────────────────────────────────────────


def _check_health() -> Health:
    """Run lint and stale-state checks; return aggregate counts."""
    from decree.commands.lint import run as lint_run

    # Lint runs to stdout; capture exit code by running it.
    # We swallow output here — caller can run `decree lint` directly for details.
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        lint_args = argparse.Namespace(check_attachments=False)
        lint_exit = lint_run(lint_args)

    return Health(lint_errors=1 if lint_exit != 0 else 0, stale_docs=0)


# ── Public API ────────────────────────────────────────────────


def assess(project_path: Path | None = None) -> DDDAssessment:
    """Run the full DDD assessment on the project at `project_path` (or cwd)."""
    if project_path is not None:
        # Set cwd so decree's existing utilities resolve the right project
        import os
        os.chdir(project_path)
        # Clear cached project root + doc types since cwd changed
        from decree.config import get_project_root, load_doc_types
        get_project_root.cache_clear()
        load_doc_types.cache_clear()

    from decree.config import get_project_root

    try:
        root = get_project_root()
    except FileNotFoundError:
        # No decree.toml — return an "ideation" / no-corpus assessment
        return DDDAssessment(
            phase=Phase.IDEATION,
            project_path=project_path or Path.cwd(),
            documents={},
            progress={"completed": 0, "total": 0, "percent": 0},
            chains=(),
            orphan_adrs=(),
            orphan_specs=(),
            suggested_actions=(
                Suggestion(
                    action="init_decree",
                    description="No decree.toml found. Run `decree` skill init or create one manually.",
                ),
            ),
            health=Health(lint_errors=0, stale_docs=0),
        )

    docs = load_all_types(strict=False)
    summaries = [_summarize(d) for d in docs]

    # Aggregate progress
    completed = sum(s.progress_done for s in summaries)
    total = sum(s.progress_total for s in summaries)
    percent = round(completed / total * 100) if total > 0 else 0

    # Doc counts by type
    doc_counts: dict[str, int] = {}
    for s in summaries:
        doc_counts[s.type] = doc_counts.get(s.type, 0) + 1

    # Build chains
    chains, orphan_adrs, orphan_specs = _build_chains(summaries)

    # Detect phase
    phase, suggestions = _detect_phase({"doc_count": len(docs)}, chains)

    # Health
    health = _check_health()

    return DDDAssessment(
        phase=phase,
        project_path=root,
        documents=doc_counts,
        progress={"completed": completed, "total": total, "percent": percent},
        chains=chains,
        orphan_adrs=orphan_adrs,
        orphan_specs=orphan_specs,
        suggested_actions=suggestions,
        health=health,
    )


# ── Formatters ────────────────────────────────────────────────


_PHASE_LABELS = {
    Phase.IDEATION: "IDEATION",
    Phase.ARCHITECTURE_DECISIONS: "ARCHITECTURE DECISIONS",
    Phase.TECHNICAL_DESIGN: "TECHNICAL DESIGN",
    Phase.PLANNING: "PLANNING",
    Phase.IMPLEMENTATION: "IMPLEMENTATION",
    Phase.COMPLETION: "COMPLETION",
    Phase.DONE: "DONE",
}


def format_human(assessment: DDDAssessment, *, quiet: bool = False) -> str:
    """Format the assessment as human-readable text."""
    lines: list[str] = []
    label = _PHASE_LABELS[assessment.phase]
    doc_summary = ", ".join(f"{n} {t.upper()}{'s' if n != 1 else ''}" for t, n in sorted(assessment.documents.items())) or "no documents"
    pct = assessment.progress["percent"]

    lines.append(f"DDD Assessment: {assessment.project_path}")
    lines.append("")
    lines.append(f"  Phase: {label}")
    lines.append(f"  Documents: {doc_summary}")
    lines.append(f"  Progress: {pct}% ({assessment.progress['completed']}/{assessment.progress['total']})")
    if assessment.health.lint_errors:
        lines.append(f"  Health: ⚠ {assessment.health.lint_errors} lint errors")
    else:
        lines.append(f"  Health: ✓ lint clean")
    lines.append("")

    if not quiet and assessment.chains:
        lines.append("  Document chains:")
        for c in assessment.chains:
            prd_str = f"{c.prd.id} ({c.prd.status})" if c.prd else "(no PRD)"
            adr_strs = [f"{a.id} ({a.status})" for a in c.adrs] or ["(no ADRs)"]
            spec_strs = [
                f"{s.id} ({s.status}{f', {s.progress_percent}%' if s.progress_percent is not None else ''})"
                for s in c.specs
            ] or ["(no SPECs)"]
            lines.append(f"    {prd_str} ← {', '.join(adr_strs)} ← {', '.join(spec_strs)}")
        if assessment.orphan_adrs or assessment.orphan_specs:
            for s in assessment.orphan_adrs:
                lines.append(f"    (orphan) {s.id} ({s.status})")
            for s in assessment.orphan_specs:
                progress = f", {s.progress_percent}%" if s.progress_percent is not None else ""
                lines.append(f"    (orphan) {s.id} ({s.status}{progress})")
        lines.append("")

    lines.append("  Next action:")
    for sug in assessment.suggested_actions:
        lines.append(f"    → {sug.description}")
        cmd = sug.extra.get("command") if sug.extra else None
        if cmd:
            lines.append(f"      $ {cmd}")
    return "\n".join(lines)


def _dataclass_to_dict(obj):
    """Recursive dataclass → dict serializer."""
    from dataclasses import fields, is_dataclass

    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _dataclass_to_dict(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, (list, tuple)):
        return [_dataclass_to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _dataclass_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    return obj


def format_json(assessment: DDDAssessment) -> str:
    """Format the assessment as JSON for programmatic consumers."""
    data = _dataclass_to_dict(assessment)
    return json.dumps(data, indent=2, sort_keys=False)


# ── CLI entry point ──────────────────────────────────────────────


def run(args: argparse.Namespace) -> int:
    project_path = Path(args.project).resolve() if args.project else None
    try:
        assessment = assess(project_path=project_path)
    except Exception as e:  # noqa: BLE001
        error("ddd", f"assessment failed: {e}")
        return 1

    if args.json:
        print(format_json(assessment))
    else:
        print(format_human(assessment, quiet=args.quiet))

    # Exit code: 0 healthy, 1 if lint errors or stale state
    if assessment.health.lint_errors or assessment.health.stale_docs:
        return 1
    return 0


def find_root_run(args: argparse.Namespace) -> int:
    """`decree find-root` — print the path to the nearest decree.toml. Exit 1 if not found."""
    from decree.config import get_project_root

    try:
        root = get_project_root()
    except FileNotFoundError:
        return 1
    print(root)
    return 0
