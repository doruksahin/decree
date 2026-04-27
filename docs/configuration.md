# Configuration

All configuration lives in `decree.toml` at the project root.

## File Location and Format

Decree looks for `decree.toml` by walking up from the current working directory. The file uses TOML format and defines one or more document types under `[types.<name>]` sections.

## Document Type Sections

Each `[types.<name>]` section defines a document type. You can define as many types as you need (e.g., `adr`, `prd`, `spec`).

### Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `dir` | string | no | `"docs/<name>"` | Directory where documents of this type live (relative to project root) |
| `prefix` | string | **yes** | — | ID prefix used in filenames and references (e.g., `"ADR"`, `"PRD"`) |
| `digits` | integer | no | `4` | Number of zero-padded digits in document IDs (e.g., `4` → `ADR-0001`) |
| `initial_status` | string | no | first entry in `statuses` | Status assigned to newly created documents |
| `statuses` | list of strings | **yes** | — | All valid statuses for this document type |
| `warn_on_reference` | list of strings | no | `[]` | Statuses that trigger a lint warning when referenced by other documents |
| `required_sections` | list of strings | no | `[]` | Markdown H2 sections that must be present in every document of this type |
| `template` | string | no | bundled default | Path to a custom template file (relative to project root) |

### Transitions

`[types.<name>.transitions]` defines which status transitions are allowed. Each key is a source status, and its value is a list of valid target statuses. Statuses not listed as keys are treated as terminal (no transitions out).

### Actions

`[types.<name>.actions]` defines named shortcuts for status transitions. Each key is an action name (used as a CLI verb), and its value is the target status.

For example, `accept = "accepted"` allows `decree status accept ADR-0004` instead of specifying the target status directly.

### Status Field Requirements

`[types.<name>.status_field_requirements]` defines frontmatter fields that must be present when a document is in a given status. For example, requiring a `superseded-by` field when status is `superseded`.

### Section Descriptions

`[types.<name>.section_descriptions]` provides LLM-facing guidance text for required sections. Used by `decree new` to populate section descriptions in generated documents.

## C4 Model Diagrams (Optional)

`[types.<name>.c4]` enables C4 model diagram generation for a document type.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `false` | Whether C4 diagrams are enabled |
| `id_field` | string | `"id"` | Frontmatter field used as the C4 element identifier |
| `levels` | list of strings | `["system", "container", "component"]` | C4 abstraction levels to generate |

## Example Configuration

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
submit = "review"
approve = "approved"
implement = "implemented"
archive = "archived"

[types.adr]
dir = "decree/adr"
prefix = "ADR"
digits = 4
initial_status = "proposed"
statuses = ["proposed", "accepted", "rejected", "deprecated", "superseded"]
warn_on_reference = ["rejected", "deprecated", "superseded"]
required_sections = ["Context and Problem Statement", "Considered Options", "Decision Outcome"]

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
statuses = ["draft", "review", "approved", "implemented"]
required_sections = ["Overview", "Technical Design", "Testing Strategy"]

[types.spec.transitions]
draft = ["review"]
review = ["approved", "draft"]
approved = ["implemented"]
implemented = []

[types.spec.actions]
submit = "review"
approve = "approved"
implement = "implemented"
```
