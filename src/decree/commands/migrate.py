"""SPEC-01KT22NMRZ4W0CFDSJVHVQ8JBR — `decree migrate audit-coherence` command.

Runs SPEC-01KT22NMRYNFYM7EN80WS2HD6F's coherence gates in **preview mode** (force-enabled regardless
of decree.toml's per-type opt-in) across the entire corpus and reports per-gate
violations as `AuditFinding`s. The maintainer's use case: "if I enabled gate X
globally today, how many docs would lint fail on?".

Three modes:
  - default (human-readable text)
  - --json   (structured output for CI / pipeline consumers)
  - --fix    (interactive remediation: fix/skip/defer/quit per finding)
"""

from __future__ import annotations

import argparse
import dataclasses
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover -- py3.10
    import tomli as tomllib  # type: ignore[no-redef]

from decree.log import error, fail, info, success

# Gate names recognised by audit-coherence. Keep in sync with the live coherence validators.
KNOWN_GATES: tuple[str, ...] = (
    "terminal_status_progress",
    "unreferenced_active",
    "status_field_requirements",
)


@dataclasses.dataclass(frozen=True)
class AuditFinding:
    """One coherence violation surfaced by the audit.

    `severity` is "error" for live violations or "info" for findings that are
    deferred via [types.<t>.coherence_exceptions].
    """

    doc_path: str
    doc_id: str
    gate: str
    severity: str
    message: str
    suggested_fix: str | None = None


@dataclasses.dataclass(frozen=True)
class AuditReport:
    """Aggregated audit output."""

    findings: tuple[AuditFinding, ...]
    by_gate: dict[str, int]
    by_type: dict[str, int]
    total: int


# ─── library API ──────────────────────────────────────────────────────────


def audit_coherence(
    project_root: Path,
    gates: list[str] | None = None,
) -> AuditReport:
    """Run coherence gates in preview mode against every doc in the corpus.

    Reuses SPEC-01KT22NMRYNFYM7EN80WS2HD6F's validators (`validate_terminal_status_progress`,
    `validate_unreferenced_active`) but with a synthetic CoherenceConfig that
    force-enables each selected gate, regardless of the doc-type's actual
    coherence block. Per-type exceptions are honoured: listed doc IDs are
    still reported but tagged `severity="info"` with a `deferred via exception`
    note instead of erroring.
    """
    selected = _select_gates(gates)

    # Switch cwd so load_all_types picks up the right project; restore on exit.
    cwd_before = Path.cwd()
    os.chdir(project_root)
    try:
        from decree.config import (
            get_project_root,
            load_coherence_exceptions,
            load_doc_types,
        )
        from decree.parser import load_all_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()

        doc_types = load_doc_types()
        all_docs = load_all_types()
        exceptions = load_coherence_exceptions()
        synthetic_types_by_name = _force_enabled_doc_types_by_name(doc_types, selected)

        findings: list[AuditFinding] = []
        if "terminal_status_progress" in selected:
            findings.extend(_terminal_status_findings(all_docs, synthetic_types_by_name, exceptions))
        if "unreferenced_active" in selected:
            findings.extend(_unreferenced_active_findings(all_docs, synthetic_types_by_name, exceptions))
        if "status_field_requirements" in selected:
            findings.extend(_status_field_requirements_findings(all_docs, exceptions))
    finally:
        os.chdir(cwd_before)

    findings_t = tuple(findings)
    by_gate: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for f in findings_t:
        # Only "error" severity counts toward enforcement totals; "info"
        # (deferred via exception) is informational.
        if f.severity != "error":
            continue
        by_gate[f.gate] = by_gate.get(f.gate, 0) + 1
        doc_type = _doc_type_from_id(f.doc_id)
        by_type[doc_type] = by_type.get(doc_type, 0) + 1
    total = sum(by_gate.values())
    return AuditReport(
        findings=findings_t,
        by_gate=by_gate,
        by_type=by_type,
        total=total,
    )


# ─── findings builders (one per gate) ─────────────────────────────────────


def _terminal_status_findings(
    all_docs: list,
    types_by_name: dict,
    exceptions: dict[str, dict[str, frozenset[str]]],
) -> list[AuditFinding]:
    from decree.checklists import DEFAULT_DEFERRED_SECTION_PATTERNS, parse_checkboxes_by_section
    from decree.commands.report import is_terminal_success

    out: list[AuditFinding] = []
    for doc in all_docs:
        if doc.doc_type is None:
            continue
        dt = types_by_name.get(doc.doc_type.name)
        if dt is None:
            continue
        coh = getattr(dt, "coherence", None)
        if coh is None or not getattr(coh, "terminal_status_progress", False):
            continue
        if not is_terminal_success(dt, doc.meta.status):
            continue
        patterns = tuple(coh.deferred_sections) or DEFAULT_DEFERRED_SECTION_PATTERNS
        parsed = parse_checkboxes_by_section(doc.body, patterns)
        total = parsed.primary_total
        done = parsed.primary_done
        if total == 0 or done == total:
            continue
        pct = round(done / total * 100) if total else 0
        remaining = total - done
        message = f"status '{doc.meta.status}' but primary AC progress is {done}/{total} ({pct}%)"
        suggested = (
            f"check {remaining} unchecked AC{'s' if remaining != 1 else ''} or move them under a deferred section"
        )
        sev, msg = _maybe_demote_to_info(doc.doc_id, "terminal_status_progress", message, dt.name, exceptions)
        out.append(
            AuditFinding(
                doc_path=_display_path(doc.path),
                doc_id=doc.doc_id,
                gate="terminal_status_progress",
                severity=sev,
                message=msg,
                suggested_fix=suggested,
            )
        )
    return out


def _unreferenced_active_findings(
    all_docs: list,
    types_by_name: dict,
    exceptions: dict[str, dict[str, frozenset[str]]],
) -> list[AuditFinding]:
    from datetime import date as _date

    today = _date.today()
    inbound: dict[str, int] = {}
    for d in all_docs:
        for r in d.meta.references or []:
            inbound[r] = inbound.get(r, 0) + 1

    out: list[AuditFinding] = []
    for doc in all_docs:
        if doc.doc_type is None:
            continue
        dt = types_by_name.get(doc.doc_type.name)
        if dt is None:
            continue
        coh = getattr(dt, "coherence", None)
        if coh is None or not getattr(coh, "unreferenced_active", False):
            continue
        active = set(coh.active_statuses) if coh.active_statuses else {"approved", "accepted"}
        if doc.meta.status not in active:
            continue
        if inbound.get(doc.doc_id, 0) > 0:
            continue
        d_date = doc.meta.date
        if not isinstance(d_date, _date):
            continue
        age_days = (today - d_date).days
        if age_days <= coh.unreferenced_after_days:
            continue
        message = (
            f"status '{doc.meta.status}' for {age_days} days with no referencing "
            f"document (threshold: {coh.unreferenced_after_days} days)"
        )
        suggested = "transition status back to draft, add an inbound reference, or raise the threshold"
        sev, msg = _maybe_demote_to_info(doc.doc_id, "unreferenced_active", message, dt.name, exceptions)
        out.append(
            AuditFinding(
                doc_path=_display_path(doc.path),
                doc_id=doc.doc_id,
                gate="unreferenced_active",
                severity=sev,
                message=msg,
                suggested_fix=suggested,
            )
        )
    return out


