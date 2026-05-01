# decree

Software decision lifecycle toolkit. Track the chain from **PRD** (what/why) through **ADR** (how) to **SPEC** (blueprint) — with cross-type references, status enforcement, and validation.

```
PRD (what/why) → ADR (how) → SPEC (blueprint) → Implementation
```

## Install

```bash
pip install decree
# or
uv tool install decree
```

## Quick Start

```bash
# Initialize decree in your project
decree init

# Create documents
decree new prd "User Authentication"
decree new adr "Auth via JWT"
decree new spec "Token Storage API"
```

```
$ decree new adr "Session Cookies Instead"
[new] type: adr, next number: ADR-0002
[new] slug: session-cookies-instead
✓ created ADR-0002
```

Add cross-references in YAML frontmatter:

```yaml
# In ADR-0001:
references: [PRD-001]

# In SPEC-001:
references: [PRD-001, ADR-0001]
```

## Features

### Lint — validate everything

Catches broken references, stale links, missing sections, and more.

```
$ decree lint
✗ 4 documents checked. 1 error.

CROSS-TYPE: SPEC-002 references PRD-999 which does not exist
```

**What it checks:**

| Rule | Example |
|------|---------|
| Dangling references | SPEC-001 references ADR-0099 which doesn't exist |
| Stale references | ADR-0001 references PRD-001 which is archived |
| Self-references | SPEC-001 references itself |
| Duplicate IDs | Two files claim ADR-0001 |
| Supersede symmetry | ADR-0001 says superseded-by ADR-0002, but ADR-0002 doesn't say supersedes ADR-0001 |
| Missing sections | SPEC-001 missing required "Testing Strategy" section |
| C4 hierarchy (opt-in) | Parent/depends-on don't resolve, duplicate C4 ids |
| Missing attachments (opt-in) | `--check-attachments` validates file paths exist on disk |

```
$ decree lint
✓ 3 documents validated. 0 errors.

$ decree lint --check-attachments
✓ 3 documents validated. 0 errors.
```

### Status — enforce lifecycle transitions

Only valid transitions are allowed. No skipping steps.

```
$ decree status PRD-001 approve
✓ PRD-001 draft → approved

$ decree status PRD-001 approve
✗ PRD-001 cannot transition from 'approved' to 'approved'.
  Valid transitions: implemented, archived.
```

Supersede links both documents automatically:

```
$ decree status ADR-0001 supersede ADR-0002
[status] transition: accepted → superseded (superseded-by ADR-0002)
[status] linking ADR-0002 → supersedes ADR-0001
✓ ADR-0001 superseded
```

### Progress — checkbox completion tracking

Scans all documents for `- [x]` / `- [ ]` checkboxes.

```
$ decree progress
✓ 9/18 items complete (50%) across 3 documents
  ADR-0001  Auth via JWT         accepted  ███████░░░  67% (2/3)
  PRD-001   User Authentication  approved  ██████░░░░  57% (4/7)
  SPEC-001  Token Storage API    draft     ████░░░░░░  38% (3/8)
```

### Index — auto-generated tables

Regenerates a markdown index per document type, sorted by status priority.

```
$ decree index
✓ index regenerated for 3 type(s)
```

Produces tables like:

```markdown
| ADR | Title | Status | Date | Supersedes |
|-----|-------|--------|------|------------|
| ADR-0002 | Session Cookies Instead | proposed | 2026-04-30 | ADR-0001 |
| ADR-0001 | Auth via JWT | superseded | 2026-04-30 |  |
```

### Graph — Mermaid diagrams

Generates decision timelines, supersede chains, status distribution pie charts, and C4 container views. Appended to each type's `index.md` below a generated marker.

```
$ decree graph
[graph] generated timeline for adr
[graph] generated supersede graph for adr
[graph] generated status distribution for adr
✓ generated diagrams for 3 type(s)
```

Example output in `index.md`:

````markdown
<!-- GENERATED:decree-graph — do not edit below this line -->

## Decision Timeline

```mermaid
timeline
    title ADR Decision Timeline
    section 2026-04-01
        ADR-0001 🔄 : Auth via JWT
    section 2026-04-02
        ADR-0002 ✅ : Session Cookies Instead
```

## Decision Chain

