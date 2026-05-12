"""SPEC-010 — `decree migrate audit-coherence` command.

Runs SPEC-008's coherence gates in **preview mode** (force-enabled regardless
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
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover -- py3.10
    import tomli as tomllib  # type: ignore[no-redef]

from decree.log import error, fail, info, success

# Gate names recognised by SPEC-010. Keep in sync with SPEC-008 validators.
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

    Reuses SPEC-008's validators (`validate_terminal_status_progress`,
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
        all_docs = load_all_types(strict=False)
        exceptions = load_coherence_exceptions()
        synthetic_types_by_name = _force_enabled_doc_types_by_name(
            doc_types, selected
        )

        findings: list[AuditFinding] = []
        if "terminal_status_progress" in selected:
            findings.extend(
                _terminal_status_findings(
                    all_docs, synthetic_types_by_name, exceptions
                )
            )
        if "unreferenced_active" in selected:
            findings.extend(
                _unreferenced_active_findings(
                    all_docs, synthetic_types_by_name, exceptions
                )
            )
        if "status_field_requirements" in selected:
            findings.extend(
                _status_field_requirements_findings(all_docs, exceptions)
            )
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
    from decree.commands.report import (
        DEFAULT_DEFERRED_SECTION_PATTERNS,
        _parse_checkboxes_by_section,
        is_terminal_success,
    )

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
        parsed = _parse_checkboxes_by_section(doc.body, patterns)
        total = parsed.primary_total
        done = parsed.primary_done
        if total == 0 or done == total:
            continue
        pct = int(round(done / total * 100)) if total else 0
        remaining = total - done
        message = (
            f"status '{doc.meta.status}' but primary AC progress is "
            f"{done}/{total} ({pct}%)"
        )
        suggested = (
            f"check {remaining} unchecked AC{'s' if remaining != 1 else ''} "
            f"or move them under a deferred section"
        )
        sev, msg = _maybe_demote_to_info(
            doc.doc_id, "terminal_status_progress", message, dt.name, exceptions
        )
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
        active = (
            set(coh.active_statuses)
            if coh.active_statuses
            else {"approved", "accepted"}
        )
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
        suggested = (
            "transition status back to draft, add an inbound reference, or "
            "raise the threshold"
        )
        sev, msg = _maybe_demote_to_info(
            doc.doc_id, "unreferenced_active", message, dt.name, exceptions
        )
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
        missing = [
            fld
            for fld in reqs
            if getattr(doc.meta, fld.replace("-", "_"), None) is None
        ]
        if not missing:
            continue
        message = (
            f"status '{doc.meta.status}' requires field(s) "
            f"{', '.join(missing)} but they are absent"
        )
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
        raise ValueError(
            f"Unknown gate(s): {unknown}. Known: {list(KNOWN_GATES)}"
        )
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
                "terminal_status_progress" in selected
                or bool(getattr(existing, "terminal_status_progress", False))
            ),
            deferred_sections_separated=bool(
                getattr(existing, "deferred_sections_separated", False)
            ),
            unreferenced_active=(
                "unreferenced_active" in selected
                or bool(getattr(existing, "unreferenced_active", False))
            ),
            unreferenced_after_days=int(
                getattr(existing, "unreferenced_after_days", 30)
            ),
            deferred_sections=tuple(getattr(existing, "deferred_sections", ()) or ()),
            expected_referrer_types=tuple(
                getattr(existing, "expected_referrer_types", ()) or ()
            ),
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
    """Best-effort: extract the type prefix (e.g., 'SPEC' from 'SPEC-007')."""
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


def _fix_loop(
    root: Path, report: AuditReport, gates: list[str] | None
) -> int:
    """Walk findings one at a time and let the user fix/skip/defer/quit."""
    if not sys.stdin.isatty():
        error(
            "audit-coherence",
            "--fix requires an interactive TTY. "
            "For non-interactive use, pass --json.",
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
                _append_exception(
                    root, finding.doc_id, finding.gate
                )
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


def _open_editor_and_revalidate(
    root: Path, finding: AuditFinding, gates: list[str] | None
) -> bool:
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
    still_failing = [
        f
        for f in follow_up.findings
        if f.severity == "error" and f.doc_id == finding.doc_id
    ]
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
    read-only in stdlib, and we don't want a new dependency for SPEC-010.)
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
        new_lines = lines[: sect_end] + [f'{gate} = ["{doc_id}"]'] + lines[sect_end:]
        _atomic_write(toml_path, "\n".join(new_lines) + ("\n" if text.endswith("\n") else ""))
        return

    # Mutate the existing list line — parse out the existing list, append.
    existing_line = lines[key_idx]
    _, _, rhs = existing_line.partition("=")
    rhs = rhs.strip()
    try:
        existing_list = tomllib.loads(f"v = {rhs}")["v"]
    except Exception as e:
        raise ValueError(f"cannot parse existing coherence_exceptions list: {e}")
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



# ─── SPEC-011: governs backfill ────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class SuggestionResult:
    """One LLM-proposed `governs:` array for a single document.

    `proposed_governs` is the *full* proposal (verified + unverified, in the
    order the model returned them). `verified_paths` and `unverified_paths`
    split that list by on-disk existence at `project_root` — a human reviewer
    can prioritise scrutiny on the unverified entries before applying.

    `error` is set when the LLM call or response parse failed for this doc;
    other docs in the batch are unaffected (per-doc error isolation).
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