def _status_field_requirements_findings(
    all_docs: list,
    exceptions: dict[str, dict[str, frozenset[str]]],
) -> list[AuditFinding]:
    """Audit-only check: each doc whose status has required fields must have them.

    Already enforced at parse time by DocFrontmatter, so live violations cannot
    survive into a parsed doc. Surfaces nothing under the audit *unless* a doc
    type defines new requirements not yet honoured — useful when adding a new
    `status_field_requirements` row and previewing impact.
    """
    out: list[AuditFinding] = []
    for doc in all_docs:
        if doc.doc_type is None:
            continue
        reqs = doc.doc_type.status_field_requirements.get(doc.meta.status, ())
        missing = [fld for fld in reqs if getattr(doc.meta, fld.replace("-", "_"), None) is None]
        if not missing:
            continue
        message = f"status '{doc.meta.status}' requires field(s) {', '.join(missing)} but they are absent"
        suggested = f"set field(s) {', '.join(missing)} in frontmatter"
        sev, msg = _maybe_demote_to_info(
            doc.doc_id,
            "status_field_requirements",
            message,
            doc.doc_type.name,
            exceptions,
        )
        out.append(
            AuditFinding(
                doc_path=_display_path(doc.path),
                doc_id=doc.doc_id,
                gate="status_field_requirements",
                severity=sev,
                message=msg,
                suggested_fix=suggested,
            )
        )
    return out


# ─── helpers ───────────────────────────────────────────────────────────────


def _select_gates(gates: list[str] | None) -> tuple[str, ...]:
    if not gates:
        return KNOWN_GATES
    unknown = [g for g in gates if g not in KNOWN_GATES]
    if unknown:
        raise ValueError(f"Unknown gate(s): {unknown}. Known: {list(KNOWN_GATES)}")
    # Preserve caller order while de-duplicating.
    seen: set[str] = set()
    ordered: list[str] = []
    for g in gates:
        if g not in seen:
            seen.add(g)
            ordered.append(g)
    return tuple(ordered)


def _force_enabled_doc_types_by_name(doc_types: tuple, selected: tuple[str, ...]) -> dict:
    """Build a synthetic {name: DocType} where the selected gates are forced on.

    The audit runs in *preview mode*: it ignores per-type `coherence` enable
    flags and pretends each selected gate is enabled for every type. The
    surrounding gate logic (e.g., `is_terminal_success`, threshold checks)
    still applies, so docs that wouldn't trigger a gate aren't reported.
    """
    from decree.config import CoherenceConfig

    out: dict = {}
    for dt in doc_types:
        existing = getattr(dt, "coherence", None)
        merged = CoherenceConfig(
            terminal_status_progress=(
                "terminal_status_progress" in selected or bool(getattr(existing, "terminal_status_progress", False))
            ),
            deferred_sections_separated=bool(getattr(existing, "deferred_sections_separated", False)),
            unreferenced_active=(
                "unreferenced_active" in selected or bool(getattr(existing, "unreferenced_active", False))
            ),
            unreferenced_after_days=int(getattr(existing, "unreferenced_after_days", 30)),
            deferred_sections=tuple(getattr(existing, "deferred_sections", ()) or ()),
            expected_referrer_types=tuple(getattr(existing, "expected_referrer_types", ()) or ()),
            active_statuses=tuple(getattr(existing, "active_statuses", ()) or ()),
        )
        # Build a shallow copy of the doc type with the new coherence block.
        out[dt.name] = dataclasses.replace(dt, coherence=merged)
    return out


def _maybe_demote_to_info(
    doc_id: str,
    gate: str,
    message: str,
    type_name: str,
    exceptions: dict[str, dict[str, frozenset[str]]],
) -> tuple[str, str]:
    """If this doc is in coherence_exceptions[type][gate], demote severity to info."""
    type_exc = exceptions.get(type_name, {})
    if doc_id in type_exc.get(gate, frozenset()):
        return "info", f"{message} [deferred via exception]"
    return "error", message


def _display_path(p: Path) -> str:
    try:
        return "/".join(p.parts[-3:])
    except Exception:
        return p.name


def _doc_type_from_id(doc_id: str) -> str:
    """Best-effort: extract the type prefix (e.g., 'SPEC' from 'SPEC-01KT22NMRYJ4482K92AX9GJTMA')."""
    return doc_id.split("-", 1)[0] if "-" in doc_id else doc_id


# ─── CLI handler ──────────────────────────────────────────────────────────


def audit_coherence_run(args: argparse.Namespace) -> int:
    """`decree migrate audit-coherence` — CLI entrypoint."""
    try:
        root = _resolve_root(getattr(args, "project", None))
    except FileNotFoundError as e:
        fail(str(e))
        return 1

    gates = list(getattr(args, "gate", None) or []) or None
    try:
        report = audit_coherence(root, gates=gates)
    except ValueError as e:
        fail(str(e))
        return 1

    if getattr(args, "fix", False):
        return _fix_loop(root, report, gates)

    if getattr(args, "json", False):
        print(json.dumps(_report_to_dict(report), indent=2, sort_keys=True))
    else:
        print(_format_human(report))

    return 0 if report.total == 0 else 1


def _resolve_root(project_arg: str | None) -> Path:
    if project_arg:
        path = Path(project_arg).resolve()
        if not (path / "decree.toml").exists():
            raise FileNotFoundError(f"{path} has no decree.toml")
        return path
    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()
    return get_project_root()


def _report_to_dict(report: AuditReport) -> dict:
    return {
        "total": report.total,
        "by_gate": dict(report.by_gate),
        "by_type": dict(report.by_type),
        "findings": [
            {
                "doc_path": f.doc_path,
                "doc_id": f.doc_id,
                "gate": f.gate,
                "severity": f.severity,
                "message": f.message,
                "suggested_fix": f.suggested_fix,
            }
            for f in report.findings
        ],
    }