```mermaid
graph LR
    ADR-0001["ADR-0001<br/>Auth via JWT"]
    style ADR-0001 fill:#8b949e,color:#fff
    ADR-0002["ADR-0002<br/>Session Cookies Instead"]
    style ADR-0002 fill:#2ea043,color:#fff
    ADR-0001 -->|superseded by| ADR-0002
```

## Status Distribution

```mermaid
pie title ADR Status Distribution
    "accepted" : 1
    "superseded" : 1
```
````

### Attachments — link external artifacts

Reference design files, wireframes, or architecture diagrams in frontmatter:

```yaml
attachments:
  - .stitch/designs/overview.png
  - docs/wireframes/detail-view.png
```

Paths are relative to project root. Validated only with `--check-attachments` (won't break CI where files aren't committed).

### C4 Architecture (opt-in)

Add `[types.spec.c4]` to `decree.toml` to enable C4 validation and diagram generation on SPECs:

```yaml
# In spec frontmatter:
id: demand_model
c4_type: container
c4_name: Demand Model
c4_tech: Python / scipy
parent: system_boundary_id
depends-on: ["data_preparation"]
```

`decree lint` validates C4 hierarchy. `decree graph` generates C4Container Mermaid diagrams.

## Configuration

All config lives in `decree.toml`. Define any document type you need:

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
archive = "archived"
```

Not limited to PRD/ADR/SPEC — define any document type with its own prefix, statuses, transitions, and validation rules.

See [docs/configuration.md](docs/configuration.md) for full schema reference.

## Claude Code Integration

Decree ships as a [Claude Code](https://claude.ai/code) plugin with skills for AI-assisted document creation:

| Skill | What it does |
|-------|-------------|
| `/decree:init` | Scaffold `decree/` folder with working examples |
| `/decree:prd` | Create a PRD with section guidance and lint validation |
| `/decree:adr` | Create an ADR with reference discovery across existing docs |
| `/decree:spec` | Create a SPEC with stale-reference warnings |
| `/decree:lint` | Validate all documents, create tasks per error found |
| `/decree:ddd` | Check project state, guide next step in the PRD→ADR→SPEC flow |

## Live Example: Decree Managing Itself

Decree dogfoods its own workflow. This repo uses decree to track its own features:

```
$ decree progress
✓ 32/54 items complete (59%) across 4 documents
  ADR-0001  Coupled C4 Module vs Plugin Architecture  accepted  ░░░░░░░░░░   — 
  PRD-001   C4 Architecture Support                   approved  ░░░░░░░░░░   — 
  PRD-002   DDD CLI Command and Proofshot Integra...  approved  ░░░░░░░░░░   0% (0/17)
  SPEC-001  C4 Validation and Diagram Generation      draft     █████████░  86% (32/37)
```

Two features tracked, at different lifecycle stages:

**Feature 1: C4 Architecture Support** (86% complete)
```
PRD-001 (approved) → ADR-0001 (accepted) → SPEC-001 (draft, 86%)
```
The decision chain is complete. The PRD defined what C4 support means, the ADR chose a coupled module over a plugin architecture, and the SPEC has 32 of 37 acceptance criteria checked off.

**Feature 2: DDD CLI & Proofshot** (just approved)
```
PRD-002 (approved) → needs ADRs → needs SPECs
```
The PRD is approved with 17 acceptance criteria. Next step: create ADRs for architectural decisions (report format, hook mechanism), then SPECs for the technical blueprint.

This is what Decree Driven Development looks like — every feature has a traceable chain from business need to implementation, with checkboxes tracking progress at every level.

## Roadmap

See [docs/roadmap.md](docs/roadmap.md) for planned features and ideas — including lightweight decision logs, release notes skill, and custom templates.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, developer guidelines, and code style.

## Design Principles

- **No LLM calls** — decree is deterministic and offline. AI tooling sits on top, consuming decree's output.
- **Config-driven** — no hardcoded document types. Everything is defined in `decree.toml`.
- **`warn_on_reference` != terminal** — "implemented" is terminal (no further transitions) but healthy to reference. "rejected" is terminal AND dead.
- **Staleness is direct-only** — if SPEC-001 → ADR-0001 (superseded), only SPEC-001 is flagged. Transitive chains are not followed.

## License

MIT
