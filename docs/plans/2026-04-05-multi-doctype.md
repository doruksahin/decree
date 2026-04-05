# Multi-Document-Type Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Generalize decree from ADR-only to support configurable document types (ADR, PRD, SPEC, etc.) with cross-type references and validation.

**Architecture:** Introduce a `DocType` dataclass that encapsulates all type-specific config (prefix, statuses, transitions, sections, template, directory). ADR remains a built-in default. Additional types are defined in `[tool.doc.types.*]` sections of pyproject.toml. The parser and commands become type-parameterized. A new `doc` CLI entry point sits alongside the backward-compatible `adr` entry point.

**Tech Stack:** Python 3.11+, Pydantic v2, python-frontmatter, python-slugify, pytest

---

## Scenarios This Plan Supports

```
S1: doc new adr "Use Redis"        → docs/adr/0001-use-redis.md (ADR-0001)
S2: doc new prd "User Auth"        → docs/prd/001-user-auth.md  (PRD-001)
S3: doc new spec "Auth API"        → docs/spec/001-auth-api.md  (SPEC-001)
S4: doc status ADR-0001 accepted   → enforces ADR transitions
S5: doc status PRD-001 approved    → enforces PRD transitions
S6: PRD-001 frontmatter has references: [ADR-0003] → lint validates ADR-0003 exists
S7: SPEC-001 frontmatter has references: [PRD-001] → lint validates PRD-001 exists
S8: ADR-0003 gets superseded → lint warns: "PRD-001 references ADR-0003 (superseded)"
S9: doc lint                       → validates all types + cross-type references
S10: doc index                     → generates per-type index files
S11: doc graph                     → Mermaid with cross-type edges
S12: adr new "title" still works   → backward compatibility
```

## Config Schema (Target)

```toml
# Backward compatible — still works:
[tool.adr]
adr_dir = "docs/adr"
project_sections = ["Consequences"]

# New multi-type config — takes precedence when present:
[tool.doc.types.adr]
dir = "docs/adr"
prefix = "ADR"
digits = 4
initial_status = "proposed"
statuses = ["proposed", "accepted", "rejected", "deprecated", "superseded"]
warn_on_reference = ["rejected", "deprecated", "superseded"]
required_sections = ["Context and Problem Statement", "Considered Options", "Decision Outcome"]
project_sections = ["Consequences"]

[tool.doc.types.adr.transitions]
proposed = ["accepted", "rejected"]
accepted = ["deprecated", "superseded"]

[tool.doc.types.adr.actions]
accept = "accepted"
reject = "rejected"
deprecate = "deprecated"
supersede = "superseded"

[tool.doc.types.prd]
dir = "docs/prd"
prefix = "PRD"
digits = 3
initial_status = "draft"
statuses = ["draft", "review", "approved", "implemented", "archived"]
warn_on_reference = ["archived"]
required_sections = ["Problem Statement", "Requirements", "Success Criteria"]

[tool.doc.types.prd.transitions]
draft = ["review"]
review = ["approved", "draft"]
approved = ["implemented"]
implemented = ["archived"]

[tool.doc.types.prd.actions]
submit = "review"
approve = "approved"
implement = "implemented"
archive = "archived"

[tool.doc.types.spec]
dir = "docs/spec"
prefix = "SPEC"
digits = 3
initial_status = "draft"
statuses = ["draft", "review", "approved", "implemented"]
warn_on_reference = []
required_sections = ["Overview", "Technical Design", "Testing Strategy"]

[tool.doc.types.spec.transitions]
draft = ["review"]
review = ["approved", "draft"]
approved = ["implemented"]
implemented = []

[tool.doc.types.spec.actions]
submit = "review"
approve = "approved"
implement = "implemented"
```

---

## Task 1: DocType dataclass

**Files:**
- Create: `src/decree/doctypes.py`
- Test: `tests/test_doctypes.py`

This is the core abstraction. Every type-specific constant moves from config.py module-level into a DocType instance.

**Step 1: Write failing tests**

