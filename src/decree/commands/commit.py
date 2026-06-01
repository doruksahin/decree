"""`decree commit` — git commit wrapper that adds structural trailers.

Implements SPEC-01KT22NMRY8YK9RP4323KX4RQG R1. Wraps `git commit`, inspecting the staged diff,
optionally inferring the active SPEC from the `governs:` table, and
prepending `Implements:` / `Refs:` / `Fixes:` trailers via the canonical
`git interpret-trailers` plumbing.

Design notes:
  * We never re-implement trailer parsing or formatting in Python.
    Both add (`git interpret-trailers --in-place ...`) and parse
    (`git interpret-trailers --parse`) shell out to git itself.
  * Inference is opt-out (`--no-infer`) and overridable
    (`--implements SPEC-<ULID> ...`). Ambiguous matches refuse to guess.
  * Post-commit we trigger `IndexDB.sync_commits_from_git()` so that
    `decree refs SPEC-<ULID>` reflects the new commit immediately.
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from decree.commands.queries import _resolve_root, _status_priority
from decree.identity import require_doc_id
from decree.index_db import IndexDB, default_db_path
from decree.log import error, info, success


@dataclass(frozen=True)
class InferenceCandidate:
    """One candidate produced by active-SPEC inference."""

    decision_id: str
    type: str
    status: str
    unchecked_acs: int
    matched_paths: tuple[str, ...]


# ── git plumbing helpers ────────────────────────────────────


def _git(
    project_root: Path, *args: str, check: bool = False, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run `git -C <root> <args>` and return the CompletedProcess."""
    return subprocess.run(
        ["git", "-C", str(project_root), *args],
        capture_output=True,
        text=True,
        check=check,
        input=input_text,
    )


def _staged_files(project_root: Path) -> list[str]:
    """Return staged file paths (rel to repo root)."""
    result = _git(project_root, "diff", "--cached", "--name-only")
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


# ── trailer arg construction ────────────────────────────────


def build_trailers_arg(
    implements: list[str] | None,
    refs: list[str] | None,
    fixes: list[str] | None,
) -> list[str]:
    """Return the `--trailer "<Kind>: <ID>"` flags for `git interpret-trailers`.

    One flag per ID (multi-value trailers as separate lines — that's how
    git canonicalizes them on `--parse`).
    """
    out: list[str] = []
    for spec_id in implements or []:
        out.extend(["--trailer", f"Implements: {require_doc_id(spec_id)}"])
    for ref_id in refs or []:
        out.extend(["--trailer", f"Refs: {require_doc_id(ref_id)}"])
    for fix_id in fixes or []:
        out.extend(["--trailer", f"Fixes: {require_doc_id(fix_id)}"])
    return out


def _validated_ids(values: list[str] | None, *, flag: str) -> list[str]:
    """Normalize CLI-supplied document IDs and fail before invoking git."""
    try:
        return [require_doc_id(value) for value in values or []]
    except ValueError as exc:
        raise ValueError(f"{flag}: {exc}") from exc


def apply_trailers(project_root: Path, message: str, trailers: list[str]) -> str:
    """Run `git interpret-trailers --in-place` over `message` and return the result.

    `trailers` is the flag list produced by `build_trailers_arg`. If
    empty, returns `message` unchanged (no temp file, no subprocess —
    `git interpret-trailers` with no `--trailer` flags is a no-op
    anyway, but skipping the round-trip is cleaner).
    """
    if not trailers:
        return message

    # `git interpret-trailers` operates on a file (or stdin). The
    # `--in-place` form is the documented way to add trailers without
    # mangling pre-existing ones, and `--if-exists addIfDifferent`
    # avoids duplicating an `Implements:` the user already wrote.
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".COMMIT_EDITMSG",
        delete=False,
        dir=str(project_root),
        encoding="utf-8",
    ) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(message)
        if not message.endswith("\n"):
            tmp.write("\n")

    try:
        result = _git(
            project_root,
            "interpret-trailers",
            "--in-place",
            "--if-exists",
            "addIfDifferent",
            *trailers,
            str(tmp_path),
        )
        if result.returncode != 0:
            # git printed something useful on stderr; surface it.
            raise RuntimeError(f"git interpret-trailers failed: {result.stderr.strip()}")
        return tmp_path.read_text(encoding="utf-8")
    finally:
        with suppress(FileNotFoundError):
            tmp_path.unlink()


# ── active-SPEC inference ───────────────────────────────────


