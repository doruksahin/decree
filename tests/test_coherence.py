"""SPEC-008 coherence gate tests.

Covers:
  - Gate 1: terminal_status_progress
  - Gate 2: deferred_sections_separated + code-fence checkbox exclusion
  - Gate 3: unreferenced_active
  - Gate 4: status-field requirements surfacing
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from decree.commands.report import (
    DEFAULT_DEFERRED_SECTION_PATTERNS,
    _parse_checkboxes_by_section,
)


# ── Gate 2 unit tests (code-fence handling on the parser) ───


class TestCodeFenceExclusion:
    """SPEC-008 Gate 2: checkboxes inside fenced code blocks are illustrations."""

    def test_checkbox_inside_fence_is_ignored(self):
        body = """
## v1 Acceptance Criteria

- [x] Real done item

```markdown
- [x] Illustration only
- [ ] Another illustration
```

- [ ] Real pending item
"""
        parsed = _parse_checkboxes_by_section(body, DEFAULT_DEFERRED_SECTION_PATTERNS)
        # Only the two real items count
        assert parsed.primary_total == 2
        assert parsed.primary_done == 1

    def test_multiple_fences(self):
        body = """
## ACs

- [x] one
```
- [x] code-fence-illustration
```
- [ ] two
```python
- [x] another illustration
```
- [x] three
"""
        parsed = _parse_checkboxes_by_section(body, DEFAULT_DEFERRED_SECTION_PATTERNS)
        assert parsed.primary_total == 3
        assert parsed.primary_done == 2

    def test_no_fences_unaffected(self):
        body = """
## ACs

- [x] one
- [ ] two
"""
        parsed = _parse_checkboxes_by_section(body, DEFAULT_DEFERRED_SECTION_PATTERNS)
        assert parsed.primary_total == 2
        assert parsed.primary_done == 1


# ── Test corpus + fixture ───────────────────────────────────


def _three_type_toml(extra: str = "") -> str:
    base = """\
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
[types.adr.status_field_requirements]
superseded = ["superseded-by"]

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
    return base + extra


def _write_corpus(root: Path, extra_toml: str = "") -> None:
    (root / "decree.toml").write_text(_three_type_toml(extra_toml))
    for sub in ("prd", "adr", "spec"):
        (root / "decree" / sub).mkdir(parents=True, exist_ok=True)


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch):
    _write_corpus(tmp_path)
    monkeypatch.chdir(tmp_path)
    from decree.config import get_project_root, load_doc_types

    get_project_root.cache_clear()
    load_doc_types.cache_clear()
    yield tmp_path
    get_project_root.cache_clear()
    load_doc_types.cache_clear()


# ── Gate 1: terminal-status progress ────────────────────────


class TestGate1TerminalStatusProgress:
    def _spec(self, root: Path, name: str, status: str, body_acs: str):
        (root / "decree" / "spec" / f"{name}.md").write_text(
            f"""---
status: {status}
date: 2026-05-10
---

# SPEC-{name[:3]} title

## Overview

Prose.

## v1 Acceptance Criteria

{body_acs}
"""
        )

    def test_terminal_with_incomplete_primary_errors(self, corpus: Path, monkeypatch):
        # Reload doc_types with coherence gate enabled
        (corpus / "decree.toml").write_text(
            _three_type_toml(
                """
[types.spec.coherence]
terminal_status_progress = true
"""
            )
        )
        from decree.config import get_project_root, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()

        self._spec(corpus, "001-foo", "implemented", "- [x] one\n- [ ] two\n- [ ] three\n")
        from decree.commands import lint

        rc = lint.run()
        assert rc == 1

    def test_terminal_with_complete_primary_passes(self, corpus: Path, monkeypatch):
        (corpus / "decree.toml").write_text(
            _three_type_toml(
                """
[types.spec.coherence]
terminal_status_progress = true
"""
            )
        )
        from decree.config import get_project_root, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()

        self._spec(corpus, "001-foo", "implemented", "- [x] one\n- [x] two\n")
        from decree.commands import lint

        rc = lint.run()
        assert rc == 0

    def test_deferred_items_dont_drag_progress(self, corpus: Path):
        (corpus / "decree.toml").write_text(
            _three_type_toml(
                """
[types.spec.coherence]
terminal_status_progress = true
"""
            )
        )
        from decree.config import get_project_root, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()

        body = """- [x] one
- [x] two

### Deferred

- [ ] backlog item
"""
        self._spec(corpus, "001-foo", "implemented", body)
        from decree.commands import lint

        rc = lint.run()
        assert rc == 0

    def test_gate_disabled_no_error(self, corpus: Path):
        # No [types.spec.coherence] block at all → gate disabled
        from decree.config import get_project_root, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()

        self._spec(corpus, "001-foo", "implemented", "- [x] one\n- [ ] two\n")
        from decree.commands import lint

        rc = lint.run()
        assert rc == 0


# ── Gate 2: deferred section reporting + code fences ────────


class TestGate2DeferredSections:
    def test_custom_deferred_sections_pattern(self, corpus: Path):
        (corpus / "decree.toml").write_text(
            _three_type_toml(
                """
[types.spec.coherence]
deferred_sections_separated = true
deferred_sections = ["Backlog"]
"""
            )
        )
        from decree.config import get_project_root, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()

        (corpus / "decree" / "spec" / "001-foo.md").write_text(
            """---
status: implemented
date: 2026-05-10
---

# SPEC-001 title

## Overview

x

## ACs

- [x] one
- [x] two

## Backlog

- [ ] later
"""
        )
        from decree.commands import lint
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = lint.run()
        out = buf.getvalue()
        assert rc == 0
        assert "deferred-section ACs" in out

    def test_code_block_checkboxes_excluded_via_parser(self):
        """Confirm parser-side: gate 2's other half — fenced checkboxes don't count."""
        body = """## ACs

- [x] real

```markdown
- [x] inside fence
- [ ] also inside fence
```

- [ ] another real
"""
        parsed = _parse_checkboxes_by_section(body, DEFAULT_DEFERRED_SECTION_PATTERNS)
        assert parsed.primary_total == 2