def _format_human(report: AuditReport) -> str:
    lines: list[str] = []
    if not report.findings:
        lines.append("audit-coherence: no findings.")
        return "\n".join(lines)

    errors = [f for f in report.findings if f.severity == "error"]
    infos = [f for f in report.findings if f.severity != "error"]

    if errors:
        lines.append(f"Found {len(errors)} coherence violation(s):")
        lines.append("")
        for f in errors:
            lines.append(f"  {f.doc_path}")
            lines.append(f"    gate: {f.gate}")
            lines.append(f"    {f.message}")
            if f.suggested_fix:
                lines.append(f"    fix: {f.suggested_fix}")
            lines.append("")
    else:
        lines.append("audit-coherence: no violations (errors).")
        lines.append("")

    if infos:
        lines.append(f"{len(infos)} finding(s) deferred via exception:")
        lines.append("")
        for f in infos:
            lines.append(f"  {f.doc_path}  ({f.gate})  {f.message}")
        lines.append("")

    if report.by_gate:
        lines.append("By gate:")
        for gate, count in sorted(report.by_gate.items()):
            lines.append(f"  {gate}: {count}")
        lines.append("")
    if report.by_type:
        lines.append("By type:")
        for tname, count in sorted(report.by_type.items()):
            lines.append(f"  {tname}: {count}")
    return "\n".join(lines)


# ─── --fix interactive loop ───────────────────────────────────────────────


def _fix_loop(root: Path, report: AuditReport, gates: list[str] | None) -> int:
    """Walk findings one at a time and let the user fix/skip/defer/quit."""
    if not sys.stdin.isatty():
        error(
            "audit-coherence",
            "--fix requires an interactive TTY. For non-interactive use, pass --json.",
        )
        return 1

    errors = [f for f in report.findings if f.severity == "error"]
    if not errors:
        success("audit-coherence: nothing to fix.")
        return 0

    remaining: list[AuditFinding] = []
    quit_early = False
    total = len(errors)
    for idx, finding in enumerate(errors, start=1):
        if quit_early:
            remaining.append(finding)
            continue

        print()
        print(f"[{idx}/{total}] {finding.doc_path}")
        print(f"  Gate: {finding.gate}")
        print(f"  Issue: {finding.message}")
        if finding.suggested_fix:
            print(f"  Suggested fix: {finding.suggested_fix}")
        print("")
        print("  Options:")
        print("    f) Fix — open $EDITOR on the document")
        print("    s) Skip this finding")
        print("    d) Defer — add this doc to decree.toml exceptions for this gate")
        print("    q) Quit (apply changes so far; skip the rest)")

        while True:
            try:
                choice = input("  Choice [f/s/d/q]: ").strip().lower()
            except EOFError:
                choice = "q"
            if choice in ("f", "s", "d", "q"):
                break
            print("  (invalid; choose one of f/s/d/q)")

        if choice == "q":
            quit_early = True
            remaining.append(finding)
            continue
        if choice == "s":
            remaining.append(finding)
            continue
        if choice == "d":
            try:
                _append_exception(root, finding.doc_id, finding.gate)
                info(
                    "audit-coherence",
                    f"deferred {finding.doc_id} for gate '{finding.gate}'",
                )
            except Exception as e:
                error("audit-coherence", f"failed to write decree.toml: {e}")
                remaining.append(finding)
            continue
        # choice == "f"
        if not _open_editor_and_revalidate(root, finding, gates):
            remaining.append(finding)

    if remaining:
        info(
            "audit-coherence",
            f"{len(remaining)} finding(s) unresolved.",
        )
        return 1
    success("audit-coherence: all findings resolved.")
    return 0


def _open_editor_and_revalidate(root: Path, finding: AuditFinding, gates: list[str] | None) -> bool:
    """Spawn $EDITOR on the doc, then re-run the audit on that single doc/gate.

    Returns True if the finding is resolved (no longer reported), False
    otherwise. The caller decides what to do with the remaining finding.
    """
    doc_path = root / finding.doc_path
    if not doc_path.exists():
        # Fall back to a path scan — display path may be truncated.
        candidates = list(root.glob(f"**/{Path(finding.doc_path).name}"))
        if candidates:
            doc_path = candidates[0]
        else:
            error("audit-coherence", f"cannot locate doc: {finding.doc_path}")
            return False

    editor = os.environ.get("EDITOR", "vim")
    try:
        subprocess.run([editor, str(doc_path)], check=False)
    except FileNotFoundError:
        error("audit-coherence", f"editor not found: {editor}")
        return False

    # Re-audit — but only the gate that was flagged, for speed and clarity.
    follow_up = audit_coherence(root, gates=[finding.gate])
    still_failing = [f for f in follow_up.findings if f.severity == "error" and f.doc_id == finding.doc_id]
    if still_failing:
        info(
            "audit-coherence",
            f"{finding.doc_id} still failing gate '{finding.gate}' — keep editing or pick another option",
        )
        return False
    return True


def _append_exception(root: Path, doc_id: str, gate: str) -> None:
    """Add doc_id to [types.<type>.coherence_exceptions][<gate>] in decree.toml.

    Atomic write via a sibling tempfile + os.replace. Preserves any other
    config keys verbatim; if the target table does not exist we append it
    at the end of the file. (Best-effort line-based edit — tomllib is
    read-only in stdlib, and we don't want a new dependency for SPEC-01KT22NMRZ4W0CFDSJVHVQ8JBR.)
    """
    type_name = _resolve_type_name_for_doc(root, doc_id)
    if type_name is None:
        raise ValueError(f"cannot resolve doc type for {doc_id}")

    toml_path = root / "decree.toml"
    text = toml_path.read_text()
    section_header = f"[types.{type_name}.coherence_exceptions]"
    key_line_prefix = f"{gate} = "

    lines = text.splitlines()
    sect_start = _find_section(lines, section_header)

    if sect_start is None:
        # Append a brand-new section at the bottom.
        new_block = [
            "",
            section_header,
            f'{gate} = ["{doc_id}"]',
        ]
        new_text = text.rstrip() + "\n" + "\n".join(new_block) + "\n"
        _atomic_write(toml_path, new_text)
        return

    # Section exists. Look for the gate key inside it.
    sect_end = _find_next_section_or_eof(lines, sect_start + 1)
    key_idx: int | None = None
    for i in range(sect_start + 1, sect_end):
        if lines[i].strip().startswith(key_line_prefix):
            key_idx = i
            break

    if key_idx is None:
        # Append a new key inside the section.
        new_lines = [*lines[:sect_end], f'{gate} = ["{doc_id}"]', *lines[sect_end:]]
        _atomic_write(toml_path, "\n".join(new_lines) + ("\n" if text.endswith("\n") else ""))
        return

    # Mutate the existing list line — parse out the existing list, append.
    existing_line = lines[key_idx]
    _, _, rhs = existing_line.partition("=")
    rhs = rhs.strip()
    try:
        existing_list = tomllib.loads(f"v = {rhs}")["v"]
    except Exception as e:
        raise ValueError(f"cannot parse existing coherence_exceptions list: {e}") from e
    if doc_id in existing_list:
        return  # already present; no-op
    existing_list.append(doc_id)
    formatted = ", ".join(f'"{x}"' for x in existing_list)
    lines[key_idx] = f"{gate} = [{formatted}]"
    _atomic_write(toml_path, "\n".join(lines) + ("\n" if text.endswith("\n") else ""))