def infer_active_spec(
    db: IndexDB,
    staged_files: list[str],
) -> str | None | list[InferenceCandidate]:
    """Pick the SPEC most likely being worked on, based on staged files.

    Returns:
      * `None` — no SPEC's `governs:` paths intersect the staged set.
      * `str` (decision_id) — a unique non-terminal-status SPEC matched.
      * `list[InferenceCandidate]` — multiple SPECs tied; caller should
        print these and require explicit `--implements`.

    Matching mirrors `decree why`: exact path match wins over directory
    prefix match. Among the survivors we keep SPECs only (the convention
    in PRD-01KT22NMRS4QGHSFDBZ858PP1T R4 — `Implements:` binds to SPEC, not PRD/ADR), filter
    out terminal statuses, and tie-break on number of unchecked ACs
    (more unchecked → more "in-flight").
    """
    if not staged_files:
        return None

    conn = db.db.conn  # type: ignore[attr-defined]

    # Collect candidate decision_ids per staged file (exact + prefix).
    matched_paths_by_spec: dict[str, set[str]] = {}

    for staged in staged_files:
        # Exact match on `governs.path`.
        for row in conn.execute(
            "SELECT g.decision_id, g.path, d.type FROM governs g "
            "JOIN decisions d ON d.id = g.decision_id "
            "WHERE g.path = ? AND d.type = 'spec'",
            (staged,),
        ):
            decision_id, gpath, _ = row
            matched_paths_by_spec.setdefault(decision_id, set()).add(gpath)

        # Directory-prefix match: governs.path ends with '/' and staged path starts with it.
        for row in conn.execute(
            "SELECT g.decision_id, g.path, d.type FROM governs g "
            "JOIN decisions d ON d.id = g.decision_id "
            "WHERE substr(g.path, -1) = '/' AND ? LIKE g.path || '%' AND d.type = 'spec'",
            (staged,),
        ):
            decision_id, gpath, _ = row
            # Prefer exact match: don't overwrite if already matched.
            matched_paths_by_spec.setdefault(decision_id, set()).add(gpath)

    if not matched_paths_by_spec:
        return None

    # Hydrate candidates with status + unchecked-AC counts; filter to active (priority 1).
    candidates: list[InferenceCandidate] = []
    for decision_id, paths in matched_paths_by_spec.items():
        meta_row = next(
            conn.execute(
                "SELECT id, type, status FROM decisions WHERE id = ?",
                (decision_id,),
            ),
            None,
        )
        if meta_row is None:
            continue
        _, type_name, status = meta_row
        if _status_priority(type_name, status) != 1:
            # Skip terminal-success (0) and warn-on-reference (2).
            continue
        unchecked_row = next(
            conn.execute(
                "SELECT COUNT(*) FROM acceptance_criteria WHERE decision_id = ? AND done = 0 AND deferred = 0",
                (decision_id,),
            ),
            (0,),
        )
        candidates.append(
            InferenceCandidate(
                decision_id=decision_id,
                type=type_name,
                status=status,
                unchecked_acs=int(unchecked_row[0]),
                matched_paths=tuple(sorted(paths)),
            )
        )

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0].decision_id

    # Tie-break on unchecked ACs (descending). If still tied, return the
    # full list so the caller can refuse to guess.
    candidates.sort(key=lambda c: (-c.unchecked_acs, c.decision_id))
    top = candidates[0]
    if len(candidates) > 1 and candidates[1].unchecked_acs == top.unchecked_acs:
        return candidates

    return top.decision_id


# ── commit_run ──────────────────────────────────────────────


def _format_candidates(candidates: list[InferenceCandidate]) -> str:
    """Pretty list of ambiguous candidates for the user to disambiguate."""
    lines = ["Ambiguous active-SPEC inference — multiple candidates tied:"]
    for c in candidates:
        paths = ", ".join(c.matched_paths) if c.matched_paths else "(no path matches)"
        lines.append(f"  {c.decision_id}  status={c.status}  unchecked_acs={c.unchecked_acs}  paths=[{paths}]")
    lines.append("Re-run with `--implements <SPEC-ID>` to disambiguate, or `--no-infer` to skip.")
    return "\n".join(lines)


