---
status: draft
date: 2026-04-05
references: [PRD-001, ADR-0001]
---

# SPEC-001 C4 Validation and Diagram Generation

## Overview

Add opt-in C4 architecture support to decree. When `[types.spec.c4]` is configured, decree validates C4 hierarchy metadata in spec frontmatter and generates C4Container Mermaid diagrams. All C4 code lives in `src/decree/c4.py` (ADR-0001: coupled module, not plugin).

## Technical Design

### Config schema

```toml
# decree.toml
[types.spec.c4]
enabled = true
id_field = "id"                                        # frontmatter field for C4 node ID
levels = ["system", "container", "component"]          # valid c4_type values
```

Parsed into a frozen dataclass on DocType:

```python
# src/decree/c4.py
@dataclass(frozen=True)
class C4Config:
    enabled: bool
    id_field: str           # default "id"
    levels: tuple[str, ...]  # valid c4_type values
```

DocType gains: `c4: C4Config | None = None`

### Spec frontmatter (C4 fields)

```yaml
---
# decree lifecycle (existing)
status: approved
date: 2026-04-05
references: [PRD-001, ADR-0001]

# C4 component metadata (new, validated when c4 enabled)
id: demand_model
c4_type: container
c4_name: Demand Model
c4_tech: Python / scipy       # optional
parent: markdown_optimization_poc   # optional, must resolve to another spec's id
depends-on: ["data_preparation"]     # optional, each must resolve
---
```

Required when C4 enabled: `id`, `c4_type`, `c4_name`.
Optional: `c4_tech`, `parent`, `depends-on`.

### Parser changes

`DocFrontmatter` already uses `model_config = {"populate_by_name": True}`. C4 fields are parsed as extra fields. When `doc_type.c4` is set, `c4.py` validates them after parsing.

No changes to DocFrontmatter model — C4 fields are accessed via `post.metadata` (the raw dict from python-frontmatter), not via Pydantic fields.

### Validation (`c4.py`)

```python
def validate_c4(docs: list[DocDocument]) -> list[str]:
    """Validate C4 metadata across all docs of a C4-enabled type."""
```

Checks (in order):
1. **Field presence**: every doc must have `id`, `c4_type`, `c4_name`
2. **c4_type validity**: must be one of `c4_config.levels`
3. **Duplicate C4 ids**: no two docs may share the same `id` value
4. **Parent resolution**: `parent` value must match another doc's `id`
5. **Depends-on resolution**: each entry must match another doc's `id`
6. **Dead node filtering**: skip docs with status in `doc_type.warn_on_reference`

Error format: `C4: SPEC-001 (demand_model): parent 'nonexistent' not found`

### Diagram generation (`c4.py`)

```python
def generate_c4_container(docs: list[DocDocument], c4_config: C4Config) -> str:
    """Generate Mermaid C4Container diagram."""
```

- Groups containers by system parent (system boundary boxes)
- Shows containers with c4_name, c4_tech, and brief description
- Draws `depends-on` edges between containers
- Skips dead/superseded docs

Called from `commands/graph.py` after existing diagram generation, only when `doc_type.c4` is set.

### Template changes

When `doc_type.c4` is enabled, `decree new spec "title"` generates:

```yaml
---
status: draft
date: __DATE__

id: __SLUG__
c4_type: container
c4_name: __TITLE__
c4_tech: ""
parent: ""
depends-on: []
---
```

### Files touched

- Create: `src/decree/c4.py` — C4Config dataclass, validate_c4(), generate_c4_container()
- Modify: `src/decree/doctypes.py` — add `c4: C4Config | None` field
- Modify: `src/decree/config.py` — parse `[types.*.c4]` section
- Modify: `src/decree/commands/lint.py` — call validate_c4() for C4-enabled types
- Modify: `src/decree/commands/graph.py` — call generate_c4_container() for C4-enabled types
- Modify: `src/decree/commands/new.py` — scaffold C4 fields in template when enabled
- Create: `tests/test_c4.py` — C4-specific tests

### What this does NOT do (deferred to v2)

- [ ] produces/consumes contract validation
- [ ] Data flow Mermaid diagram
- [ ] External system declarations (`[types.spec.c4.externals]`)
- [ ] Level-ordering enforcement (component's parent must be container)
- [ ] c4_tech validation

## v1 Acceptance Criteria

- [x] C4Config dataclass in `c4.py`
- [x] DocType gains `c4` field
- [x] Config parses `[types.*.c4]` section from decree.toml
- [x] Validate: missing required C4 fields (id, c4_type, c4_name)
- [x] Validate: invalid c4_type against configured levels
- [x] Validate: duplicate C4 ids
- [x] Validate: parent resolves to another spec's C4 id
- [x] Validate: depends-on entries resolve
- [x] Filter dead/superseded docs from C4 processing
- [x] `decree lint` calls validate_c4 for C4-enabled types
- [x] `decree graph` generates C4Container Mermaid diagram
- [x] Non-C4 projects: zero behavioral change
- [x] 18 C4 unit tests pass
- [x] 160 total tests pass (142 existing + 18 new)
- [x] CLAUDE.md, README.md, --help updated

## Testing Strategy

### Unit tests (`tests/test_c4.py`)

- [x] `validate_c4` with all valid docs → empty errors
- [x] Missing required C4 field → error message identifies doc and field
- [x] Invalid c4_type → error with valid options
- [x] Duplicate C4 ids → error identifying both docs
- [x] Parent resolves correctly → no error
- [x] Parent doesn't resolve → error with suggestion
- [x] Depends-on resolves → no error
- [x] Depends-on entry missing → error identifying which entry
- [x] Dead/superseded docs filtered out → not validated, not in diagram
- [x] Non-C4 type → validate_c4 returns empty (no-op)
- [x] C4Container diagram generated with system boundaries and edges
- [x] Disabled C4 returns None
- [x] Config loaded from decree.toml
- [x] No C4 section means c4 = None

### Integration

- [x] Full lint with C4-enabled type passes
- [x] Non-C4 project: all 142 existing tests unchanged

### Regression

- [x] 160/160 tests pass