def _resolve_type_name_for_doc(root: Path, doc_id: str) -> str | None:
    cwd_before = Path.cwd()
    os.chdir(root)
    try:
        from decree.config import (
            find_doc_type,
            get_project_root,
            load_doc_types,
        )

        get_project_root.cache_clear()
        load_doc_types.cache_clear()
        try:
            return find_doc_type(doc_id).name
        except Exception:
            return None
    finally:
        os.chdir(cwd_before)


def _find_section(lines: list[str], header: str) -> int | None:
    for i, line in enumerate(lines):
        if line.strip() == header:
            return i
    return None


def _find_next_section_or_eof(lines: list[str], start: int) -> int:
    for i in range(start, len(lines)):
        s = lines[i].lstrip()
        if s.startswith("[") and not s.startswith("[["):
            return i
    return len(lines)


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    os.replace(tmp, path)


# ─── stdin helper for tests ────────────────────────────────────────────────


def _is_tty_override(stream: io.IOBase | None = None) -> bool:
    """Indirection so tests can monkeypatch stdin tty state."""
    target = stream if stream is not None else sys.stdin
    return bool(target.isatty()) if hasattr(target, "isatty") else False


# ─── SPEC-01KT22NMS0D19VMD8VPK4D2MNX: legacy sequential ID migration ──────────────────────────────


@dataclasses.dataclass(frozen=True)
class LegacyDoc:
    path: Path
    type_name: str
    type_dir: str
    old_id: str
    new_id: str
    slug: str


def migrate_ids_run(args: argparse.Namespace) -> int:
    """`decree migrate ids` — convert filename-derived IDs to frontmatter IDs."""
    try:
        root = _resolve_root(getattr(args, "project", None))
    except FileNotFoundError as e:
        fail(str(e))
        return 1

    apply = bool(getattr(args, "apply", False))
    try:
        legacy_docs = _plan_id_migration(root)
    except Exception as e:
        fail(f"could not plan ID migration: {e}")
        return 1

    if not legacy_docs:
        success("migrate ids: no legacy numeric documents found.")
        return 0

    print(f"migrate ids: {len(legacy_docs)} legacy document(s)")
    for item in legacy_docs:
        rel = item.path.relative_to(root)
        print(f"  {item.old_id} -> {item.new_id}  {rel}")

    if not apply:
        success("dry-run complete; no files changed.")
        return 0

    try:
        mapping_path = _apply_id_migration(root, legacy_docs)
    except Exception as e:
        fail(f"ID migration failed: {e}")
        return 1

    success(f"migrated {len(legacy_docs)} document(s); mapping written to {mapping_path}")
    return 0


def _plan_id_migration(root: Path) -> list[LegacyDoc]:
    from decree.config import get_project_root, load_doc_types
    from decree.identity import generate_doc_id

    cwd_before = Path.cwd()
    os.chdir(root)
    try:
        get_project_root.cache_clear()
        load_doc_types.cache_clear()
        doc_types = load_doc_types()
    finally:
        os.chdir(cwd_before)

    out: list[LegacyDoc] = []
    for dt in doc_types:
        type_dir = root / dt.dir
        if not type_dir.exists():
            continue
        for path in sorted(p for p in type_dir.glob("*.md") if p.name != "index.md"):
            match = _legacy_filename_re(dt).match(path.name)
            if not match:
                continue
            post = _load_frontmatter_raw(path)
            if post.metadata.get("id"):
                continue
            stem_parts = path.stem.split("-", 1)
            slug = stem_parts[1] if len(stem_parts) == 2 else "document"
            old_id = _legacy_format_id(dt, int(match.group(1)))
            out.append(
                LegacyDoc(
                    path=path,
                    type_name=dt.name,
                    type_dir=dt.dir,
                    old_id=old_id,
                    new_id=generate_doc_id(dt.prefix),
                    slug=slug,
                )
            )
    return out


def _legacy_filename_re(doc_type) -> re.Pattern:
    """Filename matcher used only by `decree migrate ids`."""
    return re.compile(rf"^(\d{{{doc_type.legacy_digits}}})-.+\.md$")


def _legacy_format_id(doc_type, number: int) -> str:
    """Build an old numeric ID while planning `decree migrate ids`."""
    return f"{doc_type.prefix}-{number:0{doc_type.legacy_digits}d}"


def _apply_id_migration(root: Path, docs: list[LegacyDoc]) -> Path:
    import frontmatter

    from decree.commands import index as index_cmd
    from decree.config import get_project_root, load_doc_types
    from decree.identity import filename_for_doc_id

    id_map = {d.old_id: d.new_id for d in docs}
    moves: list[tuple[Path, Path]] = []

    for item in docs:
        post = frontmatter.load(str(item.path))
        metadata = dict(post.metadata)
        metadata["id"] = item.new_id
        _rewrite_metadata_ids(metadata, id_map)
        body = _rewrite_heading_id(post.content, item.old_id, item.new_id)
        new_path = item.path.with_name(filename_for_doc_id(item.new_id, item.slug))
        if new_path.exists():
            raise FileExistsError(f"target already exists: {new_path}")
        item.path.write_text(frontmatter.dumps(frontmatter.Post(body, **metadata)).rstrip() + "\n")
        moves.append((item.path, new_path))

    for old_path, new_path in moves:
        old_path.rename(new_path)

    _migrate_report_snapshots(root, docs, id_map)
    mapping_path = _write_id_mapping(root, docs)

    cwd_before = Path.cwd()
    os.chdir(root)
    try:
        get_project_root.cache_clear()
        load_doc_types.cache_clear()
        index_cmd.run(None)
    finally:
        os.chdir(cwd_before)

    return mapping_path


def _load_frontmatter_raw(path: Path):
    import frontmatter

    return frontmatter.load(str(path))


def _rewrite_metadata_ids(metadata: dict, id_map: dict[str, str]) -> None:
    if isinstance(metadata.get("references"), list):
        metadata["references"] = [id_map.get(str(ref), str(ref)) for ref in metadata["references"]]
    for key in ("supersedes", "superseded-by"):
        value = metadata.get(key)
        if isinstance(value, str) and value in id_map:
            metadata[key] = id_map[value]