def commit_run(args: argparse.Namespace) -> int:
    """`decree commit` entry point."""
    try:
        root = _resolve_root(getattr(args, "project", None))
    except FileNotFoundError as e:
        error("commit", str(e))
        return 1

    # The wrapper is git-only — non-git projects make no sense here.
    git_check = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if git_check.returncode != 0:
        error("commit", f"not a git repository: {root}")
        return 1

    try:
        implements: list[str] = _validated_ids(args.implements, flag="--implements")
        refs: list[str] = _validated_ids(args.refs, flag="--refs")
        fixes: list[str] = _validated_ids(args.fixes, flag="--fixes")
    except ValueError as exc:
        error("commit", str(exc))
        return 1

    # Pass `--amend` through to git directly; no inference, no message
    # rewriting. The PM can re-add trailers manually via `--implements`
    # on the amend if they really want to. After amend we still re-sync
    # the index so the rewritten SHA replaces the old one.
    if args.amend:
        amend_cmd: list[str] = ["git", "-C", str(root), "commit", "--amend"]
        if args.message:
            # Rewriting the message — apply trailer flags if the user gave any.
            msg = args.message
            trailers = build_trailers_arg(args.implements, args.refs, args.fixes)
            if trailers:
                msg = apply_trailers(root, msg, trailers)
            amend_cmd.extend(["-m", msg])
        rc = subprocess.run(amend_cmd, check=False).returncode
        if rc == 0:
            IndexDB(default_db_path(root)).sync_commits_from_git(root)
        return rc

    # Staged-files check — refuse with a clear error when empty.
    staged = _staged_files(root)
    if not staged:
        error("commit", "no staged changes (run `git add ...` first)")
        return 1

    # Active-SPEC inference: only run if user didn't explicitly pass
    # `--implements`, and `--no-infer` wasn't set.
    if not implements and not args.no_infer:
        db = IndexDB(default_db_path(root))
        idx_status = db.status()
        if idx_status.exists:
            inferred = infer_active_spec(db, staged)
            if isinstance(inferred, list):
                # Tied — refuse to guess.
                print(_format_candidates(inferred))
                return 1
            if isinstance(inferred, str):
                implements.append(inferred)
                info("commit", f"inferred Implements: {inferred} (from staged paths)")
        else:
            error(
                "commit",
                "index not built; run `decree index rebuild`, pass --implements <SPEC-ID>, or use --no-infer",
            )
            return 1

    # Assemble the message.
    message = args.message or ""
    if not message:
        # Defer to git's EDITOR flow — easiest way is to let `git commit`
        # open the editor itself. We add trailers via a prepare-commit-msg
        # path: write a template file, pass `-t <file>`. But the SPEC
        # gives us an out: just refuse and require `-m` for v1. Implement
        # the simpler path: error out if no -m and no trailers (we can't
        # inject trailers into an EDITOR session without a hook).
        # However — if there are no trailers either, just pass through.
        trailers = build_trailers_arg(implements, refs, fixes)
        if not trailers:
            rc = subprocess.run(["git", "-C", str(root), "commit"], check=False).returncode
            if rc == 0:
                IndexDB(default_db_path(root)).sync_commits_from_git(root)
            return rc
        # With trailers but no -m, fall back to a template via -t.
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".COMMIT_EDITMSG.tpl",
            delete=False,
            dir=str(root),
            encoding="utf-8",
        ) as tpl:
            tpl_path = Path(tpl.name)
            # Empty subject — let the user fill it in — then a blank
            # line and the trailers block.
            tpl.write("\n\n")
            for kind, ids in (("Implements", implements), ("Refs", refs), ("Fixes", fixes)):
                for spec_id in ids:
                    tpl.write(f"{kind}: {spec_id}\n")
        try:
            rc = subprocess.run(
                ["git", "-C", str(root), "commit", "-t", str(tpl_path)],
                check=False,
            ).returncode
        finally:
            with suppress(FileNotFoundError):
                tpl_path.unlink()
        if rc == 0:
            IndexDB(default_db_path(root)).sync_commits_from_git(root)
        return rc

    # We have a message. Apply trailers, then commit via -F so we don't
    # have to round-trip the message through the shell.
    trailers = build_trailers_arg(implements, refs, fixes)
    final_message = apply_trailers(root, message, trailers) if trailers else message

    # Write to temp file and `git commit -F`.
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".COMMIT_EDITMSG",
        delete=False,
        dir=str(root),
        encoding="utf-8",
    ) as msg_file:
        msg_path = Path(msg_file.name)
        msg_file.write(final_message)
        if not final_message.endswith("\n"):
            msg_file.write("\n")

    try:
        result = subprocess.run(
            ["git", "-C", str(root), "commit", "-F", str(msg_path)],
            check=False,
        )
    finally:
        with suppress(FileNotFoundError):
            msg_path.unlink()

    if result.returncode == 0:
        rows, ms = IndexDB(default_db_path(root)).sync_commits_from_git(root)
        if rows > 0:
            success(f"commit landed; index synced ({rows} trailer rows, {ms}ms)")
        else:
            success("commit landed")
    return result.returncode
