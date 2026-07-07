"""Shared corpus fixtures reproducing the Agentkith dogfooding cases (backlog B2).

Each builder writes a ``decree.toml`` plus a document corpus into ``root`` so the
command tests grade real changes against the situations that surfaced during live
Agentkith work, not toy corpora. Builders that need git history (churn / attached
commits) only write the docs; the caller adds commits.

Reference: docs/dogfooding-feedback/06-research-backlog.md (item B2).
"""

from __future__ import annotations

from pathlib import Path

DECREE_TOML = """\
[types.prd]
dir = "decree/prd"
prefix = "PRD"
digits = 3
initial_status = "draft"
statuses = ["draft", "approved", "implemented"]
warn_on_reference = []
required_sections = ["Problem Statement"]
[types.prd.transitions]
draft = ["approved"]
approved = ["implemented"]
implemented = []
[types.prd.actions]
approve = "approved"
implement = "implemented"

[types.adr]
dir = "decree/adr"
prefix = "ADR"
digits = 4
initial_status = "proposed"
statuses = ["proposed", "accepted", "rejected", "deprecated", "superseded"]
warn_on_reference = ["rejected", "deprecated", "superseded"]
required_sections = ["Context and Problem Statement"]
[types.adr.transitions]
proposed = ["accepted", "rejected"]
accepted = ["deprecated", "superseded"]
rejected = []
deprecated = []
superseded = []
[types.adr.actions]
accept = "accepted"
reject = "rejected"
deprecate = "deprecated"
supersede = "superseded"

[types.spec]
dir = "decree/spec"
prefix = "SPEC"
digits = 3
initial_status = "draft"
statuses = ["draft", "approved", "implemented"]
warn_on_reference = []
required_sections = ["Overview"]
[types.spec.transitions]
draft = ["approved"]
approved = ["implemented"]
implemented = []
[types.spec.actions]
approve = "approved"
implement = "implemented"
"""

PRD_ID = "PRD-00000000000000000000000001"


def _padded(n: int) -> str:
    return str(n).rjust(26, "0")


def spec_id(n: int) -> str:
    """Deterministic 26-char SPEC id, mirroring the existing test corpora."""
    return f"SPEC-{_padded(n)}"


def _init(root: Path) -> None:
    (root / "decree.toml").write_text(DECREE_TOML)
    for sub in ("prd", "adr", "spec"):
        (root / "decree" / sub).mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir(exist_ok=True)


def _write_prd(root: Path) -> None:
    (root / "decree" / "prd" / "prd-00000000000000000000000001-test.md").write_text(
        f"""---
id: {PRD_ID}
status: approved
date: 2026-05-10
---

# {PRD_ID} Test PRD

## Problem Statement

Prose.
"""
    )


def _write_spec(
    root: Path,
    n: int,
    *,
    status: str = "implemented",
    governs: list[str],
    acs: list[str] | None = None,
    title: str = "SPEC",
    date: str = "2026-05-12",
) -> str:
    sid = spec_id(n)
    gov_block = "\n".join(f"  - {g}" for g in governs)
    ac_lines = acs if acs is not None else ["- [ ] Feature is shipped", "- [x] Tests pass"]
    ac_block = "\n".join(ac_lines)
    (root / "decree" / "spec" / f"spec-{_padded(n)}-{n}.md").write_text(
        f"""---
id: {sid}
status: {status}
date: {date}
references: [{PRD_ID}]
governs:
{gov_block}
---

# {sid} {title}

## Overview

{title} perspective.

## Acceptance Criteria

{ac_block}
"""
    )
    return sid


def hot_file_three_specs(root: Path, hot: str = "src/hot.py") -> tuple[str, tuple[str, ...]]:
    """Case 1/3: one hot file governed by three complementary SPECs.

    Returns ``(authoritative_id, all_ids)``. SPEC …001 is the authoritative
    first-slice; …002 is an evolution slice; …003 is an implemented model-controls
    slice. All three ``govern`` the same hot file, so the exact-conflict query
    reports a multi-decision conflict the caller can reframe with ``--under``.
    """
    _init(root)
    (root / hot).parent.mkdir(parents=True, exist_ok=True)
    (root / hot).touch()
    _write_prd(root)
    a = _write_spec(root, 1, status="draft", governs=[hot], title="Push-to-talk first slice")
    b = _write_spec(root, 2, status="draft", governs=[hot], title="In-app voice dictation")
    c = _write_spec(root, 3, status="implemented", governs=[hot], title="Model controls")
    return a, (a, b, c)


def conflict_with_unrelated(root: Path, hot: str = "src/foo.py", other: str = "src/other.py") -> dict[str, str]:
    """B8: SPEC …001 & …002 govern ``hot`` (conflict); SPEC …004 governs ``other``.

    Lets a test set ``--under`` to an owning decision (…001 → contextual overlap)
    or an unrelated one (…004 → contradiction on ``hot``).
    """
    _init(root)
    for p in (hot, other):
        (root / p).parent.mkdir(parents=True, exist_ok=True)
        (root / p).touch()
    _write_prd(root)
    _write_spec(root, 1, governs=[hot], title="Owner A")
    _write_spec(root, 2, status="draft", governs=[hot], title="Owner B")
    _write_spec(root, 4, governs=[other], title="Unrelated")
    return {"hot": hot, "other": other, "owner": spec_id(1), "contextual": spec_id(2), "unrelated": spec_id(4)}


def exact_and_directory_overlap(root: Path, target: str = "src/baz.py") -> dict[str, str]:
    """B12: SPEC …005 governs ``target`` exactly; SPEC …003 governs ``src/`` (directory).

    ``target`` is co-governed (one exact, one directory-prefix) but is NOT an
    exact multi-decision conflict, so it is invisible to the exact conflict query.
    """
    _init(root)
    (root / target).parent.mkdir(parents=True, exist_ok=True)
    (root / target).touch()
    _write_prd(root)
    _write_spec(root, 5, governs=[target], title="Exact owner")
    _write_spec(root, 3, governs=["src/"], title="Directory owner")
    return {"target": target, "exact": spec_id(5), "directory": spec_id(3)}


def draft_at_100(root: Path, governs: str = "src/foo.py") -> str:
    """Case 4/B10: SPEC …001 with every primary AC checked but status still ``draft``."""
    _init(root)
    (root / governs).parent.mkdir(parents=True, exist_ok=True)
    (root / governs).touch()
    _write_prd(root)
    return _write_spec(
        root,
        1,
        status="draft",
        governs=[governs],
        acs=["- [x] Ships", "- [x] Tested"],
        title="Complete but draft",
    )


def broad_governs(root: Path, n: int = 60) -> tuple[str, list[str]]:
    """Case 3/B11: SPEC …001 governs ``n`` paths (broad ownership surface)."""
    _init(root)
    paths = [f"src/mod{i}.py" for i in range(n)]
    for p in paths:
        (root / p).touch()
    _write_prd(root)
    sid = _write_spec(root, 1, governs=paths, title="Broad governance")
    return sid, paths
