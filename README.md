# decree

Software decision lifecycle toolkit. Track the chain from business need (PRD) through architecture decision (ADR) to technical design (SPEC) — with cross-type references, status enforcement, and validation.

## Document Model

![Decree document model](docs/model.png)

| Type | Purpose | Lifecycle | Example |
|------|---------|-----------|---------|
| **PRD** | What to build and why | draft → review → approved → implemented → archived | PRD-001 "User Auth" |
| **ADR** | Architecture decisions | proposed → accepted / rejected / deprecated / superseded | ADR-0001 "Use SQLite" |
| **SPEC** | Technical blueprint | draft → review → approved → implemented | SPEC-001 "Storage API" |

## Decree Driven Development

```
Without decree:
  idea → brainstorming → write plan → execute → code

With decree:
  idea → /decree:prd → /decree:adr → /decree:spec → write plan → execute → code
           (what)        (how)         (blueprint)     (tasks)      (build)
```

Decree owns **decisions**. Your planning/execution tools own **implementation**. The SPEC is the handoff point — decree produces it, your planner consumes it.

Run `/decree:ddd` to see where you are:

```
$ /decree:ddd

Checking project state...

decree progress:
  PRD-001   User Auth        approved   ██████████ 100%
  ADR-0001  Use JWT          accepted   ██████████ 100%
  SPEC-001  Token Storage    draft      ░░░░░░░░░░   0% (0/8)

→ SPEC-001 has acceptance criteria but 0% progress.
  Next: write an implementation plan from this spec.

  Option A: /superpowers:write-plan (reads SPEC-001 as input)
  Option B: Start implementing directly
  Option C: The spec needs more work first
```

## Install

```bash
uv tool install decree
```

## Quick Start

```bash
# Create documents
decree new prd "User Authentication"
decree new adr "Auth via JWT"
decree new spec "Token Storage"

# Add cross-references (in YAML frontmatter)
# ADR-0001: references: [PRD-001]
# SPEC-001: references: [PRD-001, ADR-0001]

# Validate everything
decree lint

# Track progress (counts checkboxes in docs)
decree progress
```

Output:

```
$ decree progress
  ADR-0001  Auth via JWT    accepted   ███████░░░  67% (2/3)
  PRD-001   User Auth       approved   █████░░░░░  50% (3/6)
  SPEC-001  Token Storage   draft      ███░░░░░░░  29% (2/7)

  ✓ 7/16 items complete (44%) across 3 documents
```

## Commands

| Command | What it does |
|---------|-------------|
| `decree new <type> "title"` | Create a new document |
| `decree status <ID> <action>` | Transition document status |
| `decree lint` | Validate all types + cross-type references + C4 |
| `decree index` | Regenerate per-type index files |
| `decree graph` | Generate Mermaid diagrams + C4 container view |
| `decree progress` | Show checkbox completion across all docs |

## Configuration

Create `decree.toml` in your project root:

```toml
[types.prd]
dir = "decree/prd"
prefix = "PRD"
digits = 3
initial_status = "draft"
statuses = ["draft", "review", "approved", "implemented", "archived"]
warn_on_reference = ["archived"]
required_sections = ["Problem Statement", "Requirements", "Success Criteria"]

[types.prd.transitions]
draft = ["review"]
review = ["approved", "draft"]
approved = ["implemented", "archived"]
implemented = ["archived"]
archived = []

[types.prd.actions]
approve = "approved"
implement = "implemented"
```

See [docs/configuration.md](docs/configuration.md) for full schema with ADR and SPEC examples.

## What decree validates

- **Dangling references** — SPEC-001 references ADR-0099 which doesn't exist
- **Stale references** — ADR-0001 references PRD-001 which is archived
- **Self-references** — document references itself (copy-paste mistake)
- **Duplicate IDs** — two files map to the same ADR-0001
- **Supersede symmetry** — ADR-0001 says superseded-by ADR-0002, but ADR-0002 doesn't say supersedes ADR-0001
- **Missing sections** — SPEC-001 is missing required "Testing Strategy" section
- **C4 hierarchy** (opt-in) — parent/depends-on don't resolve, duplicate C4 ids, invalid c4_type

## C4 Architecture Support

Add `[types.spec.c4]` to `decree.toml` to enable C4 validation on SPECs:

```toml
[types.spec.c4]
enabled = true
id_field = "id"
levels = ["system", "container", "component"]
```

Specs gain C4 fields in frontmatter:

```yaml
---
status: approved
date: 2026-04-05
references: [PRD-001, ADR-0001]

id: demand_model
c4_type: container
c4_name: Demand Model
c4_tech: Python / scipy
parent: markdown_optimization_poc
depends-on: ["data_preparation"]
---
```

`decree lint` validates C4 hierarchy. `decree graph` generates C4Container Mermaid diagrams. Non-C4 projects are unaffected.

## Key design

- **`warn_on_reference` != `terminal_statuses`** — "implemented" is terminal (no further transitions) but healthy to reference. "rejected" is terminal AND dead.
- **Staleness is direct-only** — if SPEC-001 → ADR-0001 (superseded), only SPEC-001 is flagged. SPEC-002 → SPEC-001 is fine (SPEC-001 is approved, not dead).
- **No LLM calls** — decree is deterministic and offline. LLM tooling sits on top, consuming decree's output.

## License

MIT