```python
# tests/test_doctypes.py
from decree.doctypes import DocType, ADR_DEFAULT

def test_adr_default_has_expected_statuses():
    assert ADR_DEFAULT.statuses == ("proposed", "accepted", "rejected", "deprecated", "superseded")

def test_adr_default_prefix():
    assert ADR_DEFAULT.prefix == "ADR"
    assert ADR_DEFAULT.digits == 4

def test_adr_default_transitions():
    assert ADR_DEFAULT.transitions["proposed"] == ("accepted", "rejected")
    assert ADR_DEFAULT.transitions["rejected"] == ()

def test_adr_default_ref_re():
    import re
    assert ADR_DEFAULT.ref_re.match("ADR-0001")
    assert not ADR_DEFAULT.ref_re.match("PRD-001")

def test_adr_default_filename_re():
    assert ADR_DEFAULT.filename_re.match("0001-use-redis.md")
    assert not ADR_DEFAULT.filename_re.match("001-use-redis.md")  # needs 4 digits

def test_adr_default_actions():
    assert ADR_DEFAULT.actions["accept"] == "accepted"
    assert ADR_DEFAULT.actions["supersede"] == "superseded"

def test_adr_default_required_sections():
    assert "Context and Problem Statement" in ADR_DEFAULT.required_sections
    assert "Considered Options" in ADR_DEFAULT.required_sections
    assert "Decision Outcome" in ADR_DEFAULT.required_sections

def test_adr_default_initial_status():
    assert ADR_DEFAULT.initial_status == "proposed"

def test_adr_default_status_field_requirements():
    assert ADR_DEFAULT.status_field_requirements["superseded"] == ("superseded-by",)
    assert ADR_DEFAULT.status_field_requirements["proposed"] == ()

def test_doctype_format_id():
    assert ADR_DEFAULT.format_id(1) == "ADR-0001"
    assert ADR_DEFAULT.format_id(42) == "ADR-0042"

def test_doctype_parse_number_from_id():
    assert ADR_DEFAULT.parse_number("ADR-0001") == 1
    assert ADR_DEFAULT.parse_number("ADR-0042") == 42

def test_doctype_terminal_statuses():
    """Statuses with no valid transitions are terminal."""
    assert "rejected" in ADR_DEFAULT.terminal_statuses
    assert "deprecated" in ADR_DEFAULT.terminal_statuses
    assert "superseded" in ADR_DEFAULT.terminal_statuses
    assert "proposed" not in ADR_DEFAULT.terminal_statuses

def test_prd_doctype():
    prd = DocType(
        name="prd",
        prefix="PRD",
        digits=3,
        dir="docs/prd",
        initial_status="draft",
        statuses=("draft", "review", "approved", "implemented", "archived"),
        transitions={
            "draft": ("review",),
            "review": ("approved", "draft"),
            "approved": ("implemented",),
            "implemented": ("archived",),
            "archived": (),
        },
        actions={"submit": "review", "approve": "approved", "implement": "implemented", "archive": "archived"},
        required_sections=("Problem Statement", "Requirements", "Success Criteria"),
    )
    assert prd.ref_re.match("PRD-001")
    assert not prd.ref_re.match("PRD-0001")  # 3 digits, not 4
    assert prd.format_id(1) == "PRD-001"
    assert prd.filename_re.match("001-user-auth.md")
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/doruk/Desktop/SIDE_HUSTLE/decree && uv run pytest tests/test_doctypes.py -v`
Expected: FAIL — module `decree.doctypes` does not exist

**Step 3: Implement DocType**

```python
# src/decree/doctypes.py
"""Document type definitions — the core abstraction for multi-type support."""

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DocType:
    """A document type with its own ID scheme, lifecycle, and structure."""

    name: str
    prefix: str
    digits: int
    dir: str  # relative to project root
    initial_status: str
    statuses: tuple[str, ...]
    transitions: dict[str, tuple[str, ...]]
    actions: dict[str, str]  # verb → target status
    required_sections: tuple[str, ...] = ()
    warn_on_reference: tuple[str, ...] = ()  # "dead" statuses — referencing these is flagged
    status_field_requirements: dict[str, tuple[str, ...]] = field(default_factory=dict)
    section_descriptions: dict[str, str] = field(default_factory=dict)
    template: str | None = None  # relative path to custom template, or None for built-in

    @property
    def ref_re(self) -> re.Pattern:
        return re.compile(rf"^{re.escape(self.prefix)}-\d{{{self.digits}}}$")

    @property
    def filename_re(self) -> re.Pattern:
        return re.compile(rf"^(\d{{{self.digits}}})-.+\.md$")

    @property
    def terminal_statuses(self) -> frozenset[str]:
        return frozenset(s for s, t in self.transitions.items() if not t)

    # NOTE: warn_on_reference is DIFFERENT from terminal_statuses.
    # "implemented" is terminal (no transitions) but healthy to reference.
    # "rejected", "superseded", "deprecated" are terminal AND dead.

    def format_id(self, number: int) -> str:
        return f"{self.prefix}-{number:0{self.digits}d}"

    def parse_number(self, doc_id: str) -> int:
        return int(doc_id.split("-", 1)[1])


ADR_DEFAULT = DocType(
    name="adr",
    prefix="ADR",
    digits=4,
    dir="docs/adr",
    initial_status="proposed",
    statuses=("proposed", "accepted", "rejected", "deprecated", "superseded"),
    transitions={
        "proposed": ("accepted", "rejected"),
        "accepted": ("deprecated", "superseded"),
        "rejected": (),
        "deprecated": (),
        "superseded": (),
    },
    actions={
        "accept": "accepted",
        "reject": "rejected",
        "deprecate": "deprecated",
        "supersede": "superseded",
    },
    warn_on_reference=("rejected", "deprecated", "superseded"),
    status_field_requirements={
        "proposed": (),
        "accepted": (),
        "rejected": (),
        "deprecated": (),
        "superseded": ("superseded-by",),
    },
    required_sections=(
        "Context and Problem Statement",
        "Considered Options",
        "Decision Outcome",
    ),
    section_descriptions={
        "Context and Problem Statement": "What is the issue or force motivating this decision?",
        "Considered Options": (
            "Bullet list of candidate options. Detailed pros/cons go in "
            "'Pros and Cons of the Options'."
        ),
        "Decision Outcome": (
            "State the chosen option and why. Use: "
            "'Chosen option: \"[option]\", because [justification]'."
        ),
        "Decision Drivers": "Bullet list of forces or concerns influencing the decision.",
        "Pros and Cons of the Options": "Detailed per-option pros/cons as H3 subsections.",
        "More Information": "Links to related ADRs, external references, meeting notes.",
    },
)
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/doruk/Desktop/SIDE_HUSTLE/decree && uv run pytest tests/test_doctypes.py -v`
Expected: All PASS

**Step 5: Run existing tests to verify nothing broke**

Run: `cd /Users/doruk/Desktop/SIDE_HUSTLE/decree && uv run pytest -v`
Expected: All existing tests still PASS (doctypes.py is additive, nothing imports it yet)

**Step 6: Commit**

```bash
git add src/decree/doctypes.py tests/test_doctypes.py
git commit -m "feat: add DocType dataclass — core abstraction for multi-type support"
```

---

## Task 2: Load DocTypes from pyproject.toml