def _rewrite_heading_id(body: str, old_id: str, new_id: str) -> str:
    prefix = f"# {old_id} "
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = f"# {new_id} {line[len(prefix) :]}"
            return "\n".join(lines) + ("\n" if body.endswith("\n") else "")
    return body


def _migrate_report_snapshots(root: Path, docs: list[LegacyDoc], id_map: dict[str, str]) -> None:
    for item in docs:
        report = root / item.type_dir / "reports" / f"{item.old_id}.md"
        if not report.exists():
            continue
        text = report.read_text()
        for old_id, new_id in id_map.items():
            text = text.replace(old_id, new_id)
        target = report.with_name(f"{item.new_id}.md")
        if target.exists():
            raise FileExistsError(f"target report already exists: {target}")
        report.write_text(text)
        report.rename(target)


def _write_id_mapping(root: Path, docs: list[LegacyDoc]) -> Path:
    from datetime import UTC, datetime

    migrations_dir = root / "decree" / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = migrations_dir / f"{stamp}-id-migration.json"
    payload = {
        "schema": "decree-id-migration-v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "documents": [
            {
                "type": d.type_name,
                "old_id": d.old_id,
                "new_id": d.new_id,
                "old_path": str(d.path.relative_to(root)),
            }
            for d in docs
        ],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


# ─── SPEC-01KT22NMS0BN1F5B01HEFK87W0: deterministic governs handoff ───────

GOVERNS_ANALYSIS_SCHEMA = "decree.governs-analysis.v1"
GOVERNS_SUGGESTIONS_SCHEMA = "decree.governs-suggestions.v1"
GOVERNS_APPLY_SCHEMA = "decree.governs-apply.v1"
GOVERNS_BODY_CHAR_BUDGET = 24_000
_PATH_CANDIDATE_RE = re.compile(r"(?<![\w/.-])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+(?:#[A-Za-z_][\w.]*)?")


@dataclasses.dataclass(frozen=True)
class SuggestionResult:
    """One externally proposed `governs:` array for a single document.

    Proposals are untrusted input from an agent/skill. Core decree validates
    schema, document IDs, path syntax, duplicate entries, and on-disk existence
    before diffing or writing anything.

    `error` is populated for invalid input. Invalid suggestions are shown and
    block writes; decree never silently drops malformed paths.
    """

    doc_id: str
    doc_path: str
    current_governs: tuple[str, ...]
    proposed_governs: tuple[str, ...]
    confidence: str
    rationale: str
    verified_paths: tuple[str, ...]
    unverified_paths: tuple[str, ...]
    error: str | None = None


@dataclasses.dataclass(frozen=True)
class ApplyResult:
    """Outcome of writing one SuggestionResult to disk."""

    doc_id: str
    doc_path: str
    wrote: bool
    skipped_reason: str | None = None
    error: str | None = None


def _validate_governs_entry(entry: object) -> str | None:
    """Mirror `validators.validate_governs_paths` + frontmatter's `governs_syntax`.

    Returns the cleaned path string if valid, else None. Invalid entries are
    dropped (caller logs / counts them).
    """
    if not isinstance(entry, str):
        return None
    path_part = entry.split("#", 1)[0]
    if not path_part:
        return None
    if path_part.startswith("/"):
        return None
    if ".." in path_part.split("/"):
        return None
    return entry


def _body_excerpt(body: str) -> str:
    if len(body) <= GOVERNS_BODY_CHAR_BUDGET:
        return body
    return body[:GOVERNS_BODY_CHAR_BUDGET] + "\n\n[... document truncated for length ...]"


def _candidate_paths_from_body(body: str, project_root: Path) -> tuple[str, ...]:
    """Extract deterministic repo-relative path candidates mentioned in text."""
    candidates: dict[str, None] = {}
    for match in _PATH_CANDIDATE_RE.finditer(body or ""):
        raw = match.group(0).rstrip(".,;:)")
        cleaned = _validate_governs_entry(raw)
        if cleaned is None:
            continue
        path_part = cleaned.split("#", 1)[0]
        if (project_root / path_part).exists():
            candidates.setdefault(cleaned, None)
    return tuple(candidates)


def analyze_governs(docs: list, project_root: Path) -> dict:
    """Return the deterministic analysis contract consumed by agent skills."""
    documents: list[dict] = []
    for doc in docs:
        current = tuple(doc.meta.governs or ())
        documents.append(
            {
                "document_id": doc.doc_id,
                "document_path": _display_path(doc.path),
                "document_type": doc.doc_type.name if doc.doc_type is not None else "",
                "status": doc.meta.status,
                "title": doc.title,
                "needs_governs": not bool(current),
                "existing_governs": list(current),
                "candidate_paths": list(_candidate_paths_from_body(doc.body or "", project_root)),
                "body_excerpt": _body_excerpt(doc.body or ""),
            }
        )
    return {
        "schema": GOVERNS_ANALYSIS_SCHEMA,
        "rules": {
            "suggestion_schema": GOVERNS_SUGGESTIONS_SCHEMA,
            "governs_paths": [
                "repo-relative only",
                "no absolute paths",
                "no '..' path segments",
                "path part before an optional '#symbol' must exist on disk",
                "do not include duplicates",
            ],
            "core_responsibility": "validate suggestions and apply only explicit diffs",
            "agent_responsibility": "call any LLM/runtime externally and write suggestions JSON",
        },
        "documents": documents,
    }


def _parse_llm_json(content: str) -> dict:
    """Thin wrapper for fenced JSON parsing used by external suggestion files."""
    from decree.llm_io import parse_llm_json

    return parse_llm_json(content)