def _parse_llm_json(content: str) -> dict:
    """Parse an LLM response body as JSON.

    litellm with `response_format={"type":"json_object"}` returns the JSON
    payload as a string in `choices[0].message.content`. Some providers wrap
    the response in markdown code fences even when asked for json_object —
    strip a single leading/trailing ```/```json fence pair if present.
    """
    text = content.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


def suggest_governs(
    docs: list,
    model: str,
    project_root: Path,
) -> list[SuggestionResult]:
    """Call the LLM once per doc to propose a `governs:` array.

    Per-doc behaviour:
      1. If `doc.meta.governs` is already non-empty, skip — return a result
         with empty `proposed_governs`, no error. Caller renders as "already
         has governs".
      2. Build a prompt via `build_governs_prompt(doc.body)`.
      3. Call `litellm.completion(...)` with `temperature=0`,
         `response_format={"type":"json_object"}`, 60s timeout.
      4. Parse the response. Drop entries that fail the same validation rules
         enforced by `DocFrontmatter.governs_syntax` + SPEC-004's
         `validate_governs_paths`.
      5. Split the survivors into `verified_paths` (exist on disk) and
         `unverified_paths` (don't exist — kept but flagged).
      6. On any exception (litellm error, JSON parse error, network), catch
         and stash the message on `error`. The batch keeps going.
    """
    import litellm  # local import — keep the litellm dep out of the cold path

    from decree.migrate_prompts import build_governs_prompt

    results: list[SuggestionResult] = []
    for doc in docs:
        doc_path = _display_path(doc.path)
        current = tuple(doc.meta.governs or ())
        if current:
            results.append(
                SuggestionResult(
                    doc_id=doc.doc_id,
                    doc_path=doc_path,
                    current_governs=current,
                    proposed_governs=(),
                    confidence="",
                    rationale="already has governs; skipped",
                    verified_paths=(),
                    unverified_paths=(),
                    error=None,
                )
            )
            continue

        prompt = build_governs_prompt(doc.body or "")
        try:
            response = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                response_format={"type": "json_object"},
                timeout=60,
            )
            content = response.choices[0].message.content
            payload = _parse_llm_json(content)
        except Exception as e:  # noqa: BLE001 — per-doc isolation by design
            results.append(
                SuggestionResult(
                    doc_id=doc.doc_id,
                    doc_path=doc_path,
                    current_governs=current,
                    proposed_governs=(),
                    confidence="",
                    rationale="",
                    verified_paths=(),
                    unverified_paths=(),
                    error=f"{type(e).__name__}: {e}",
                )
            )
            continue

        raw_paths = payload.get("governs", []) if isinstance(payload, dict) else []
        confidence = payload.get("confidence", "") if isinstance(payload, dict) else ""
        rationale = payload.get("rationale", "") if isinstance(payload, dict) else ""
        if not isinstance(raw_paths, list):
            raw_paths = []
        cleaned: list[str] = []
        for entry in raw_paths:
            v = _validate_governs_entry(entry)
            if v is not None:
                cleaned.append(v)

        verified: list[str] = []
        unverified: list[str] = []
        for entry in cleaned:
            path_part = entry.split("#", 1)[0]
            if (project_root / path_part).exists():
                verified.append(entry)
            else:
                unverified.append(entry)

        results.append(
            SuggestionResult(
                doc_id=doc.doc_id,
                doc_path=doc_path,
                current_governs=current,
                proposed_governs=tuple(cleaned),
                confidence=str(confidence) if confidence is not None else "",
                rationale=str(rationale) if rationale is not None else "",
                verified_paths=tuple(verified),
                unverified_paths=tuple(unverified),
                error=None,
            )
        )
    return results


def _suggestion_diff(
    doc_full_path: Path, suggestion: SuggestionResult
) -> str:
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

    Suggestions with empty `proposed_governs` (skipped or LLM-errored) are
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
            reason = (
                "already has governs"
                if s.current_governs
                else "LLM proposed no paths"
            )
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
        except Exception as e:  # noqa: BLE001 — per-doc isolation
            results.append(
                ApplyResult(
                    doc_id=s.doc_id,
                    doc_path=s.doc_path,
                    wrote=False,
                    error=f"{type(e).__name__}: {e}",
                )
            )
    return results


# ─── model resolution ─────────────────────────────────────────────────────


