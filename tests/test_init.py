"""Tests for `decree init` — deterministic, idempotent project scaffolder.

Phase 1 pins the lints-clean contract on the bundled assets before any command
code exists. Phases 2/3 cover the planning core, the apply step, and the CLI
report / exit codes / `--json` machine contract.

The "lint clean" assertions run `decree lint` as a subprocess with `cwd=<target>`
because `decree lint` resolves its project via the cwd-walk (it has no
`--project` flag). That is exactly how a user verifies a freshly-scaffolded
project, so it is the realistic contract.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# Pinned example-chain IDs (must stay in sync with the bundled docs).
PRD_ID = "PRD-01JEXAMP1E00000000000000PR"
ADR_ID = "ADR-01JEXAMP1E00000000000000AD"
SPEC_ID = "SPEC-01JEXAMP1E0000000000000SPC"

INIT_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "src" / "decree" / "templates" / "init"


def _run_decree(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the decree CLI as a subprocess rooted at `cwd`."""
    return subprocess.run(
        [sys.executable, "-m", "decree.cli", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


# ── Phase 1: bundled assets lint clean together ─────────────


def test_bundled_assets_lint_clean(tmp_path: Path) -> None:
    """The bundled decree.toml + worked chain pass `decree lint` with 0 errors.

    Copies the four bundled assets into a tmp dir mirroring the target layout
    (decree.toml at root, docs under decree/<type>/), then lints.
    """
    # Mirror the bundled layout into the tmp target.
    (tmp_path / "decree.toml").write_text((INIT_TEMPLATE_DIR / "decree.toml").read_text())
    for type_name in ("prd", "adr", "spec"):
        dest = tmp_path / "decree" / type_name
        dest.mkdir(parents=True)
        for src in (INIT_TEMPLATE_DIR / type_name).glob("*.md"):
            (dest / src.name).write_text(src.read_text())

    result = _run_decree("lint", cwd=tmp_path)
    assert result.returncode == 0, f"lint failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    assert "0 errors" in (result.stdout + result.stderr)

    # Cross-refs resolve: refs on the SPEC should surface the PRD and the ADR.
    refs = _run_decree("refs", SPEC_ID, cwd=tmp_path)
    # `refs` needs the index; build it first, then re-query.
    _run_decree("index", "rebuild", cwd=tmp_path)
    refs = _run_decree("refs", SPEC_ID, cwd=tmp_path)
    combined = refs.stdout + refs.stderr
    assert PRD_ID in combined
    assert ADR_ID in combined


# ── Phase 2: plan_init (pure planning, no disk writes) ──────


def _actions_by_kind(plan, kind):
    return [a for a in plan if a.kind == kind]


def test_plan_empty_target_all_create(tmp_path: Path) -> None:
    """An empty target plans to create every piece."""
    from decree.commands.init import plan_init

    plan = plan_init(tmp_path)

    config = _actions_by_kind(plan, "config")
    assert len(config) == 1
    assert config[0].action == "create"

    dirs = _actions_by_kind(plan, "dir")
    assert {a.path.name for a in dirs} == {"prd", "adr", "spec"}
    assert all(a.action == "create" for a in dirs)

    examples = _actions_by_kind(plan, "example")
    assert len(examples) == 3
    assert all(a.action == "create" for a in examples)

    index = _actions_by_kind(plan, "index")
    assert len(index) == 1
    assert index[0].action == "create"

    # No writes happened.
    assert not (tmp_path / "decree.toml").exists()
    assert not (tmp_path / "decree").exists()


def test_plan_full_target_all_skip(tmp_path: Path) -> None:
    """A fully-initialized target plans to skip config, dirs, and examples."""
    from decree.commands.init import apply_init, plan_init

    apply_init(plan_init(tmp_path), no_examples=False)

    plan = plan_init(tmp_path)
    config = _actions_by_kind(plan, "config")[0]
    assert config.action == "skip"
    assert config.reason and "types" in config.reason

    assert all(a.action == "skip" for a in _actions_by_kind(plan, "dir"))
    assert all(a.action == "skip" for a in _actions_by_kind(plan, "example"))


def test_plan_partial_toml_present_dirs_absent(tmp_path: Path) -> None:
    """toml present + dirs absent → config skipped, dirs/examples created."""
    from decree.commands.init import plan_init

    (tmp_path / "decree.toml").write_text((INIT_TEMPLATE_DIR / "decree.toml").read_text())

    plan = plan_init(tmp_path)
    assert _actions_by_kind(plan, "config")[0].action == "skip"
    assert all(a.action == "create" for a in _actions_by_kind(plan, "dir"))
    assert all(a.action == "create" for a in _actions_by_kind(plan, "example"))


def test_plan_nonempty_type_dir_skips_only_that_example(tmp_path: Path) -> None:
    """A non-empty decree/spec/ → spec example skipped; prd/adr examples created."""
    from decree.commands.init import plan_init

    spec_dir = tmp_path / "decree" / "spec"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec-existing.md").write_text("# pre-existing\n")

    plan = plan_init(tmp_path)
    examples = {a.path.parent.name: a for a in _actions_by_kind(plan, "example")}
    assert examples["spec"].action == "skip"
    assert "already has documents" in (examples["spec"].reason or "")
    assert examples["prd"].action == "create"
    assert examples["adr"].action == "create"

    # The existing spec dir is itself skipped (present), not recreated.
    spec_dir_action = next(a for a in _actions_by_kind(plan, "dir") if a.path.name == "spec")
    assert spec_dir_action.action == "skip"


# ── Phase 2: apply_init (executes a plan; never overwrites) ──


def test_apply_into_empty_creates_files_index_and_lints_clean(tmp_path: Path) -> None:
    from decree.commands.init import apply_init, plan_init

    applied = apply_init(plan_init(tmp_path), no_examples=False)

    assert (tmp_path / "decree.toml").exists()
    for t in ("prd", "adr", "spec"):
        assert (tmp_path / "decree" / t).is_dir()
        assert list((tmp_path / "decree" / t).glob("*.md")), f"{t} example not seeded"
    assert (tmp_path / ".decree" / "index.sqlite").exists()
    assert applied.created > 0

    result = _run_decree("lint", cwd=tmp_path)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def test_apply_is_idempotent_no_overwrite(tmp_path: Path) -> None:
    from decree.commands.init import apply_init, plan_init

    apply_init(plan_init(tmp_path), no_examples=False)
    prd = next((tmp_path / "decree" / "prd").glob("*.md"))
    sentinel = prd.read_text() + "\nUSER EDIT — must survive re-init\n"
    prd.write_text(sentinel)

    re_applied = apply_init(plan_init(tmp_path), no_examples=False)
    # The index is always rebuilt (it is not a file we refuse to touch); but no
    # config/dir/example is ever (re)created on a fully-present project.
    non_index_created = [a for a in re_applied.actions if a.kind != "index" and a.action == "created"]
    assert non_index_created == []
    assert prd.read_text() == sentinel  # never overwritten


def test_apply_no_examples_skips_docs(tmp_path: Path) -> None:
    from decree.commands.init import apply_init, plan_init

    apply_init(plan_init(tmp_path), no_examples=True)

    assert (tmp_path / "decree.toml").exists()
    for t in ("prd", "adr", "spec"):
        assert (tmp_path / "decree" / t).is_dir()
        assert not list((tmp_path / "decree" / t).glob("*.md"))
    assert (tmp_path / ".decree" / "index.sqlite").exists()


# ── Phase 3: CLI command, report, exit codes, --json ────────


def _init(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return _run_decree("init", *args, cwd=cwd)


def test_cli_init_help() -> None:
    result = _run_decree("init", "--help", cwd=Path.cwd())
    assert result.returncode == 0
    out = result.stdout + result.stderr
    assert "--dry-run" in out
    assert "--no-examples" in out
    assert "--project" in out


def test_cli_empty_dir_created_and_lint_clean(tmp_path: Path) -> None:
    result = _init(cwd=tmp_path)
    assert result.returncode == 0, result.stderr

    assert (tmp_path / "decree.toml").exists()
    assert (tmp_path / ".decree" / "index.sqlite").exists()
    for t in ("prd", "adr", "spec"):
        assert list((tmp_path / "decree" / t).glob("*.md"))

    # The report names each created piece (on stderr).
    assert "decree.toml" in result.stderr
    assert "Created" in result.stderr

    # The scaffolded project lints clean and the chain resolves.
    assert _run_decree("lint", cwd=tmp_path).returncode == 0
    assert _run_decree("index", "rebuild", cwd=tmp_path).returncode == 0
    why = _run_decree("why", "src/anything.py", cwd=tmp_path)
    assert why.returncode in (0, 1)  # path not governed → graceful, not a crash
    refs = _run_decree("refs", SPEC_ID, cwd=tmp_path)
    assert refs.returncode == 0
    assert PRD_ID in (refs.stdout + refs.stderr)


def test_cli_rerun_all_skipped_exit_zero(tmp_path: Path) -> None:
    assert _init(cwd=tmp_path).returncode == 0
    second = _init(cwd=tmp_path)
    assert second.returncode == 0
    assert "skipped" in second.stderr.lower()


def test_cli_dry_run_writes_nothing(tmp_path: Path) -> None:
    result = _init("--dry-run", cwd=tmp_path)
    assert result.returncode == 0
    # Absolutely nothing on disk.
    assert not (tmp_path / "decree.toml").exists()
    assert not (tmp_path / "decree").exists()
    assert not (tmp_path / ".decree").exists()
    assert list(tmp_path.iterdir()) == []
    # But the plan is reported.
    assert "would create" in result.stderr.lower()


def test_cli_partial_only_missing_created(tmp_path: Path) -> None:
    (tmp_path / "decree.toml").write_text((INIT_TEMPLATE_DIR / "decree.toml").read_text())
    result = _init(cwd=tmp_path)
    assert result.returncode == 0
    # Config was present → skipped; dirs + examples created.
    assert "skipped" in result.stderr.lower()
    for t in ("prd", "adr", "spec"):
        assert list((tmp_path / "decree" / t).glob("*.md"))


# A valid, lintable pre-existing SPEC the user already wrote.
_EXISTING_SPEC = """\
---
id: SPEC-01HF7YAT020000000000000099
status: draft
date: 2026-02-01
---

# SPEC-01HF7YAT020000000000000099 My Own Spec

## Overview

A spec the user wrote before running init again.
"""


def test_cli_nonempty_type_dir_example_skipped(tmp_path: Path) -> None:
    (tmp_path / "decree.toml").write_text((INIT_TEMPLATE_DIR / "decree.toml").read_text())
    spec_dir = tmp_path / "decree" / "spec"
    spec_dir.mkdir(parents=True)
    existing = spec_dir / "spec-01hf7yat020000000000000099-my-own-spec.md"
    existing.write_text(_EXISTING_SPEC)

    result = _init(cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "already has documents" in result.stderr
    # The user's doc is untouched; the example is not seeded into spec/.
    assert existing.read_text() == _EXISTING_SPEC
    spec_docs = {p.name for p in spec_dir.glob("*.md")}
    assert spec_docs == {existing.name}
    # prd/adr examples were seeded.
    assert list((tmp_path / "decree" / "prd").glob("*.md"))


def test_cli_no_examples(tmp_path: Path) -> None:
    result = _init("--no-examples", cwd=tmp_path)
    assert result.returncode == 0
    assert (tmp_path / "decree.toml").exists()
    assert (tmp_path / ".decree" / "index.sqlite").exists()
    for t in ("prd", "adr", "spec"):
        assert (tmp_path / "decree" / t).is_dir()
        assert not list((tmp_path / "decree" / t).glob("*.md"))


def test_cli_non_git_target_emits_git_note(tmp_path: Path) -> None:
    # tmp_path is not a git repo.
    result = _init(cwd=tmp_path)
    assert result.returncode == 0
    assert "git init" in result.stderr


def test_cli_git_target_no_git_note(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    result = _init(cwd=tmp_path)
    assert result.returncode == 0
    assert "git init" not in result.stderr


def test_cli_json_shape_run(tmp_path: Path) -> None:
    result = _init("--json", cwd=tmp_path)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {
        "target",
        "actions",
        "summary",
        "git",
        "dry_run",
        "exit",
    }
    assert payload["target"] == str(tmp_path.resolve())
    assert payload["dry_run"] is False
    assert payload["git"] is False
    assert payload["exit"] == 0
    assert set(payload["summary"].keys()) == {"created", "skipped"}
    assert payload["summary"]["created"] > 0
    for a in payload["actions"]:
        assert set(a.keys()) == {"kind", "path", "action", "reason"}
        assert a["kind"] in {"config", "dir", "example", "index"}
        assert a["action"] in {"created", "skipped", "would-create"}
    # In a real (non-dry) run, nothing should be reported as would-create.
    assert all(a["action"] != "would-create" for a in payload["actions"])


def test_cli_json_shape_dry_run(tmp_path: Path) -> None:
    result = _init("--dry-run", "--json", cwd=tmp_path)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["summary"]["created"] > 0  # counts the would-create steps
    # Every actionable step is "would-create" or "skipped" — none "created".
    assert all(a["action"] in {"would-create", "skipped"} for a in payload["actions"])
    # Dry run wrote nothing.
    assert list(tmp_path.iterdir()) == []


def test_cli_project_flag_targets_other_dir(tmp_path: Path) -> None:
    other = tmp_path / "elsewhere"
    other.mkdir()
    # Run from tmp_path but target `other` via --project.
    result = _init("--project", str(other), cwd=tmp_path)
    assert result.returncode == 0
    assert (other / "decree.toml").exists()
    assert (other / ".decree" / "index.sqlite").exists()
    # The cwd (tmp_path) is untouched.
    assert not (tmp_path / "decree.toml").exists()