def _suggestion_result_from_payload(
    item: object,
    docs_by_id: dict[str, object],
    project_root: Path,
) -> SuggestionResult:
    """Validate one untrusted suggestions.v1 item."""
    if not isinstance(item, dict):
        return SuggestionResult("", "", (), (), "", "", (), (), "suggestion item must be an object")

    raw_doc_id = item.get("document_id")
    if not isinstance(raw_doc_id, str) or not raw_doc_id:
        return SuggestionResult("", "", (), (), "", "", (), (), "suggestion item missing document_id")

    doc = docs_by_id.get(raw_doc_id)
    if doc is None:
        return SuggestionResult(raw_doc_id, "", (), (), "", "", (), (), f"unknown document_id: {raw_doc_id}")

    doc_path = _display_path(doc.path)
    current = tuple(doc.meta.governs or ())
    confidence = str(item.get("confidence", "") or "")
    if current:
        return SuggestionResult(
            doc_id=doc.doc_id,
            doc_path=doc_path,
            current_governs=current,
            proposed_governs=(),
            confidence=confidence,
            rationale="already has governs; skipped to avoid overwrite",
            verified_paths=(),
            unverified_paths=(),
            error=None,
        )

    raw_governs = item.get("governs")
    if not isinstance(raw_governs, list):
        return SuggestionResult(
            doc.doc_id,
            doc_path,
            current,
            (),
            confidence,
            str(item.get("rationale", "") or ""),
            (),
            (),
            "governs must be a list",
        )

    cleaned: list[str] = []
    verified: list[str] = []
    errors: list[str] = []
    seen: set[str] = set()
    for entry in raw_governs:
        value = _validate_governs_entry(entry)
        if value is None:
            errors.append(f"invalid governs entry: {entry!r}")
            continue
        if value in seen:
            errors.append(f"duplicate governs entry: {value}")
            continue
        seen.add(value)
        path_part = value.split("#", 1)[0]
        if not (project_root / path_part).exists():
            errors.append(f"governs path does not exist: {path_part}")
            continue
        cleaned.append(value)
        verified.append(value)

    return SuggestionResult(
        doc_id=doc.doc_id,
        doc_path=doc_path,
        current_governs=current,
        proposed_governs=tuple(cleaned) if not errors else (),
        confidence=confidence,
        rationale=str(item.get("rationale", "") or ""),
        verified_paths=tuple(verified) if not errors else (),
        unverified_paths=(),
        error="; ".join(errors) if errors else None,
    )


def load_governs_suggestions(path: Path, docs: list, project_root: Path) -> list[SuggestionResult]:
    """Load and validate an external `decree.governs-suggestions.v1` JSON file."""
    try:
        payload = _parse_llm_json(path.read_text())
    except Exception as e:
        raise ValueError(f"cannot parse suggestions JSON: {type(e).__name__}: {e}") from e

    schema = payload.get("schema")
    if schema != GOVERNS_SUGGESTIONS_SCHEMA:
        raise ValueError(f"suggestions schema must be {GOVERNS_SUGGESTIONS_SCHEMA!r}, got {schema!r}")

    raw_suggestions = payload.get("suggestions")
    if not isinstance(raw_suggestions, list):
        raise ValueError("suggestions must be a list")

    docs_by_id = {doc.doc_id: doc for doc in docs}
    return [_suggestion_result_from_payload(item, docs_by_id, project_root) for item in raw_suggestions]


def _suggestion_diff(doc_full_path: Path, suggestion: SuggestionResult) -> str:
    """Return a unified diff (as text) for setting `governs:` on the doc.

    The diff is built from the current file's frontmatter against a new
    frontmatter where `governs:` is set to `proposed_governs`. We use
    `python-frontmatter` to round-trip so the diff includes only the
    frontmatter change, never accidental body normalisation.
    """
    import difflib

    import frontmatter

    original_text = doc_full_path.read_text()
    post = frontmatter.loads(original_text)
    post["governs"] = list(suggestion.proposed_governs)
    new_text = frontmatter.dumps(post)
    if not new_text.endswith("\n"):
        new_text += "\n"

    rel_path = suggestion.doc_path
    diff = difflib.unified_diff(
        original_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f"a/{rel_path}",
        tofile=f"b/{rel_path}",
        lineterm="",
    )
    return "".join(diff)


def apply_governs(
    suggestions: list[SuggestionResult],
    project_root: Path,
    *,
    dry_run: bool,
) -> list[ApplyResult]:
    """Write `proposed_governs` to each suggestion's doc frontmatter.

    Uses `python-frontmatter` to round-trip so the body is preserved verbatim.
    Writes are atomic (write to .tmp sibling, rename). `dry_run` skips the
    write but still returns a successful result so callers can report what
    *would* have happened.

    Suggestions with empty `proposed_governs` (skipped or invalid) are
    reported as `wrote=False, skipped_reason=...` and no write is attempted.
    """
    import frontmatter

    results: list[ApplyResult] = []
    for s in suggestions:
        full_path = project_root / s.doc_path
        if not full_path.exists():
            # Display path may have been truncated; try a glob.
            matches = list(project_root.glob(f"**/{Path(s.doc_path).name}"))
            if matches:
                full_path = matches[0]

        if s.error:
            results.append(
                ApplyResult(
                    doc_id=s.doc_id,
                    doc_path=s.doc_path,
                    wrote=False,
                    skipped_reason=None,
                    error=s.error,
                )
            )
            continue
        if not s.proposed_governs:
            reason = "already has governs" if s.current_governs else "suggestions file proposed no paths"
            results.append(
                ApplyResult(
                    doc_id=s.doc_id,
                    doc_path=s.doc_path,
                    wrote=False,
                    skipped_reason=reason,
                )
            )
            continue

        if dry_run:
            results.append(
                ApplyResult(
                    doc_id=s.doc_id,
                    doc_path=s.doc_path,
                    wrote=False,
                    skipped_reason="dry-run",
                )
            )
            continue

        try:
            post = frontmatter.loads(full_path.read_text())
            post["governs"] = list(s.proposed_governs)
            new_text = frontmatter.dumps(post)
            if not new_text.endswith("\n"):
                new_text += "\n"
            _atomic_write(full_path, new_text)
            results.append(
                ApplyResult(
                    doc_id=s.doc_id,
                    doc_path=s.doc_path,
                    wrote=True,
                )
            )
        except Exception as e:
            results.append(
                ApplyResult(
                    doc_id=s.doc_id,
                    doc_path=s.doc_path,
                    wrote=False,
                    error=f"{type(e).__name__}: {e}",
                )
            )
    return results


# ─── governs CLI handler ──────────────────────────────────────────────────


def _filter_docs_for_suggest(all_docs: list, only: list[str] | None) -> list:
    """Apply `--only` filter (case-insensitive on doc_id)."""
    if not only:
        return all_docs
    wanted = {x.strip() for x in only if x and x.strip()}
    return [d for d in all_docs if d.doc_id in wanted]