**Files:**
- Modify: `src/decree/config.py` — add `load_doc_types()` function
- Test: `tests/test_config.py` — add tests for multi-type loading

This task wires DocType into the config system. `load_doc_types()` returns a list of DocTypes loaded from `[tool.doc.types.*]`, falling back to building a single ADR type from `[tool.adr]`.

**Step 1: Write failing tests**

```python
# Add to tests/test_config.py

from decree.doctypes import DocType
from decree.config import load_doc_types


def test_load_doc_types_from_tool_doc(tmp_path, monkeypatch):
    """[tool.doc.types.*] loads multiple types."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("""\
[project]
name = "test"

[tool.doc.types.adr]
dir = "docs/adr"
prefix = "ADR"
digits = 4
initial_status = "proposed"
statuses = ["proposed", "accepted", "rejected"]
required_sections = ["Context and Problem Statement"]

[tool.doc.types.adr.transitions]
proposed = ["accepted", "rejected"]
accepted = []
rejected = []

[tool.doc.types.adr.actions]
accept = "accepted"
reject = "rejected"

[tool.doc.types.prd]
dir = "docs/prd"
prefix = "PRD"
digits = 3
initial_status = "draft"
statuses = ["draft", "approved"]
required_sections = ["Problem Statement", "Requirements"]

[tool.doc.types.prd.transitions]
draft = ["approved"]
approved = []

[tool.doc.types.prd.actions]
approve = "approved"
""")
    monkeypatch.chdir(tmp_path)
    types = load_doc_types()
    assert len(types) == 2
    names = {t.name for t in types}
    assert names == {"adr", "prd"}


def test_load_doc_types_fallback_to_tool_adr(tmp_path, monkeypatch):
    """If no [tool.doc], falls back to [tool.adr] → single ADR type."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("""\
[project]
name = "test"

[tool.adr]
adr_dir = "my/adrs"
project_sections = ["Consequences"]
""")
    monkeypatch.chdir(tmp_path)
    types = load_doc_types()
    assert len(types) == 1
    assert types[0].name == "adr"
    assert types[0].dir == "my/adrs"
    assert "Consequences" in types[0].required_sections


def test_load_doc_types_no_config_returns_adr_default(tmp_path, monkeypatch):
    """If no [tool.doc] and no [tool.adr], returns ADR_DEFAULT."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\n')
    monkeypatch.chdir(tmp_path)
    types = load_doc_types()
    assert len(types) == 1
    assert types[0].name == "adr"
    assert types[0].prefix == "ADR"


def test_load_doc_types_validates_transitions_match_statuses(tmp_path, monkeypatch):
    """Transitions must only reference defined statuses."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("""\
[project]
name = "test"

[tool.doc.types.bad]
dir = "docs/bad"
prefix = "BAD"
digits = 3
initial_status = "draft"
statuses = ["draft", "done"]
required_sections = []

[tool.doc.types.bad.transitions]
draft = ["nonexistent"]
done = []

[tool.doc.types.bad.actions]
finish = "done"
""")
    monkeypatch.chdir(tmp_path)
    import pytest
    with pytest.raises(ValueError, match="nonexistent"):
        load_doc_types()


def test_load_doc_types_find_by_prefix(tmp_path, monkeypatch):
    """Can look up a type by its prefix."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("""\
[project]
name = "test"

[tool.doc.types.adr]
dir = "docs/adr"
prefix = "ADR"
digits = 4
initial_status = "proposed"
statuses = ["proposed", "accepted"]
required_sections = []

[tool.doc.types.adr.transitions]
proposed = ["accepted"]
accepted = []

[tool.doc.types.adr.actions]
accept = "accepted"

[tool.doc.types.prd]
dir = "docs/prd"
prefix = "PRD"
digits = 3
initial_status = "draft"
statuses = ["draft", "approved"]
required_sections = []

[tool.doc.types.prd.transitions]
draft = ["approved"]
approved = []

[tool.doc.types.prd.actions]
approve = "approved"
""")
    monkeypatch.chdir(tmp_path)
    from decree.config import find_doc_type
    assert find_doc_type("ADR-0001").name == "adr"
    assert find_doc_type("PRD-001").name == "prd"
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/doruk/Desktop/SIDE_HUSTLE/decree && uv run pytest tests/test_config.py::test_load_doc_types_from_tool_doc -v`
Expected: FAIL — `load_doc_types` not found

**Step 3: Implement load_doc_types**

Add to `config.py`:

