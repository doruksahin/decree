"""Install packaged decree agent skills for Codex and Claude Code."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Literal

from decree.log import error, info, success

AgentTarget = Literal["codex", "claude"]
InstallStatus = Literal["installed", "updated", "unchanged", "skipped", "would-install", "would-update", "would-keep"]

SKILLS_RESOURCE = ("templates", "agent", "skills")


@dataclass(frozen=True)
class SkillTemplate:
    name: str
    content: str


@dataclass(frozen=True)
class SkillResult:
    target: AgentTarget
    scope: str
    skill: str
    status: InstallStatus
    path: Path
    reason: str | None = None


def load_packaged_skills() -> list[SkillTemplate]:
    """Load bundled skill templates from package resources."""
    root = files("decree")
    for part in SKILLS_RESOURCE:
        root = root.joinpath(part)
    skills: list[SkillTemplate] = []
    for skill_dir in sorted(root.iterdir(), key=lambda item: item.name):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir.joinpath("SKILL.md")
        if not skill_file.is_file():
            continue
        skills.append(SkillTemplate(name=skill_dir.name, content=skill_file.read_text(encoding="utf-8")))
    if not skills:
        raise RuntimeError("no packaged decree agent skills found")
    return skills


def selected_targets(value: str) -> tuple[AgentTarget, ...]:
    if value == "all":
        return ("codex", "claude")
    if value in {"codex", "claude"}:
        return (value,)  # type: ignore[return-value]
    raise ValueError(f"unknown agent target: {value}")


def destination_root(target: AgentTarget, *, scope: str, project_root: Path | None, home: Path | None = None) -> Path:
    if scope == "project":
        if project_root is None:
            raise ValueError("project scope requires a decree project root")
        if target == "codex":
            return project_root / ".codex" / "skills"
        return project_root / ".claude" / "skills"
    if scope == "user":
        base = home or Path.home()
        if target == "codex":
            return base / ".codex" / "skills"
        return base / ".claude" / "skills"
    raise ValueError(f"unknown agent scope: {scope}")


def install_agent_skills(
    *,
    target_value: str,
    scope: str,
    project_root: Path | None,
    home: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> list[SkillResult]:
    """Install packaged skill templates and return per-skill results."""
    results: list[SkillResult] = []
    skills = load_packaged_skills()
    for target in selected_targets(target_value):
        root = destination_root(target, scope=scope, project_root=project_root, home=home)
        for skill in skills:
            dest = root / skill.name / "SKILL.md"
            if not dest.exists():
                status: InstallStatus = "would-install" if dry_run else "installed"
                if not dry_run:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(skill.content, encoding="utf-8")
                results.append(SkillResult(target, scope, skill.name, status, dest))
                continue

            existing = dest.read_text(encoding="utf-8")
            if existing == skill.content:
                status = "would-keep" if dry_run else "unchanged"
                results.append(SkillResult(target, scope, skill.name, status, dest))
                continue

            if not force:
                results.append(
                    SkillResult(
                        target,
                        scope,
                        skill.name,
                        "skipped",
                        dest,
                        "existing file differs; pass --force to overwrite",
                    )
                )
                continue

            status = "would-update" if dry_run else "updated"
            if not dry_run:
                dest.write_text(skill.content, encoding="utf-8")
            results.append(SkillResult(target, scope, skill.name, status, dest))
    return results


def status_agent_skills(
    *,
    target_value: str,
    scope: str,
    project_root: Path | None,
    home: Path | None = None,
) -> list[SkillResult]:
    """Compare installed skills with packaged templates."""
    results: list[SkillResult] = []
    skills = load_packaged_skills()
    for target in selected_targets(target_value):
        root = destination_root(target, scope=scope, project_root=project_root, home=home)
        for skill in skills:
            dest = root / skill.name / "SKILL.md"
            if not dest.exists():
                results.append(SkillResult(target, scope, skill.name, "skipped", dest, "missing"))
                continue
            existing = dest.read_text(encoding="utf-8")
            if existing == skill.content:
                results.append(SkillResult(target, scope, skill.name, "unchanged", dest))
            else:
                results.append(SkillResult(target, scope, skill.name, "skipped", dest, "installed file differs"))
    return results


def _project_root_for_scope(scope: str) -> Path | None:
    if scope != "project":
        return None
    from decree.config import get_project_root

    return get_project_root()


def _print_results(results: list[SkillResult]) -> None:
    for result in results:
        suffix = f" ({result.reason})" if result.reason else ""
        print(f"{result.target} {result.scope} {result.skill}: {result.status} {result.path}{suffix}")


def _has_blocking_result(results: list[SkillResult]) -> bool:
    return any(result.status == "skipped" and result.reason != "missing" for result in results)


def _install_hooks(args: argparse.Namespace, project_root: Path | None) -> int:
    targets = selected_targets(args.target)
    if not getattr(args, "hooks", False):
        return 0
    if "claude" not in targets:
        error("agents", "--hooks requires --target claude or --target all")
        return 1
    if args.scope != "project":
        error("agents", "--hooks is supported only with --scope project")
        return 1
    if project_root is None:
        error("agents", "--hooks requires a decree project")
        return 1
    if getattr(args, "dry_run", False):
        info("agents", f"would install Claude Code stop hook in {project_root / '.claude' / 'settings.json'}")
        return 0

    from decree.commands.hook import install_claude_hook

    try:
        install_claude_hook(project_root)
    except ValueError as exc:
        error("agents", str(exc))
        return 1
    info("agents", f"Claude Code stop hook installed at {project_root / '.claude' / 'settings.json'}")
    return 0


def run(args: argparse.Namespace) -> int:
    prefix = "agents"
    try:
        project_root = _project_root_for_scope(args.scope)
    except FileNotFoundError:
        error(prefix, "decree.toml not found. Use --scope user or run from a decree-enabled project.")
        return 1

    try:
        if args.agents_action == "install":
            hook_rc = _install_hooks(args, project_root)
            if hook_rc != 0:
                return hook_rc
            results = install_agent_skills(
                target_value=args.target,
                scope=args.scope,
                project_root=project_root,
                force=args.force,
                dry_run=args.dry_run,
            )
            _print_results(results)
            if _has_blocking_result(results):
                error(prefix, "one or more existing skill files differ; pass --force to overwrite")
                return 1
            success("agent skills checked")
            return 0
        if args.agents_action == "status":
            results = status_agent_skills(target_value=args.target, scope=args.scope, project_root=project_root)
            _print_results(results)
            return 1 if any(result.reason for result in results) else 0
    except (RuntimeError, ValueError) as exc:
        error(prefix, str(exc))
        return 1

    error(prefix, f"unknown agents action: {args.agents_action}")
    return 1
