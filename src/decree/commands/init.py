"""`decree init` — deterministic, idempotent project scaffolder.

Takes a target directory from zero to a working, lint-clean decree corpus in
one run: a canonical ``decree.toml``, the ``decree/<type>/`` directories, a
worked PRD->ADR->SPEC example chain, a ``.gitignore`` rule for the derived
index cache, and a built ``.decree/index.sqlite``.

Design rules:

- **Never overwrites.** Anything already present is left untouched and reported
  with a reason. The only file init ever *modifies* is ``.gitignore`` — and only
  by appending a missing ``.decree/`` rule, never rewriting existing lines.
- **Respects an existing config.** If a ``decree.toml`` is already present, init
  scaffolds *its* declared types (at their configured dirs) rather than imposing
  the default trio — so it never litters a custom corpus with orphan directories.
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
from typing import TYPE_CHECKING

from decree.log import error, info, success, warn

if TYPE_CHECKING:
    from decree.commands.agents import SkillResult

try:  # Python 3.11+ ships tomllib; tomli is the backport elsewhere.
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

# Same access pattern as commands/new.py: bundled package data.
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
INIT_DIR = TEMPLATE_DIR / "init"
BUNDLED_CONFIG = INIT_DIR / "decree.toml"

# The canonical type trio, in chain order (used when no config exists yet).
_TYPES: tuple[str, ...] = ("prd", "adr", "spec")

# The .gitignore rule init ensures: the derived query cache is rebuildable and
# must not be committed (consistent with decree's "index is a derived cache"
# model). Written verbatim when creating .gitignore; appended when missing.
_GITIGNORE_BLOCK = "# decree's derived query cache — rebuild with `decree index rebuild`\n.decree/\n"
# Lines that already satisfy the rule (so we skip rather than double-add).
_DECREE_IGNORE_PATTERNS = {".decree", ".decree/", "/.decree", "/.decree/"}

PREFIX = "init"


@dataclass
class Action:
    """One planned (or applied) scaffolding step.

    kind:   "config" | "dir" | "example" | "gitignore" | "index"
    path:   the on-disk target the step concerns
    action: planning verbs — "create"/"skip" for corpus files; "write"/"append"
            for .gitignore; "rebuild" for the derived index cache. apply_init
            upgrades these to "created"/"skipped"/"wrote"/"appended"/"rebuilt";
            the dry-run path normalizes them to the "would-*" forms for the
            report/JSON contract.
    reason: why a step is skipped (or other accountable detail), else None
    src:    bundled source file to copy (example/config steps); else None
    """

    kind: str
    path: Path
    action: str
    reason: str | None = None
    src: Path | None = None


@dataclass
class Applied:
    """Outcome of executing a plan."""

    actions: list[Action] = field(default_factory=list)
    created: int = 0
    skipped: int = 0


# ── helpers ─────────────────────────────────────────────────


def _load_config(config_path: Path) -> dict | None:
    """Parse an existing decree.toml; None if it cannot be read/parsed."""
    try:
        with config_path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return None


def _config_parse_error(config_path: Path) -> str | None:
    """Return a human message if an existing decree.toml is malformed, else None."""
    try:
        with config_path.open("rb") as f:
            tomllib.load(f)
        return None
    except tomllib.TOMLDecodeError as e:
        return str(e)
    except OSError as e:  # pragma: no cover - unreadable file
        return str(e)


def _declared_type_dirs(config_path: Path) -> dict[str, str]:
    """{type_name: dir} from an existing decree.toml (best-effort; {} on error).

    Falls back to ``decree/<name>`` for a type that omits an explicit ``dir``.
    """
    data = _load_config(config_path)
    if data is None:
        return {}
    types = data.get("types")
    if not isinstance(types, dict):
        return {}
    out: dict[str, str] = {}
    for name, spec in types.items():
        if isinstance(spec, dict) and isinstance(spec.get("dir"), str):
            out[name] = spec["dir"]
        else:
            out[name] = f"decree/{name}"
    return out


def _declared_types(config_path: Path) -> list[str]:
    """Type names declared in an existing decree.toml (best-effort)."""
    return list(_declared_type_dirs(config_path).keys())


def _effective_types(target: Path, config_path: Path) -> list[tuple[str, Path]]:
    """The (type_name, type_dir) pairs init should scaffold.

    - config absent -> the bundled trio at ``decree/<type>/`` (init writes that
      canonical config, so the dirs and examples match it).
    - config present -> the types *it* declares, at their configured dirs. This
      respects an existing corpus instead of imposing the default trio (and so
      never creates orphan ``decree/prd|adr|spec`` dirs in a custom project).
    """
    if not config_path.exists():
        return [(t, target / "decree" / t) for t in _TYPES]
    return [(name, target / dir_) for name, dir_ in _declared_type_dirs(config_path).items()]


def _bundled_example(type_name: str) -> Path | None:
    """The single bundled example doc for a type, or None if absent."""
    matches = sorted((INIT_DIR / type_name).glob("*.md"))
    return matches[0] if matches else None


def _dir_has_docs(type_dir: Path) -> bool:
    """True if the type dir exists and contains at least one (non-index) doc."""
    if not type_dir.is_dir():
        return False
    return any(p.name != "index.md" for p in type_dir.glob("*.md"))


def _rel(path: Path, base: Path) -> Path | str:
    """``path`` relative to ``base`` for display, falling back to the absolute."""
    try:
        return path.relative_to(base)
    except ValueError:
        return path


def _ignores_decree(text: str) -> bool:
    """True if a .gitignore body already ignores the ``.decree/`` cache dir."""
    return any(line.strip() in _DECREE_IGNORE_PATTERNS for line in text.splitlines())


# ── planning (pure: reads disk to decide, writes nothing) ───


def plan_init(target: Path) -> list[Action]:
    """Plan the scaffolding for ``target`` without touching disk.

    Rules:
    - decree.toml present -> skip ("exists; types: ..."); absent -> create.
    - type dir present -> skip; absent -> create. Types come from an existing
      config when present, else the canonical trio.
    - example doc -> create only if a bundled example exists for the type and its
      type dir is empty/absent; a non-empty dir -> skip ("... already has
      documents"). Custom types with no bundled example get a dir but no example.
    - .gitignore -> ensure the derived ``.decree/`` cache is ignored (create the
      file, or append the rule if missing; skip if already covered).
    - index -> rebuild (a derived cache refresh, performed by apply_init unless
      --dry-run; it is never counted as a "creation").
    """
    target = Path(target)
    plan: list[Action] = []

    # 1. config
    config_path = target / "decree.toml"
    config_exists = config_path.exists()
    if config_exists:
        types = _declared_types(config_path)
        types_str = ", ".join(types) if types else "none"
        plan.append(Action("config", config_path, "skip", f"exists; types: {types_str}"))
    else:
        plan.append(Action("config", config_path, "create", None, src=BUNDLED_CONFIG))

    effective = _effective_types(target, config_path)

    # 2. type directories
    for _type_name, type_dir in effective:
        if type_dir.is_dir():
            plan.append(Action("dir", type_dir, "skip", "already exists"))
        else:
            plan.append(Action("dir", type_dir, "create", None))

    # 3. example docs — only for types we ship an example for, seeded only into
    #    empty/absent dirs. A custom type (no bundled example) gets its dir but no
    #    doc, so init never plants an orphan it cannot make lint clean.
    for type_name, type_dir in effective:
        src = _bundled_example(type_name)
        if src is None:
            continue
        dest = type_dir / src.name
        if _dir_has_docs(type_dir):
            plan.append(Action("example", dest, "skip", f"{_rel(type_dir, target)}/ already has documents"))
        else:
            plan.append(Action("example", dest, "create", None, src=src))

    # 4. .gitignore — keep the derived index cache out of version control.
    plan.append(_plan_gitignore(target))

    # 5. index — a derived cache refresh, not a creation.
    plan.append(Action("index", target / ".decree" / "index.sqlite", "rebuild", None))

    return plan


def _plan_gitignore(target: Path) -> Action:
    """Plan the .gitignore step: create, append, or skip."""
    gi = target / ".gitignore"
    if not gi.exists():
        return Action("gitignore", gi, "write", "ignore .decree/ (derived cache)")
    try:
        text = gi.read_text(encoding="utf-8", errors="ignore")
    except OSError:  # pragma: no cover - unreadable file; treat as needing the rule
        text = ""
    if _ignores_decree(text):
        return Action("gitignore", gi, "skip", ".decree/ already ignored")
    return Action("gitignore", gi, "append", "add .decree/ (derived cache)")


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
    """Execute a plan: write config, mkdir dirs, copy examples, ensure
    .gitignore, rebuild index.

    Never overwrites an existing file (it only ever *appends* to .gitignore).
    Returns counts + the resolved per-action outcomes. The ``created`` and
    ``skipped`` counts cover only the corpus (config, dirs, examples); the
    .gitignore and index are infrastructure side-effects, reported with their
    own verbs and excluded from both counts.
    """
    result = Applied()
    target: Path | None = None

    for step in plan:
        # Generic skip — counts only toward the corpus summary.
        if step.action == "skip":
            result.actions.append(Action(step.kind, step.path, "skipped", step.reason))
            if step.kind in ("config", "dir", "example"):
                result.skipped += 1
            continue

        if step.kind == "config":
            target = step.path.parent
            if step.path.exists():  # appeared between plan and apply — never clobber
                result.actions.append(Action("config", step.path, "skipped", "already present"))
                result.skipped += 1
            else:
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
            if step.path.exists():  # appeared between plan and apply — never clobber
                result.actions.append(Action("example", step.path, "skipped", "already present"))
                result.skipped += 1
                continue
            step.path.parent.mkdir(parents=True, exist_ok=True)
            if step.src is not None:
                shutil.copyfile(step.src, step.path)
            result.actions.append(Action("example", step.path, "created", None))
            result.created += 1

        elif step.kind == "gitignore":
            _apply_gitignore(step, result)

        elif step.kind == "index":
            if target is None:
                target = step.path.parent.parent
            _rebuild_index(target)
            # A derived cache refresh, not a creation: report "rebuilt" and keep
            # it out of the created/skipped counts.
            result.actions.append(Action("index", step.path, "rebuilt", None))

    return result


def _apply_gitignore(step: Action, result: Applied) -> None:
    """Ensure ``.decree/`` is git-ignored.

    Robust to the plan->apply race: it acts on the *actual* on-disk state rather
    than trusting the planned verb, and never rewrites existing lines (it only
    creates a new file or appends). So a ``.gitignore`` that materializes after
    planning is appended to — never clobbered.
    """
    gi = step.path
    if not gi.exists():
        gi.write_text(_GITIGNORE_BLOCK, encoding="utf-8")
        result.actions.append(Action("gitignore", gi, "wrote", "ignore .decree/ (derived cache)"))
        return

    existing = gi.read_text(encoding="utf-8", errors="ignore")
    if _ignores_decree(existing):  # already covered (incl. a rule that raced in)
        result.actions.append(Action("gitignore", gi, "skipped", ".decree/ already ignored"))
        return

    # Pure append: keep every existing byte, separated by exactly one blank line.
    if existing == "" or existing.endswith("\n\n"):
        sep = ""
    elif existing.endswith("\n"):
        sep = "\n"
    else:
        sep = "\n\n"
    gi.write_text(existing + sep + _GITIGNORE_BLOCK, encoding="utf-8")
    result.actions.append(Action("gitignore", gi, "appended", "add .decree/ (derived cache)"))


# ── reporting + CLI ─────────────────────────────────────────


def _resolve_target(args: argparse.Namespace) -> Path:
    project = getattr(args, "project", None)
    return Path(project).resolve() if project else Path.cwd().resolve()


def _is_git_repo(target: Path) -> bool:
    return (target / ".git").exists()


def _json_action(a: Action) -> dict:
    """Map an internal action to the stable JSON contract entry.

    Raw plan steps use the planning verbs (dry-run path); applied steps use the
    past-tense verbs. Normalize both to the machine vocabulary:
    created | skipped | would-create | wrote | would-write | appended |
    would-append | rebuilt | would-rebuild.
    """
    machine = {
        "create": "would-create",  # only seen in a dry-run plan
        "skip": "skipped",
        "write": "would-write",  # .gitignore, dry-run plan only
        "append": "would-append",  # .gitignore, dry-run plan only
        "rebuild": "would-rebuild",  # index, dry-run plan only
        "created": "created",
        "skipped": "skipped",
        "wrote": "wrote",
        "appended": "appended",
        "rebuilt": "rebuilt",
        "would-create": "would-create",
        "would-write": "would-write",
        "would-append": "would-append",
        "would-rebuild": "would-rebuild",
        "installed": "installed",
        "updated": "updated",
        "unchanged": "unchanged",
        "would-install": "would-install",
        "would-update": "would-update",
        "would-keep": "would-keep",
    }.get(a.action, a.action)
    return {
        "kind": a.kind,
        "path": str(a.path),
        "action": machine,
        "reason": a.reason,
    }


def _agent_skill_reason(result: SkillResult) -> str:
    """Compact display detail for a SkillResult without importing it at startup."""
    label = f"{result.target} {result.scope} {result.skill}"
    reason = result.reason
    return f"{label}; {reason}" if reason else label


def _install_agent_skill_actions(target: Path, *, dry_run: bool) -> list[Action]:
    """Install project-local packaged agent skills and adapt results to init actions."""
    from decree.commands.agents import install_agent_skills

    results = install_agent_skills(
        target_value="all",
        scope="project",
        project_root=target,
        dry_run=dry_run,
    )
    return [
        Action(
            "agent-skill",
            result.path,
            result.status,
            _agent_skill_reason(result),
        )
        for result in results
    ]


def _has_agent_skill_conflict(actions: list[Action]) -> bool:
    return any(action.kind == "agent-skill" and action.action == "skipped" for action in actions)


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
        return _rel(a.path, target)

    def line(a: Action) -> None:
        suffix = f" — {a.reason}" if a.reason else ""
        if a.kind == "agent-skill":
            label = a.action.replace("-", " ")
            if a.action == "skipped":
                warn(PREFIX, f"{label} {_shown(a)}{suffix}")
            elif a.action in ("unchanged", "would-keep"):
                info(PREFIX, f"{label} {_shown(a)}{suffix}")
            else:
                success(f"{label} {_shown(a)}{suffix}")
        elif a.action in ("rebuilt", "would-rebuild", "rebuild"):
            label = "would rebuild" if dry_run else "rebuilt"
            success(f"{label} {_shown(a)}")
        elif a.action in ("wrote", "would-write", "write"):
            label = "would write" if dry_run else "wrote"
            success(f"{label} {_shown(a)}{suffix}")
        elif a.action in ("appended", "would-append", "append"):
            label = "would append" if dry_run else "appended"
            success(f"{label} {_shown(a)}{suffix}")
        elif a.action in ("created", "would-create", "create"):
            label = "would create" if dry_run else "created"
            success(f"{label} {_shown(a)}")
        else:  # skipped
            info(PREFIX, f"skipped {_shown(a)}{suffix}")

    info(PREFIX, f"decree init — {target}{'  (dry run)' if dry_run else ''}")

    sections = [
        ("Config", "config"),
        ("Directories", "dir"),
        ("Examples", "example"),
        ("Ignore", "gitignore"),
        ("Index", "index"),
        ("Agent skills", "agent-skill"),
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
    with_agents = bool(getattr(args, "with_agents", False))

    if not target.exists():
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            error(PREFIX, f"cannot create target {target}: {e}")
            return 2

    # An existing-but-malformed decree.toml: fail clearly and name the file. init
    # never touches it, so the user knows exactly what to fix and that it was left
    # alone (rather than getting an opaque error from the index rebuild later).
    config_path = target / "decree.toml"
    if config_path.exists():
        cfg_err = _config_parse_error(config_path)
        if cfg_err:
            error(
                PREFIX,
                f"existing decree.toml is malformed ({config_path}): {cfg_err} — left unchanged; fix it and re-run.",
            )
            return 2

    git = _is_git_repo(target)

    try:
        plan = plan_init(target)
        if dry_run:
            actions = plan  # raw planning verbs; nothing touched on disk
            created = sum(1 for a in actions if a.action == "create")
            skipped = sum(1 for a in actions if a.action == "skip" and a.kind in ("config", "dir", "example"))
        else:
            applied = apply_init(plan, no_examples=no_examples)
            actions = applied.actions
            created = applied.created
            skipped = applied.skipped
        if with_agents:
            actions = [*actions, *_install_agent_skill_actions(target, dry_run=dry_run)]
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

    if _has_agent_skill_conflict(actions):
        error(
            PREFIX,
            "one or more existing agent skill files differ; run "
            "`decree agents install --target all --scope project --force` to overwrite.",
        )
        return 1

    return 0