```python
from .doctypes import DocType, ADR_DEFAULT

@functools.lru_cache(maxsize=1)
def load_doc_types() -> tuple[DocType, ...]:
    """Load document types from [tool.doc.types.*] or fall back to [tool.adr]."""
    pyproject = get_project_root() / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)

    tool = data.get("tool", {})
    doc_config = tool.get("doc", {}).get("types", {})

    if doc_config:
        return tuple(_build_doc_type(name, cfg) for name, cfg in doc_config.items())

    # Fallback: build ADR type from [tool.adr]
    adr_cfg = tool.get("adr", {})
    if adr_cfg:
        return (_adr_from_legacy_config(adr_cfg),)

    return (ADR_DEFAULT,)


def find_doc_type(doc_id: str) -> DocType:
    """Look up the DocType for a given document ID (e.g., 'ADR-0001' → adr type)."""
    for dt in load_doc_types():
        if dt.ref_re.match(doc_id):
            return dt
    raise ValueError(f"No document type matches ID '{doc_id}'")


def _build_doc_type(name: str, cfg: dict) -> DocType:
    """Build a DocType from a [tool.doc.types.*] config section."""
    statuses = tuple(cfg["statuses"])
    transitions = {k: tuple(v) for k, v in cfg.get("transitions", {}).items()}

    # Validate transitions reference valid statuses
    for src, targets in transitions.items():
        if src not in statuses:
            raise ValueError(f"Type '{name}': transition source '{src}' not in statuses")
        for t in targets:
            if t not in statuses:
                raise ValueError(f"Type '{name}': transition target '{t}' not in statuses {statuses}")

    # Fill missing terminal statuses
    for s in statuses:
        if s not in transitions:
            transitions[s] = ()

    return DocType(
        name=name,
        prefix=cfg["prefix"],
        digits=cfg.get("digits", 4),
        dir=cfg.get("dir", f"docs/{name}"),
        initial_status=cfg.get("initial_status", statuses[0]),
        statuses=statuses,
        transitions=transitions,
        actions=cfg.get("actions", {}),
        warn_on_reference=tuple(cfg.get("warn_on_reference", ())),
        required_sections=tuple(cfg.get("required_sections", ())),
        status_field_requirements=_parse_field_requirements(cfg),
        section_descriptions=cfg.get("section_descriptions", {}),
        template=cfg.get("template"),
    )


def _adr_from_legacy_config(cfg: dict) -> DocType:
    """Build ADR DocType from legacy [tool.adr] config."""
    from .doctypes import ADR_DEFAULT
    extra_sections = tuple(cfg.get("project_sections", ()))
    return DocType(
        name=ADR_DEFAULT.name,
        prefix=ADR_DEFAULT.prefix,
        digits=ADR_DEFAULT.digits,
        dir=cfg.get("adr_dir", ADR_DEFAULT.dir),
        initial_status=ADR_DEFAULT.initial_status,
        statuses=ADR_DEFAULT.statuses,
        transitions=ADR_DEFAULT.transitions,
        actions=ADR_DEFAULT.actions,
        required_sections=(*ADR_DEFAULT.required_sections, *extra_sections),
        status_field_requirements=ADR_DEFAULT.status_field_requirements,
        section_descriptions={
            **ADR_DEFAULT.section_descriptions,
            **cfg.get("project_section_descriptions", {}),
        },
        template=cfg.get("template"),
    )


def _parse_field_requirements(cfg: dict) -> dict[str, tuple[str, ...]]:
    """Parse status_field_requirements from config, defaulting to empty."""
    raw = cfg.get("status_field_requirements", {})
    return {k: tuple(v) for k, v in raw.items()}
```

**Step 4: Update conftest.py cache clearing**

Add `load_doc_types` to the reset fixture:

```python
@pytest.fixture(autouse=True)
def reset_caches():
    from decree.config import get_project_root, _load_project_config, load_doc_types
    get_project_root.cache_clear()
    _load_project_config.cache_clear()
    load_doc_types.cache_clear()
    yield
    get_project_root.cache_clear()
    _load_project_config.cache_clear()
    load_doc_types.cache_clear()
```

**Step 5: Run all tests**

Run: `cd /Users/doruk/Desktop/SIDE_HUSTLE/decree && uv run pytest -v`
Expected: All PASS (existing + new)

**Step 6: Commit**

```bash
git add src/decree/config.py tests/test_config.py tests/conftest.py
git commit -m "feat: load DocTypes from [tool.doc.types.*] with [tool.adr] fallback"
```

---

## Task 3: Generalize parser — DocFrontmatter + DocDocument

**Files:**
- Modify: `src/decree/parser.py`
- Test: `tests/test_parser.py` — update + add type-parameterized tests

The key change: `ADRFrontmatter` becomes `DocFrontmatter`. Status validation uses Pydantic v2 context to accept type-specific statuses. `ADRDocument` becomes `DocDocument`. All I/O functions accept a `DocType` parameter.

**Step 1: Write failing tests for DocFrontmatter**

```python
# Add to tests/test_parser.py

from decree.doctypes import DocType

def _make_prd_type():
    return DocType(
        name="prd", prefix="PRD", digits=3, dir="docs/prd",
        initial_status="draft",
        statuses=("draft", "review", "approved", "implemented"),
        transitions={"draft": ("review",), "review": ("approved",), "approved": ("implemented",), "implemented": ()},
        actions={"submit": "review", "approve": "approved"},
        required_sections=("Problem Statement",),
    )

def test_doc_frontmatter_validates_custom_statuses():
    """DocFrontmatter accepts statuses from DocType context."""
    from decree.parser import DocFrontmatter
    prd = _make_prd_type()
    fm = DocFrontmatter.model_validate(
        {"status": "draft", "date": "2026-04-05"},
        context={"doc_type": prd},
    )
    assert fm.status == "draft"

def test_doc_frontmatter_rejects_invalid_status_for_type():
    from decree.parser import DocFrontmatter
    import pytest
    prd = _make_prd_type()
    with pytest.raises(Exception, match="Invalid status"):
        DocFrontmatter.model_validate(
            {"status": "accepted", "date": "2026-04-05"},
            context={"doc_type": prd},
        )

def test_doc_frontmatter_references_field():
    """DocFrontmatter supports optional references list."""
    from decree.parser import DocFrontmatter
    fm = DocFrontmatter.model_validate(
        {"status": "proposed", "date": "2026-04-05", "references": ["PRD-001", "SPEC-001"]},
    )
    assert fm.references == ["PRD-001", "SPEC-001"]

def test_doc_document_id_for_custom_type(tmp_path):
    """DocDocument.doc_id uses DocType prefix and digits."""
    from decree.parser import DocFrontmatter, DocDocument
    prd = _make_prd_type()
    path = tmp_path / "001-user-auth.md"
    meta = DocFrontmatter.model_validate(
        {"status": "draft", "date": "2026-04-05"},
        context={"doc_type": prd},
    )
    doc = DocDocument(path=path, meta=meta, body="# PRD-001 User Auth", doc_type=prd)
    assert doc.doc_id == "PRD-001"
    assert doc.number == 1

def test_load_with_doc_type(project_dir):
    """load() works with a DocType parameter."""
    from decree.parser import load, DocDocument
    from decree.doctypes import ADR_DEFAULT
    adr_dir = project_dir / "docs" / "adr"
    adr_file = adr_dir / "0001-test.md"
    adr_file.write_text("---\nstatus: proposed\ndate: 2026-04-05\n---\n# ADR-0001 Test\n\n## Context and Problem Statement\n")
    doc = load(adr_file, doc_type=ADR_DEFAULT)
    assert isinstance(doc, DocDocument)
    assert doc.doc_id == "ADR-0001"

def test_find_by_id_with_doc_type(project_dir, monkeypatch):
    """find_by_id resolves type from ID prefix."""
    from decree.parser import find_by_id
    monkeypatch.chdir(project_dir)
    adr_dir = project_dir / "docs" / "adr"
    (adr_dir / "0001-test.md").write_text("---\nstatus: proposed\ndate: 2026-04-05\n---\n# ADR-0001 Test\n")
    doc = find_by_id("ADR-0001")
    assert doc.doc_id == "ADR-0001"
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/doruk/Desktop/SIDE_HUSTLE/decree && uv run pytest tests/test_parser.py::test_doc_frontmatter_validates_custom_statuses -v`
Expected: FAIL