def _confirm_apply(yes: bool) -> bool:
    """Prompt the user to confirm a write. Returns True iff approved."""
    if yes:
        return True
    if not sys.stdin.isatty():
        error(
            "migrate-governs",
            "stdin is not a TTY; refuse to apply without --yes. Re-run with --yes for non-interactive use.",
        )
        return False
    try:
        answer = input("Apply changes? [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer == "y"


def _suggestion_to_dict(s: SuggestionResult) -> dict:
    return {
        "doc_id": s.doc_id,
        "doc_path": s.doc_path,
        "current_governs": list(s.current_governs),
        "proposed_governs": list(s.proposed_governs),
        "confidence": s.confidence,
        "rationale": s.rationale,
        "verified_paths": list(s.verified_paths),
        "unverified_paths": list(s.unverified_paths),
        "error": s.error,
    }


def _apply_to_dict(a: ApplyResult) -> dict:
    return {
        "doc_id": a.doc_id,
        "doc_path": a.doc_path,
        "wrote": a.wrote,
        "skipped_reason": a.skipped_reason,
        "error": a.error,
    }


def _format_suggestions_human(suggestions: list[SuggestionResult], project_root: Path) -> str:
    """Render suggestions as a sequence of unified-diff hunks.

    Each hunk is prefixed with confidence + rationale as `#` comments so a
    reviewer can prioritise scrutiny. Docs with errors, no proposed paths, or
    pre-existing `governs:` are summarised as a one-liner instead of a diff.
    """
    out: list[str] = []
    for s in suggestions:
        if s.error:
            out.append(f"# {s.doc_id} ({s.doc_path}): ERROR: {s.error}")
            out.append("")
            continue
        if s.current_governs and not s.proposed_governs:
            out.append(f"# {s.doc_id} ({s.doc_path}): already has governs; skipped")
            out.append("")
            continue
        if not s.proposed_governs:
            out.append(f"# {s.doc_id} ({s.doc_path}): suggestions file proposed no paths")
            if s.rationale:
                out.append(f"# rationale: {s.rationale}")
            out.append("")
            continue
        out.append(f"# {s.doc_id} ({s.doc_path})")
        out.append(f"# confidence: {s.confidence or 'unknown'}")
        if s.rationale:
            out.append(f"# rationale: {s.rationale}")
        if s.unverified_paths:
            out.append("# unverified paths (don't exist on disk): " + ", ".join(s.unverified_paths))
        full_path = project_root / s.doc_path
        if not full_path.exists():
            matches = list(project_root.glob(f"**/{Path(s.doc_path).name}"))
            if matches:
                full_path = matches[0]
        try:
            diff = _suggestion_diff(full_path, s)
            out.append(diff)
        except Exception as e:
            out.append(f"# (could not render diff: {e})")
        out.append("")
    return "\n".join(out)


def _format_analysis_human(payload: dict) -> str:
    lines = ["governs analysis", ""]
    for item in payload["documents"]:
        marker = "needs governs" if item["needs_governs"] else "already has governs"
        lines.append(f"{item['document_id']} ({item['document_path']}): {marker}")
        if item["candidate_paths"]:
            lines.append("  candidate paths:")
            for path in item["candidate_paths"]:
                lines.append(f"    - {path}")
    return "\n".join(lines)


def governs_run(args: argparse.Namespace) -> int:
    """`decree migrate governs` deterministic analyze/apply entrypoint.

    Core decree performs no LLM calls here. `--analyze --json` emits a stable
    contract for an external agent/skill. `--apply-suggestions FILE` validates
    that agent output and previews/applies explicit frontmatter diffs.
    """
    try:
        root = _resolve_root(getattr(args, "project", None))
    except FileNotFoundError as e:
        fail(str(e))
        return 2

    # Load corpus from project_root the same way audit_coherence does.
    cwd_before = Path.cwd()
    os.chdir(root)
    try:
        from decree.config import get_project_root, load_doc_types
        from decree.parser import load_all_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()
        all_docs = load_all_types()
    finally:
        os.chdir(cwd_before)

    only = getattr(args, "only", None) or None
    docs = _filter_docs_for_suggest(all_docs, only)
    if not docs:
        fail("no documents matched --only filter" if only else "no documents in corpus")
        return 2

    as_json = bool(getattr(args, "json", False))
    if bool(getattr(args, "analyze", False)):
        payload = analyze_governs(docs, root)
        if as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(_format_analysis_human(payload))
        return 0

    suggestions_path = getattr(args, "apply_suggestions", None)
    if not suggestions_path:
        fail("choose exactly one mode: --analyze or --apply-suggestions FILE")
        return 2

    try:
        suggestions = load_governs_suggestions(Path(suggestions_path), docs, root)
    except ValueError as e:
        fail(str(e))
        return 2

    apply_results: list[ApplyResult] | None = None
    do_apply = bool(getattr(args, "apply", False))
    dry_run = bool(getattr(args, "dry_run", False))
    yes = bool(getattr(args, "yes", False))
    errored = [s for s in suggestions if s.error]

    if as_json:
        payload = {
            "schema": GOVERNS_APPLY_SCHEMA,
            "suggestions": [_suggestion_to_dict(s) for s in suggestions],
            "apply": None,
        }
        if errored:
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 1
        if do_apply:
            # In JSON mode we never prompt. Dry-run does not write and needs no confirmation.
            if not yes and not dry_run:
                fail("--apply in --json mode requires --yes (no interactive prompt)")
                payload["error"] = "apply refused: --yes required in --json mode"
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 2
            apply_results = apply_governs(suggestions, root, dry_run=dry_run)
            payload["apply"] = [_apply_to_dict(a) for a in apply_results]
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_format_suggestions_human(suggestions, root))
        if errored:
            return 1
        if do_apply:
            has_changes = any(s.proposed_governs and not s.error for s in suggestions)
            if not has_changes:
                info("migrate-governs", "no changes to apply.")
            else:
                if dry_run or _confirm_apply(yes):
                    apply_results = apply_governs(suggestions, root, dry_run=dry_run)
                    for r in apply_results:
                        if r.wrote:
                            success(f"wrote {r.doc_id} ({r.doc_path})")
                        elif r.error:
                            error(
                                "migrate-governs",
                                f"{r.doc_id}: {r.error}",
                            )
                        elif r.skipped_reason:
                            info(
                                "migrate-governs",
                                f"{r.doc_id}: skipped ({r.skipped_reason})",
                            )
                else:
                    info("migrate-governs", "apply aborted.")

    if apply_results is not None:
        errored_apply = [a for a in apply_results if a.error]
        if errored_apply:
            return 1
    return 0


def suggest_governs_run(args: argparse.Namespace) -> int:
    """Backward internal alias for the CLI dispatcher."""
    return governs_run(args)


def apply_governs_run(args: argparse.Namespace) -> int:
    """Thin alias used by older internal tests; writes only explicit suggestions."""
    args.apply = True
    return governs_run(args)


# ─── SPEC-01KWKXHERB56W94SCRZEVMBQMJ: sprint ledger v1 → v2 migration ────────
#
# The v1 monolith (decree/sprints/ledger.yaml, schema decree.sprints.v1) is
# parsed only here; runtime sprints.py refuses v1 stores and points at this
# command. Exit codes follow the governs_run convention: 0 clean, 1 failed
# apply/validation, 2 configuration or guard errors.


@dataclasses.dataclass(frozen=True)
class SprintLedgerPlan:
    """Planned v2 files derived from a v1 ledger (model objects, ready to write)."""

    state: object
    live: tuple
    closed: tuple


