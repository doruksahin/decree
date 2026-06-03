"""`decree init` — deterministic, idempotent project scaffolder.

Takes a target directory from zero to a working, lint-clean decree corpus in
one run: a canonical ``decree.toml``, the ``decree/<type>/`` directories, a
worked PRD->ADR->SPEC example chain, and a built ``.decree/index.sqlite``.

Design rules:

- **Never overwrites.** Anything already present is left untouched and reported
  with a reason.
- **Pure planning is separated from IO** so ``--dry-run`` is trivial and the
  planning logic is testable without touching disk.
- **No new dependency, no schema change.** The canonical config and the example
  chain are bundled assets under ``src/decree/templates/init/`` (same
  package-data access pattern as ``commands/new.py``), authored to be mutually
  consistent so the scaffolded project lints clean immediately.

See ``docs/plans/2026-06-04-decree-init.md`` /
``docs/plans/2026-06-04-decree-init-design.md``.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from decree.log import error, info, success, warn

try:  # Python 3.11+ ships tomllib; tomli is the backport elsewhere.
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

# Same access pattern as commands/new.py: bundled package data.
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
INIT_DIR = TEMPLATE_DIR / "init"
BUNDLED_CONFIG = INIT_DIR / "decree.toml"

# The canonical type trio, in chain order.
_TYPES: tuple[str, ...] = ("prd", "adr", "spec")

PREFIX = "init"


@dataclass
class Action:
    """One planned (or applied) scaffolding step.

    kind:   "config" | "dir" | "example" | "index"
    path:   the on-disk target the step concerns
    action: planning verbs — "create" / "skip" for real files; "rebuild" for the
            derived index cache. apply_init upgrades these to "created" /
            "skipped" / "rebuilt"; the dry-run path normalizes them to
            "would-create" / "would-rebuild" for the report/JSON contract.
    reason: why a step is skipped (or other accountable detail), else None
    """

    kind: str
    path: Path
    action: str
    reason: str | None = None


@dataclass
class Applied:
    """Outcome of executing a plan."""

    actions: list[Action] = field(default_factory=list)
    created: int = 0
    skipped: int = 0


# ── helpers ─────────────────────────────────────────────────


def _declared_types(config_path: Path) -> list[str]:
    """Return the type names declared in an existing decree.toml (best-effort)."""
    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return []
    types = data.get("types")
    if not isinstance(types, dict):
        return []
    return list(types.keys())


def _bundled_example(type_name: str) -> Path | None:
    """The single bundled example doc for a type, or None if absent."""
    matches = sorted((INIT_DIR / type_name).glob("*.md"))
    return matches[0] if matches else None


def _dir_has_docs(type_dir: Path) -> bool:
    """True if the type dir exists and contains at least one (non-index) doc."""
    if not type_dir.is_dir():
        return False
    return any(p.name != "index.md" for p in type_dir.glob("*.md"))


# ── planning (pure: reads disk to decide, writes nothing) ───


def plan_init(target: Path) -> list[Action]:
    """Plan the scaffolding for ``target`` without touching disk.

    Rules:
    - decree.toml present -> skip ("exists; types: ..."); absent -> create.
    - type dir present -> skip; absent -> create.
    - example doc -> create only if its type dir is empty/absent; if the type
      dir already has docs -> skip ("decree/<type>/ already has documents").
    - index -> rebuild (a derived cache refresh, performed by apply_init unless
      --dry-run; it is never counted as a "creation").
    """
    target = Path(target)
    plan: list[Action] = []

    # 1. config
    config_path = target / "decree.toml"
    if config_path.exists():
        types = _declared_types(config_path)
        types_str = ", ".join(types) if types else "none"
        plan.append(Action("config", config_path, "skip", f"exists; types: {types_str}"))
    else:
        plan.append(Action("config", config_path, "create", None))

    # 2. type directories
    for type_name in _TYPES:
        type_dir = target / "decree" / type_name
        if type_dir.is_dir():
            plan.append(Action("dir", type_dir, "skip", "already exists"))
        else:
            plan.append(Action("dir", type_dir, "create", None))

    # 3. example docs (one per type), seeded only into empty/absent type dirs
    for type_name in _TYPES:
        type_dir = target / "decree" / type_name
        src = _bundled_example(type_name)
        if src is None:  # pragma: no cover - bundled assets are always present
            continue
        dest = type_dir / src.name
        if _dir_has_docs(type_dir):
            plan.append(
                Action(
                    "example",
                    dest,
                    "skip",
                    f"decree/{type_name}/ already has documents",
                )
            )
        else:
            plan.append(Action("example", dest, "create", None))

    # 4. index — a derived cache refresh, not a creation.
    plan.append(Action("index", target / ".decree" / "index.sqlite", "rebuild", None))

    return plan


# ── apply (executes a plan; never overwrites) ───────────────


def _rebuild_index(target: Path) -> None:
    """Rebuild .decree/index.sqlite for ``target`` via the index machinery.

    rebuild_run chdir's into the target; we restore cwd afterward so callers
    (and tests) are not left in a surprising directory.

    The index command writes its own ``[index] …`` chatter to stderr (and would
    print to stdout); we capture both into throwaway buffers so init owns a
    clean, top-to-bottom report with no interleaved/leaked index lines.
    """
    from decree.commands import index_db_cli

    cwd = Path.cwd()
    sink = io.StringIO()
    try:
        with contextlib.redirect_stderr(sink), contextlib.redirect_stdout(sink):
            index_db_cli.rebuild_run(argparse.Namespace(project=str(target)))
    finally:
        os.chdir(cwd)
        # rebuild_run cleared these caches against the target; clear again so
        # the restored cwd is reflected for any subsequent in-process calls.
        from decree.config import get_project_root, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()


def apply_init(plan: list[Action], *, no_examples: bool) -> Applied:
    """Execute a plan: write config, mkdir dirs, copy examples, rebuild index.

    Never overwrites an existing file. Returns counts + the resolved per-action
    outcomes ("created" / "skipped" / "rebuilt"). The ``created`` and ``skipped``
    counts cover only real file/dir work (config, dirs, examples); the index is
    a derived cache refresh reported as "rebuilt" and excluded from both counts.
    """
    result = Applied()
    target: Path | None = None

    for step in plan:
        if step.action == "skip":
            result.actions.append(Action(step.kind, step.path, "skipped", step.reason))
            result.skipped += 1
            continue

        if step.kind == "config":
            target = step.path.parent
            if not step.path.exists():
                shutil.copyfile(BUNDLED_CONFIG, step.path)
            result.actions.append(Action("config", step.path, "created", None))
            result.created += 1

        elif step.kind == "dir":
            step.path.mkdir(parents=True, exist_ok=True)
            result.actions.append(Action("dir", step.path, "created", None))
            result.created += 1

        elif step.kind == "example":
            if no_examples:
                result.actions.append(Action("example", step.path, "skipped", "--no-examples"))
                result.skipped += 1
                continue
            src = _bundled_example(step.path.parent.name)
            step.path.parent.mkdir(parents=True, exist_ok=True)
            if src is not None and not step.path.exists():
                shutil.copyfile(src, step.path)
            result.actions.append(Action("example", step.path, "created", None))
            result.created += 1

        elif step.kind == "index":
            if target is None:
                target = step.path.parent.parent
            _rebuild_index(target)
            # The index is a derived cache refresh, not a creation: report it as
            # "rebuilt" and keep it out of the created/skipped counts.
            result.actions.append(Action("index", step.path, "rebuilt", None))

    return result


# ── reporting + CLI ─────────────────────────────────────────


def _resolve_target(args: argparse.Namespace) -> Path:
    project = getattr(args, "project", None)
    return Path(project).resolve() if project else Path.cwd().resolve()


def _is_git_repo(target: Path) -> bool:
    return (target / ".git").exists()


def _json_action(a: Action) -> dict:
    """Map an internal action to the stable JSON contract entry.

    Raw plan steps use "create"/"skip"/"rebuild" (dry-run path); applied steps
    use "created"/"skipped"/"rebuilt". Normalize both to the machine vocabulary
    created | skipped | would-create | rebuilt | would-rebuild.
    """
    machine = {
        "create": "would-create",  # only seen in a dry-run plan
        "skip": "skipped",
        "rebuild": "would-rebuild",  # index, dry-run plan only
        "created": "created",
        "skipped": "skipped",
        "rebuilt": "rebuilt",
        "would-create": "would-create",
        "would-rebuild": "would-rebuild",
    }.get(a.action, a.action)
    return {
        "kind": a.kind,
        "path": str(a.path),
        "action": machine,
        "reason": a.reason,
    }


def _print_human_report(
    target: Path,
    actions: list[Action],
    *,
    created: int,
    skipped: int,
    git: bool,
    dry_run: bool,
) -> None:
    """Sectioned, accountable report on stderr (via log.py)."""

    def _shown(a: Action) -> Path | str:
        try:
            return a.path.relative_to(target)
        except ValueError:
            return a.path

    def line(a: Action) -> None:
        if a.action in ("rebuilt", "would-rebuild", "rebuild"):
            # The index: a derived cache refresh, never "created".
            label = "would rebuild" if dry_run else "rebuilt"
            success(f"{label} {_shown(a)}")
        elif a.action in ("created", "would-create", "create"):
            label = "would create" if dry_run else "created"
            success(f"{label} {_shown(a)}")
        else:  # skipped
            reason = f" — {a.reason}" if a.reason else ""
            info(PREFIX, f"skipped {_shown(a)}{reason}")

    info(PREFIX, f"decree init — {target}{'  (dry run)' if dry_run else ''}")

    sections = [
        ("Config", "config"),
        ("Directories", "dir"),
        ("Examples", "example"),
        ("Index", "index"),
    ]
    for title, kind in sections:
        members = [a for a in actions if a.kind == kind]
        if not members:
            continue
        info(PREFIX, f"{title}:")
        for a in members:
            line(a)

    if not dry_run and created == 0:
        # Nothing real was created; the index was still refreshed.
        info(PREFIX, "Already initialized — nothing to create (index refreshed).")
    else:
        summary_verb = "Would create" if dry_run else "Created"
        info(PREFIX, f"{summary_verb} {created}, skipped {skipped} (already present).")

    if not git:
        warn(
            PREFIX,
            "not a git repo — health/commit signals unavailable until you `git init`.",
        )

    info(PREFIX, "Next: decree lint · decree why <file>")


def run(args: argparse.Namespace) -> int:
    """`decree init` entry point."""
    target = _resolve_target(args)
    dry_run = bool(getattr(args, "dry_run", False))
    no_examples = bool(getattr(args, "no_examples", False))
    as_json = bool(getattr(args, "json", False))

    if not target.exists():
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            error(PREFIX, f"cannot create target {target}: {e}")
            return 2

    git = _is_git_repo(target)

    try:
        plan = plan_init(target)
        if dry_run:
            actions = plan  # raw "create"/"skip" plan; nothing touched on disk
            created = sum(1 for a in actions if a.action == "create")
            skipped = sum(1 for a in actions if a.action == "skip")
        else:
            applied = apply_init(plan, no_examples=no_examples)
            actions = applied.actions
            created = applied.created
            skipped = applied.skipped
    except OSError as e:
        error(PREFIX, f"IO error during init: {e}")
        return 2
    except Exception as e:  # malformed bundled template, config error, etc.
        error(PREFIX, f"init failed: {e}")
        return 2

    if as_json:
        payload = {
            "target": str(target),
            "actions": [_json_action(a) for a in actions],
            "summary": {"created": created, "skipped": skipped},
            "git": git,
            "dry_run": dry_run,
            "exit": 0,
        }
        print(json.dumps(payload, indent=2), file=sys.stdout)
    else:
        _print_human_report(
            target,
            actions,
            created=created,
            skipped=skipped,
            git=git,
            dry_run=dry_run,
        )

    return 0