**Step 3: Implement generalized parser**

Key changes to `parser.py`:
1. Rename `ADRFrontmatter` → `DocFrontmatter` (keep `ADRFrontmatter = DocFrontmatter` alias)
2. Add `references: list[str] | None = None` field
3. Status validator uses `info.context["doc_type"].statuses` when context is provided, falls back to `STATUSES` for backward compat
4. Rename `ADRDocument` → `DocDocument` (keep alias), add `doc_type` attribute
5. `doc_id` property uses `doc_type.format_id()` instead of hardcoded `f"ADR-{match.group(1)}"`
6. `load()` accepts optional `doc_type` parameter, defaults to ADR
7. `load_all()` accepts `doc_type` parameter
8. `find_by_id()` auto-detects type from ID prefix via `config.find_doc_type()`
9. `next_number()` (renamed from `next_adr_number()`) accepts `doc_type`

**Critical: backward compatibility.** Keep these aliases at module level:
```python
ADRFrontmatter = DocFrontmatter
ADRDocument = DocDocument
next_adr_number = lambda: next_number(ADR_DEFAULT)
```

**Step 4: Run ALL tests**

Run: `cd /Users/doruk/Desktop/SIDE_HUSTLE/decree && uv run pytest -v`
Expected: All PASS — old tests use old names (aliases), new tests use new names

**Step 5: Commit**

```bash
git add src/decree/parser.py tests/test_parser.py
git commit -m "feat: generalize parser — DocFrontmatter + DocDocument with DocType parameter"
```

---

## Task 4: Generalize `new` command

**Files:**
- Modify: `src/decree/commands/new.py`
- Modify: `src/decree/template.py`
- Create: `src/decree/templates/prd.md`
- Create: `src/decree/templates/spec.md`
- Test: `tests/test_new.py`

**Step 1: Write failing tests**

```python
# Add to tests/test_new.py
import argparse
from decree.commands.new import run

def _prd_project(tmp_path):
    """Set up a project with PRD type configured."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("""\
[project]
name = "test"

[tool.doc.types.prd]
dir = "docs/prd"
prefix = "PRD"
digits = 3
initial_status = "draft"
statuses = ["draft", "approved"]
required_sections = ["Problem Statement", "Requirements"]

[tool.doc.types.prd.transitions]
draft = ["approved"]
approved = []

[tool.doc.types.prd.actions]
approve = "approved"
""")
    (tmp_path / "docs" / "prd").mkdir(parents=True)
    return tmp_path

def test_new_prd_creates_file(monkeypatch, tmp_path):
    proj = _prd_project(tmp_path)
    monkeypatch.chdir(proj)
    args = argparse.Namespace(title="User Authentication", doc_type="prd")
    result = run(args)
    assert result == 0
    created = proj / "docs" / "prd" / "001-user-authentication.md"
    assert created.exists()

def test_new_prd_frontmatter_has_draft_status(monkeypatch, tmp_path):
    proj = _prd_project(tmp_path)
    monkeypatch.chdir(proj)
    args = argparse.Namespace(title="User Auth", doc_type="prd")
    run(args)
    content = (proj / "docs" / "prd" / "001-user-auth.md").read_text()
    assert "status: draft" in content

def test_new_prd_has_correct_heading(monkeypatch, tmp_path):
    proj = _prd_project(tmp_path)
    monkeypatch.chdir(proj)
    args = argparse.Namespace(title="User Auth", doc_type="prd")
    run(args)
    content = (proj / "docs" / "prd" / "001-user-auth.md").read_text()
    assert "# PRD-001 User Auth" in content

def test_new_adr_still_works(monkeypatch, project_dir):
    """Backward compat: doc_type='adr' or absent uses ADR defaults."""
    monkeypatch.chdir(project_dir)
    args = argparse.Namespace(title="Use Redis", doc_type="adr")
    result = run(args)
    assert result == 0
    created = project_dir / "docs" / "adr" / "0001-use-redis.md"
    assert created.exists()
    content = created.read_text()
    assert "status: proposed" in content
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/doruk/Desktop/SIDE_HUSTLE/decree && uv run pytest tests/test_new.py::test_new_prd_creates_file -v`
Expected: FAIL