# ── Gate 3: unreferenced active ─────────────────────────────


class TestGate3UnreferencedActive:
    def test_unreferenced_prd_after_threshold_errors(self, corpus: Path):
        old = (date.today() - timedelta(days=35)).isoformat()
        (corpus / "decree.toml").write_text(
            _three_type_toml(
                """
[types.prd.coherence]
unreferenced_active = true
unreferenced_after_days = 30
active_statuses = ["approved"]
"""
            )
        )
        from decree.config import get_project_root, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()

        (corpus / "decree" / "prd" / "001-foo.md").write_text(
            f"""---
status: approved
date: {old}
---

# PRD-001 stalled

## Problem Statement

x
"""
        )
        from decree.commands import lint

        rc = lint.run()
        assert rc == 1

    def test_unreferenced_prd_within_window_passes(self, corpus: Path):
        recent = (date.today() - timedelta(days=5)).isoformat()
        (corpus / "decree.toml").write_text(
            _three_type_toml(
                """
[types.prd.coherence]
unreferenced_active = true
unreferenced_after_days = 30
active_statuses = ["approved"]
"""
            )
        )
        from decree.config import get_project_root, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()

        (corpus / "decree" / "prd" / "001-foo.md").write_text(
            f"""---
status: approved
date: {recent}
---

# PRD-001 recent

## Problem Statement

x
"""
        )
        from decree.commands import lint

        rc = lint.run()
        assert rc == 0

    def test_referenced_prd_not_flagged(self, corpus: Path):
        old = (date.today() - timedelta(days=35)).isoformat()
        (corpus / "decree.toml").write_text(
            _three_type_toml(
                """
[types.prd.coherence]
unreferenced_active = true
unreferenced_after_days = 30
active_statuses = ["approved"]
"""
            )
        )
        from decree.config import get_project_root, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()

        (corpus / "decree" / "prd" / "001-foo.md").write_text(
            f"""---
status: approved
date: {old}
---

# PRD-001 referenced

## Problem Statement

x
"""
        )
        (corpus / "decree" / "spec" / "001-bar.md").write_text(
            """---
status: implemented
date: 2026-05-12
references: [PRD-001]
---

# SPEC-001 child

## Overview

x
"""
        )
        from decree.commands import lint

        rc = lint.run()
        assert rc == 0

    def test_gate_disabled_no_error(self, corpus: Path):
        old = (date.today() - timedelta(days=100)).isoformat()
        # No coherence block at all
        from decree.config import get_project_root, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()

        (corpus / "decree" / "prd" / "001-foo.md").write_text(
            f"""---
status: approved
date: {old}
---

# PRD-001 ancient

## Problem Statement

x
"""
        )
        from decree.commands import lint

        rc = lint.run()
        assert rc == 0


# ── Gate 4: status-field requirements surfacing ─────────────


class TestGate4StatusFieldRequirements:
    """Decree already enforces status_field_requirements via the parser.

    Gate 4 doesn't add a new check; it surfaces the existing behavior. This
    test confirms the existing path still flags a missing `superseded-by`.
    """

    def test_superseded_without_target_emits_error(self, corpus: Path):
        from decree.config import get_project_root, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()

        (corpus / "decree" / "adr" / "0001-broken.md").write_text(
            """---
status: superseded
date: 2026-05-10
---

# ADR-0001 broken

## Context and Problem Statement

x
"""
        )
        from decree.commands import lint

        rc = lint.run()
        assert rc == 1


# ── Config parsing ──────────────────────────────────────────


class TestCoherenceConfigParsing:
    def test_unknown_key_errors_at_load(self, corpus: Path):
        (corpus / "decree.toml").write_text(
            _three_type_toml(
                """
[types.spec.coherence]
nonsense_key = true
"""
            )
        )
        from decree.config import get_project_root, load_doc_types

        get_project_root.cache_clear()
        load_doc_types.cache_clear()
        with pytest.raises(ValueError, match="unknown keys"):
            load_doc_types()

    def test_health_config_defaults(self, corpus: Path):
        from decree.config import get_project_root, load_health_config

        get_project_root.cache_clear()
        cfg = load_health_config()
        assert cfg.threshold_commits == 10
        assert cfg.threshold_days == 30

    def test_health_config_overrides(self, corpus: Path):
        (corpus / "decree.toml").write_text(
            _three_type_toml(
                """
[health]
threshold_commits = 5
threshold_days = 14
"""
            )
        )
        from decree.config import get_project_root, load_health_config

        get_project_root.cache_clear()
        cfg = load_health_config()
        assert cfg.threshold_commits == 5
        assert cfg.threshold_days == 14

    def test_health_unknown_key_errors(self, corpus: Path):
        (corpus / "decree.toml").write_text(
            _three_type_toml(
                """
[health]
unknown_key = 1
"""
            )
        )
        from decree.config import get_project_root, load_health_config

        get_project_root.cache_clear()
        with pytest.raises(ValueError, match="Unknown keys"):
            load_health_config()