def resolve_model(args: argparse.Namespace) -> str:
    """Pick an LLM model string from --model, env, or provider defaults.

    Priority:
      1. `args.model` if non-empty.
      2. `DECREE_LLM_MODEL` env var.
      3. `ANTHROPIC_API_KEY` set → `claude-3-5-sonnet-latest`.
      4. `OPENAI_API_KEY` set → `gpt-4o-mini`.
      5. Else: SystemExit(2) with a clear error.

    No validation that the model string is well-formed; litellm will surface
    that at call time with a clear message.
    """
    explicit = getattr(args, "model", None)
    if explicit:
        return str(explicit)
    env_model = os.environ.get("DECREE_LLM_MODEL")
    if env_model:
        return env_model
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude-3-5-sonnet-latest"
    if os.environ.get("OPENAI_API_KEY"):
        return "gpt-4o-mini"
    raise SystemExit(
        "decree migrate governs: no model resolved. Pass --model, set "
        "DECREE_LLM_MODEL, or export ANTHROPIC_API_KEY / OPENAI_API_KEY."
    )


# ─── governs CLI handler ──────────────────────────────────────────────────


def _filter_docs_for_suggest(
    all_docs: list, only: list[str] | None
) -> list:
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
            "stdin is not a TTY; refuse to apply without --yes. "
            "Re-run with --yes for non-interactive use.",
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


def _format_suggestions_human(
    suggestions: list[SuggestionResult], project_root: Path
) -> str:
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
            out.append(
                f"# {s.doc_id} ({s.doc_path}): already has governs; skipped"
            )
            out.append("")
            continue
        if not s.proposed_governs:
            out.append(
                f"# {s.doc_id} ({s.doc_path}): LLM proposed no paths"
            )
            if s.rationale:
                out.append(f"# rationale: {s.rationale}")
            out.append("")
            continue
        out.append(f"# {s.doc_id} ({s.doc_path})")
        out.append(f"# confidence: {s.confidence or 'unknown'}")
        if s.rationale:
            out.append(f"# rationale: {s.rationale}")
        if s.unverified_paths:
            out.append(
                "# unverified paths (don't exist on disk): "
                + ", ".join(s.unverified_paths)
            )
        full_path = project_root / s.doc_path
        if not full_path.exists():
            matches = list(project_root.glob(f"**/{Path(s.doc_path).name}"))
            if matches:
                full_path = matches[0]
        try:
            diff = _suggestion_diff(full_path, s)
            out.append(diff)
        except Exception as e:  # noqa: BLE001
            out.append(f"# (could not render diff: {e})")
        out.append("")
    return "\n".join(out)


def suggest_governs_run(args: argparse.Namespace) -> int:
    """`decree migrate governs --suggest [--apply]` — CLI entrypoint.

    v1 merges suggest + apply into a single handler: --suggest emits the
    diff, --apply (which requires --suggest semantically) then optionally
    writes it. Exit codes per SPEC-011:
      0 — clean run, with or without --apply.
      1 — at least one doc errored, batch continued.
      2 — config error (no API key, no docs).
    """
    try:
        root = _resolve_root(getattr(args, "project", None))
    except FileNotFoundError as e:
        fail(str(e))
        return 2

    try:
        model = resolve_model(args)
    except SystemExit as e:
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
        all_docs = load_all_types(strict=False)
    finally:
        os.chdir(cwd_before)

    only = getattr(args, "only", None) or None
    docs = _filter_docs_for_suggest(all_docs, only)
    if not docs:
        fail(
            "no documents matched --only filter"
            if only
            else "no documents in corpus"
        )
        return 2

    suggestions = suggest_governs(docs, model, root)

    apply_results: list[ApplyResult] | None = None
    do_apply = bool(getattr(args, "apply", False))
    dry_run = bool(getattr(args, "dry_run", False))
    yes = bool(getattr(args, "yes", False))
    as_json = bool(getattr(args, "json", False))

    if as_json:
        payload = {
            "model": model,
            "suggestions": [_suggestion_to_dict(s) for s in suggestions],
            "apply": None,
        }
        if do_apply:
            # In JSON mode we never prompt; --yes is required for apply.
            if not yes:
                fail(
                    "--apply in --json mode requires --yes (no interactive prompt)"
                )
                payload["error"] = "apply refused: --yes required in --json mode"
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 2
            apply_results = apply_governs(
                suggestions, root, dry_run=dry_run
            )
            payload["apply"] = [_apply_to_dict(a) for a in apply_results]
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_format_suggestions_human(suggestions, root))
        if do_apply:
            has_changes = any(
                s.proposed_governs and not s.error for s in suggestions
            )
            if not has_changes:
                info("migrate-governs", "no changes to apply.")
            else:
                if _confirm_apply(yes):
                    apply_results = apply_governs(
                        suggestions, root, dry_run=dry_run
                    )
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

    # Exit-code policy: any LLM error → 1; otherwise 0.
    errored = [s for s in suggestions if s.error]
    if apply_results is not None:
        errored_apply = [a for a in apply_results if a.error]
        if errored_apply:
            return 1
    if errored:
        return 1
    return 0


def apply_governs_run(args: argparse.Namespace) -> int:
    """Thin alias — `--apply` is a flag on the suggest handler, not its own
    subcommand. This exists for symmetry with the SPEC's library-API naming
    so future SPECs can wire it differently if they want.
    """
    setattr(args, "apply", True)
    return suggest_governs_run(args)