**Step 3: Create built-in templates**

```markdown
<!-- src/decree/templates/prd.md -->
---
status: __INITIAL_STATUS__
date: __DATE__
---

# __PREFIX__-__NUMBER__ __TITLE__

## Problem Statement

What user problem does this solve?

## Requirements

- Requirement 1
- Requirement 2

## Success Criteria

- Criterion 1
- Criterion 2

## Scope

What is in scope and out of scope?
```

```markdown
<!-- src/decree/templates/spec.md -->
---
status: __INITIAL_STATUS__
date: __DATE__
---

# __PREFIX__-__NUMBER__ __TITLE__

## Overview

High-level description of the technical design.

## Technical Design

Detailed design and architecture.

## Testing Strategy

How this will be tested.
```

**Step 4: Update template.py**

`render_template` now accepts a `DocType` to fill `__PREFIX__`, `__INITIAL_STATUS__`, and use type-specific section descriptions.

**Step 5: Update new.py**

`run()` resolves `args.doc_type` name → `DocType` instance, uses its `dir`, `digits`, `initial_status`, and template. Falls back to ADR type when `doc_type` is not provided or is `"adr"`.

**Step 6: Run ALL tests**

Run: `cd /Users/doruk/Desktop/SIDE_HUSTLE/decree && uv run pytest -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add src/decree/commands/new.py src/decree/template.py \
        src/decree/templates/prd.md src/decree/templates/spec.md \
        tests/test_new.py
git commit -m "feat: new command supports multiple document types with built-in templates"
```

---

## Task 5: Generalize `status` command

**Files:**
- Modify: `src/decree/commands/status.py`
- Test: `tests/test_status.py`

Key change: `status.py` auto-detects DocType from the ID prefix. Uses type-specific transitions and actions. Supersede logic stays ADR-specific (only ADRs have supersede semantics in the built-in config).

**Step 1: Write failing tests**

```python
# Add to tests/test_status.py

def test_status_transition_prd(monkeypatch, tmp_path):
    """PRD-001 can transition draft → review."""
    proj = _prd_project(tmp_path)  # same helper as Task 4
    monkeypatch.chdir(proj)
    # Create PRD-001
    prd_dir = proj / "docs" / "prd"
    (prd_dir / "001-user-auth.md").write_text(
        "---\nstatus: draft\ndate: 2026-04-05\n---\n# PRD-001 User Auth\n\n## Problem Statement\n\n## Requirements\n\n## Success Criteria\n"
    )
    args = argparse.Namespace(action="submit", doc_id="PRD-001", target_id=None)
    result = run(args)
    assert result == 0
    import frontmatter
    post = frontmatter.load(str(prd_dir / "001-user-auth.md"))
    assert post["status"] == "review"

def test_status_invalid_transition_prd(monkeypatch, tmp_path):
    """PRD-001 cannot transition draft → implemented."""
    proj = _prd_project(tmp_path)
    monkeypatch.chdir(proj)
    prd_dir = proj / "docs" / "prd"
    (prd_dir / "001-user-auth.md").write_text(
        "---\nstatus: draft\ndate: 2026-04-05\n---\n# PRD-001 User Auth\n"
    )
    args = argparse.Namespace(action="implement", doc_id="PRD-001", target_id=None)
    result = run(args)
    assert result == 1  # rejected
```

**Step 2: Implement**

`status.py` changes:
1. Resolve DocType from `args.doc_id` via `find_doc_type()`
2. Look up action → target_status from `doc_type.actions` (instead of hardcoded `STATUS_ACTION_MAP`)
3. Use `doc_type.transitions` instead of `VALID_TRANSITIONS`
4. Supersede logic only when target_status is `"superseded"` and doc_type has supersede semantics

**Step 3: Run ALL tests**

Run: `cd /Users/doruk/Desktop/SIDE_HUSTLE/decree && uv run pytest -v`

**Step 4: Commit**

```bash
git add src/decree/commands/status.py tests/test_status.py
git commit -m "feat: status command supports type-specific transitions via DocType"
```

---

## Task 6: Generalize `lint` command + cross-type validation

**Files:**
- Modify: `src/decree/commands/lint.py`
- Modify: `src/decree/validators.py`
- Test: `tests/test_lint.py`, `tests/test_validators.py`

Lint now iterates all configured DocTypes. Cross-type validation checks that `references` point to existing documents and warns when referencing superseded/rejected/deprecated entries.

**Step 1: Write failing tests**

```python
# Add to tests/test_validators.py

def test_validate_cross_type_references_valid(tmp_path, monkeypatch):
    """PRD-001 references ADR-0001 — both exist, no errors."""
    from decree.validators import validate_cross_type_references
    from decree.parser import DocFrontmatter, DocDocument
    from decree.doctypes import ADR_DEFAULT

    prd_type = _make_prd_type()
    adr_meta = DocFrontmatter.model_validate({"status": "accepted", "date": "2026-04-05"})
    adr_doc = DocDocument(path=tmp_path / "0001-test.md", meta=adr_meta, body="", doc_type=ADR_DEFAULT)

    prd_meta = DocFrontmatter.model_validate(
        {"status": "draft", "date": "2026-04-05", "references": ["ADR-0001"]},
        context={"doc_type": prd_type},
    )
    prd_doc = DocDocument(path=tmp_path / "001-auth.md", meta=prd_meta, body="", doc_type=prd_type)

    errors = validate_cross_type_references([adr_doc, prd_doc])
    assert errors == []


def test_validate_cross_type_references_missing():
    """PRD-001 references ADR-0099 which doesn't exist."""
    # ... similar setup, assert error contains "ADR-0099"


def test_validate_cross_type_references_stale():
    """PRD-001 references ADR-0001 which is superseded → warning."""
    # ... assert error contains "superseded"
```