def migrate_sprint_ledger_run(args: argparse.Namespace) -> int:
    """`decree migrate sprint-ledger` — convert ledger.yaml to the v2 directory store."""
    from decree.sprints import CLOSED_REL_PATH, LEDGER_REL_PATH, LIVE_REL_PATH, STATE_REL_PATH

    try:
        root = _resolve_root(getattr(args, "project", None))
    except FileNotFoundError as e:
        fail(str(e))
        return 2

    ledger_file = root / LEDGER_REL_PATH
    state_file = root / STATE_REL_PATH
    if state_file.exists():
        fail(f"sprint ledger v2 already present at {STATE_REL_PATH}; nothing to migrate")
        return 2
    if not ledger_file.exists():
        fail(f"no v1 sprint ledger found at {LEDGER_REL_PATH}; nothing to migrate")
        return 2

    try:
        plan = _plan_sprint_ledger_migration(ledger_file)
    except Exception as e:
        fail(f"could not plan sprint-ledger migration: {e}")
        return 2

    print(
        f"migrate sprint-ledger: {len(plan.closed)} closed sprint(s), "
        f"{len(plan.live)} live item(s), state: {plan.state.state}"
    )
    print(f"  create {STATE_REL_PATH}")
    for item in plan.live:
        print(f"  create {LIVE_REL_PATH / (item.document + '.yaml')}")
    for record in plan.closed:
        print(f"  create {CLOSED_REL_PATH / (record.id + '.yaml')}")
    print(f"  remove {LEDGER_REL_PATH}")

    if not getattr(args, "apply", False):
        success("dry-run complete; no files changed.")
        return 0

    try:
        _apply_sprint_ledger_migration(root, plan, ledger_file)
    except Exception as e:
        fail(f"sprint-ledger migration failed: {e}")
        return 1

    from decree.sprints import validate_ledger

    try:
        result = validate_ledger(root, _load_corpus(root))
    except Exception as e:
        # The store itself was written; a corpus that fails strict parsing must
        # not turn the one-time migration into a traceback after ledger.yaml is gone.
        fail(
            f"migration applied, but post-migration validation could not run: {e}; fix the corpus and run `decree lint`"
        )
        return 1
    if result.errors:
        for err in result.errors:
            error("migrate-sprint-ledger", err)
        fail(f"migrated store failed validation with {len(result.errors)} error(s)")
        return 1
    success(f"migrated sprint ledger: wrote {1 + len(plan.live) + len(plan.closed)} file(s); removed {LEDGER_REL_PATH}")
    return 0


def _plan_sprint_ledger_migration(ledger_file: Path) -> SprintLedgerPlan:
    import yaml

    from decree.sprints import MODE_ENABLED, SCHEMA, LiveItem, SprintRecord, SprintState

    raw = yaml.safe_load(ledger_file.read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError("v1 ledger must be a YAML mapping")
    if str(raw.get("schema", "")).strip() != "decree.sprints.v1":
        raise ValueError("v1 ledger schema must be 'decree.sprints.v1'")

    state_value = str(raw.get("state", "")).strip()
    active_id = str(raw.get("active") or "").strip().upper() or None
    closed: list[SprintRecord] = []
    active_record: SprintRecord | None = None
    for idx, sprint_raw in enumerate(raw.get("sprints") or []):
        record = SprintRecord.from_raw(sprint_raw, where=f"ledger.sprints[{idx}]")
        if record.status == "closed":
            closed.append(record)
        elif record.status == "active" and record.id == active_id:
            active_record = record
        else:
            raise ValueError(f"v1 ledger contains unexpected sprint record: {record.id} (status {record.status!r})")

    live: list[LiveItem] = []
    if active_record is not None:
        # v1 guarantees active items are outcome-less; carry outcome through
        # defensively so post-apply validation can flag a corrupt v1 ledger.
        live.extend(
            LiveItem(
                document=item.document,
                scope="active",
                kind=item.kind,
                source=item.source,
                added=item.added,
                carryover_from=item.carryover_from,
                outcome=item.outcome,
            )
            for item in active_record.items
        )
    for idx, item_raw in enumerate(raw.get("backlog") or []):
        if not isinstance(item_raw, dict):
            raise ValueError(f"ledger.backlog[{idx}]: expected mapping")
        # v1 fallback: `added` defaults to `since`, never the migration date.
        merged = {**item_raw, "scope": "backlog"}
        if not merged.get("added") and merged.get("since"):
            merged["added"] = merged["since"]
        live.append(LiveItem.from_raw(merged, where=f"ledger.backlog[{idx}]"))
    for idx, item_raw in enumerate(raw.get("draft_pool") or []):
        if not isinstance(item_raw, dict):
            raise ValueError(f"ledger.draft_pool[{idx}]: expected mapping")
        live.append(LiveItem.from_raw({**item_raw, "scope": "draft_pool"}, where=f"ledger.draft_pool[{idx}]"))

    if state_value == "active":
        if active_record is None:
            raise ValueError("v1 ledger state is active but no matching active sprint record was found")
        state = SprintState(
            schema=SCHEMA,
            mode=MODE_ENABLED,
            state="active",
            active={"id": active_record.id, "name": active_record.name, "started": active_record.started},
            paused=None,
        )
    elif state_value == "paused":
        paused_raw = raw.get("paused") or {}
        if not isinstance(paused_raw, dict):
            raise ValueError("v1 ledger paused block must be a mapping")
        state = SprintState(
            schema=SCHEMA,
            mode=MODE_ENABLED,
            state="paused",
            active=None,
            paused={
                "since": _iso_date(paused_raw.get("since", "")),
                "reason": str(paused_raw.get("reason", "")).strip(),
            },
        )
    else:
        raise ValueError(f"v1 ledger has unsupported state: {state_value!r}")

    return SprintLedgerPlan(state=state, live=tuple(live), closed=tuple(closed))


def _apply_sprint_ledger_migration(root: Path, plan: SprintLedgerPlan, ledger_file: Path) -> None:
    from decree.sprints import closed_path, create_live_item, live_path, save_state, write_closed_sprint

    live_path(root).mkdir(parents=True, exist_ok=True)
    closed_path(root).mkdir(parents=True, exist_ok=True)
    for record in plan.closed:
        write_closed_sprint(record, root=root)
    for item in plan.live:
        create_live_item(item, root=root)
    save_state(plan.state, root=root)
    ledger_file.unlink()


def _load_corpus(root: Path) -> list:
    cwd_before = Path.cwd()
    os.chdir(root)
    try:
        from decree.config import get_project_root, load_doc_types
        from decree.parser import load_all_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()
        return load_all_types()
    finally:
        os.chdir(cwd_before)


def _iso_date(value: object) -> str:
    import datetime

    if isinstance(value, datetime.date):
        return value.isoformat()
    return str(value).strip()