```python
# Add to tests/test_lint.py

def test_lint_validates_all_types(monkeypatch, tmp_path):
    """lint checks both ADR and PRD directories."""
    # Set up multi-type project with valid ADR + invalid PRD (missing section)
    # Assert exit code 1, error mentions the PRD issue
```

**Step 2: Implement**

Add to `validators.py`:
```python
def validate_cross_type_references(docs: list[DocDocument]) -> list[str]:
    """Check references: existence, self-refs, and warn_on_reference statuses."""
    errors = []
    docs_by_id = {d.doc_id: d for d in docs}

    for doc in docs:
        if not doc.meta.references:
            continue
        for ref_id in doc.meta.references:
            if ref_id == doc.doc_id:
                errors.append(f"CROSS-TYPE: {doc.doc_id} references itself (self-reference)")
            elif ref_id not in docs_by_id:
                errors.append(f"CROSS-TYPE: {doc.doc_id} references {ref_id} which does not exist")
            else:
                target = docs_by_id[ref_id]
                target_type = target.doc_type
                if target.meta.status in target_type.warn_on_reference:
                    errors.append(
                        f"CROSS-TYPE: {doc.doc_id} references {ref_id} "
                        f"(status: {target.meta.status})"
                    )
    return errors
```

Update `lint.py`:
```python
def run(args):
    doc_types = load_doc_types()
    all_docs = []
    errors = []

    for dt in doc_types:
        # Per-type validation (same as current, but type-parameterized)
        type_dir = get_project_root() / dt.dir
        if not type_dir.exists():
            continue
        paths = sorted(p for p in type_dir.glob("[0-9]*.md") if dt.filename_re.match(p.name))
        for path in paths:
            doc = load(path, doc_type=dt)
            all_docs.append(doc)
            section_errors = validate_sections(doc)
            errors.extend(...)

        # Per-type cross-file checks (supersede symmetry, etc.)
        type_docs = [d for d in all_docs if d.doc_type == dt]
        errors.extend(validate_cross_file_integrity(type_docs))

    # Cross-type checks
    errors.extend(validate_cross_type_references(all_docs))
```

**Step 3: Run ALL tests**

**Step 4: Commit**

```bash
git add src/decree/commands/lint.py src/decree/validators.py \
        tests/test_lint.py tests/test_validators.py
git commit -m "feat: lint validates all document types + cross-type reference integrity"
```

---

## Task 7: Generalize `index` command

**Files:**
- Modify: `src/decree/commands/index.py`
- Test: `tests/test_index.py`

Generates one index file per document type in each type's directory.

**Step 1: Write failing test**

```python
def test_index_generates_per_type(monkeypatch, tmp_path):
    # Multi-type project with ADR + PRD
    # Assert docs/adr/index.md and docs/prd/index.md both created
```

**Step 2: Implement**

`index.py` iterates `load_doc_types()`, generates one table per type.

**Step 3: Run ALL tests, commit**

```bash
git commit -m "feat: index command generates per-type index files"
```

---

## Task 8: Generalize `graph` command

**Files:**
- Modify: `src/decree/commands/graph.py`
- Test: `tests/test_graph.py` (new file)

Graph now shows cross-type relationships. Different node colors per document type. Cross-type edges from the `references` field.

**Step 1: Write failing tests**

```python
def test_graph_cross_type_edges():
    """PRD-001 references ADR-0001 → graph shows edge between them."""

def test_graph_multi_type_nodes():
    """Nodes from different types have different colors."""
```

**Step 2: Implement**

Add a new `_cross_type_graph()` function that renders all types as a single Mermaid graph. Each type gets a color scheme. Edges come from both `supersedes` (within-type) and `references` (cross-type).

**Step 3: Run ALL tests, commit**

```bash
git commit -m "feat: graph command shows cross-type relationships with colored nodes"
```

---

## Task 9: `doc` CLI entry point

**Files:**
- Modify: `src/decree/cli.py` — add `doc_main()` entry point
- Modify: `pyproject.toml` — add `doc = "decree.cli:doc_main"` script
- Test: `tests/test_cli.py`

**Step 1: Write failing tests**

```python
def test_doc_new_subcommand():
    """doc new prd 'title' parses correctly."""

def test_doc_status_subcommand():
    """doc status PRD-001 approved parses correctly."""

def test_doc_lint_subcommand():
    """doc lint works."""

def test_adr_backward_compat():
    """adr new 'title' still works (defaults to adr type)."""
```

**Step 2: Implement**

```python
def doc_main() -> int:
    """Multi-type document CLI."""
    parser = argparse.ArgumentParser(prog="doc", description="Structured document management toolkit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_new = subparsers.add_parser("new")
    p_new.add_argument("doc_type", help="Document type (adr, prd, spec, ...)")
    p_new.add_argument("title", help="Title of the document")

    p_status = subparsers.add_parser("status")
    p_status.add_argument("doc_id", help="Document ID (e.g., ADR-0001, PRD-001)")
    p_status.add_argument("action", help="Action to perform (e.g., accept, approve)")
    p_status.add_argument("target_id", nargs="?", default=None)

    subparsers.add_parser("lint")
    subparsers.add_parser("index")
    subparsers.add_parser("graph")

    args = parser.parse_args()
    commands = {"new": new.run, "status": status.run, "lint": lint.run, "index": index.run, "graph": graph.run}
    return commands[args.command](args)
```

Update `pyproject.toml`:
```toml
[project.scripts]
adr = "decree.cli:main"
doc = "decree.cli:doc_main"
```

**Step 3: Run ALL tests, commit**

```bash
git commit -m "feat: add 'doc' CLI entry point for multi-type document management"
```

---

## Task 10: End-to-end integration test — the killer combination

**Files:**
- Create: `tests/test_integration.py`

This test validates the complete scenario from top to bottom.

**Step 1: Write the integration test**

```python
"""End-to-end: the killer combination.

PRD-001 references ADR-0003.
SPEC-001 references PRD-001.
ADR-0003 gets superseded by ADR-0004.
Lint catches the stale reference chain.
"""
import argparse
from decree.commands import new, status, lint


def test_killer_combination(monkeypatch, tmp_path):
    # 1. Set up multi-type project
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(MULTI_TYPE_CONFIG)
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "prd").mkdir(parents=True)
    (tmp_path / "docs" / "spec").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    # 2. Create ADR-0001, ADR-0002, ADR-0003
    for title in ["Use Redis", "Use PostgreSQL", "Auth via JWT"]:
        new.run(argparse.Namespace(title=title, doc_type="adr"))

    # 3. Accept ADR-0003
    status.run(argparse.Namespace(action="accept", doc_id="ADR-0003", target_id=None))

    # 4. Create PRD-001 referencing ADR-0003
    new.run(argparse.Namespace(title="User Authentication", doc_type="prd"))
    prd_path = tmp_path / "docs" / "prd" / "001-user-authentication.md"
    _add_references(prd_path, ["ADR-0003"])

    # 5. Create SPEC-001 referencing PRD-001
    new.run(argparse.Namespace(title="Auth API Design", doc_type="spec"))
    spec_path = tmp_path / "docs" / "spec" / "001-auth-api-design.md"
    _add_references(spec_path, ["PRD-001"])

    # 6. Lint should pass — all references valid
    assert lint.run(None) == 0

    # 7. Create ADR-0004 and supersede ADR-0003
    new.run(argparse.Namespace(title="Auth via OAuth2", doc_type="adr"))
    status.run(argparse.Namespace(action="accept", doc_id="ADR-0004", target_id=None))
    status.run(argparse.Namespace(action="supersede", doc_id="ADR-0003", target_id="ADR-0004"))

    # 8. Lint should WARN — PRD-001 references ADR-0003 (superseded)
    assert lint.run(None) == 1  # errors/warnings found


def _add_references(path, refs):
    """Inject references into a document's frontmatter."""
    import frontmatter
    post = frontmatter.load(str(path))
    post["references"] = refs
    path.write_text(frontmatter.dumps(post).rstrip() + "\n")


MULTI_TYPE_CONFIG = """\
[project]
name = "test-project"

[tool.doc.types.adr]
dir = "docs/adr"
prefix = "ADR"
digits = 4
initial_status = "proposed"
statuses = ["proposed", "accepted", "rejected", "deprecated", "superseded"]
required_sections = ["Context and Problem Statement", "Considered Options", "Decision Outcome"]

[tool.doc.types.adr.transitions]
proposed = ["accepted", "rejected"]
accepted = ["deprecated", "superseded"]
rejected = []
deprecated = []
superseded = []

[tool.doc.types.adr.actions]
accept = "accepted"
reject = "rejected"
deprecate = "deprecated"
supersede = "superseded"

[tool.doc.types.adr.status_field_requirements]
superseded = ["superseded-by"]

[tool.doc.types.prd]
dir = "docs/prd"
prefix = "PRD"
digits = 3
initial_status = "draft"
statuses = ["draft", "review", "approved", "implemented"]
required_sections = ["Problem Statement", "Requirements", "Success Criteria"]

[tool.doc.types.prd.transitions]
draft = ["review"]
review = ["approved", "draft"]
approved = ["implemented"]
implemented = []

[tool.doc.types.prd.actions]
submit = "review"
approve = "approved"
implement = "implemented"

[tool.doc.types.spec]
dir = "docs/spec"
prefix = "SPEC"
digits = 3
initial_status = "draft"
statuses = ["draft", "approved", "implemented"]
required_sections = ["Overview", "Technical Design", "Testing Strategy"]

[tool.doc.types.spec.transitions]
draft = ["approved"]
approved = ["implemented"]
implemented = []

[tool.doc.types.spec.actions]
approve = "approved"
implement = "implemented"
"""
```

**Step 2: Run the integration test**

Run: `cd /Users/doruk/Desktop/SIDE_HUSTLE/decree && uv run pytest tests/test_integration.py -v`
Expected: PASS — all tasks are implemented, the full chain works

**Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: end-to-end killer combination — cross-type references and stale cascade"
```

---

## Summary

| Task | What | Depends On |
|------|------|-----------|
| 1 | DocType dataclass + ADR_DEFAULT | — |
| 2 | load_doc_types() from pyproject.toml | 1 |
| 3 | Generalize parser (DocFrontmatter, DocDocument) | 1, 2 |
| 4 | Generalize `new` + built-in templates | 3 |
| 5 | Generalize `status` | 3 |
| 6 | Generalize `lint` + cross-type validation | 3 |
| 7 | Generalize `index` | 3 |
| 8 | Generalize `graph` — cross-type edges | 3, 6 |
| 9 | `doc` CLI entry point | 4, 5, 6, 7 |
| 10 | Integration test — the killer combination | all |

## Not In Scope (Future)

- Package rename from `decree` to something generic
- Typed relationships (e.g., `implements: PRD-001` vs generic `references`)
- `doc query` command
- doctrace integration (separate tool, reads same files)
- Custom templates per type via config
