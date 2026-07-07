---
date: '2026-07-07'
governs:
- src/decree/config.py
- src/decree/commands/intent_check.py
id: SPEC-01KWXPAP3ENJ9BF7MADKHHCF6H
references:
- PRD-01KWXMRR7R3S5CSAAZRGFHR5QN
- ADR-01KWXMRRB44CE78H0659D9WDY7
status: implemented
---

# SPEC-01KWXPAP3ENJ9BF7MADKHHCF6H Typed intent-check findings and planned-file classification

## Overview

Implements the in-scope slice of PRD-01KWXMRR7R3S5CSAAZRGFHR5QN (backlog items
`B7`, `B6`, `B3`, `B4`, `B5` in
[docs/dogfooding-feedback/06-research-backlog.md](../../../docs/dogfooding-feedback/06-research-backlog.md))
under the additive-and-exit-stable decision of ADR-01KWXMRRB44CE78H0659D9WDY7.

`intent-check` now tells an agent what *kind* of finding each result is, so a
contextual overlap or a decree-document self-edit is no longer indistinguishable
from a real blocker in one flat exit-1 bucket.

## Technical Design

- **`config.classify_path(rel_path, doc_type_dirs=None) -> "source"|"corpus"|"generated"`**
  (`B7`) — path-only and deterministic. `corpus` = a file under a configured
  document type's `dir`; `generated` = `index.md` or a `reports/` entry under a
  document dir; `source` = everything else.
- **Planned-file partition** (`B6`) — `intent_check()` classifies every planned
  file into `source_changes` / `corpus_changes` / `generated_artifact_changes`
  and excludes corpus/generated paths from the `add_governance` recommendation,
  so editing a decree document no longer looks ungoverned (Agentkith Case 5).
- **Finding classes** (`B3`) — `_bucket_findings()` derives additive
  `blocking_findings` (the exit-1 drivers: conflicts, stale governance, live
  overlap), `advisory_findings`, and `corpus_hygiene_findings` from the existing
  recommendations plus the planned-file classification. Surfaced in `--json` and,
  via the shared serializer, the MCP `intent_check` tool.
- **Human output** (`B4`) — `_format_human` leads with a "Block now" / "Clean
  later" summary and a single recommended next command.
- **Exit contract** (`B5`) — the `has_blockers` gate is unchanged; the new
  classes never change the exit code. A regression test pins that a stale-only
  corpus still exits 1.

## Testing Strategy

- `tests/test_classify_path.py` — the classifier across source/corpus/generated,
  normalization, and determinism without a working tree.
- `tests/test_intent_check.py` — `TestPlannedFileClassification`,
  `TestFindingClassBuckets`, `TestHumanBlockCleanOutput`, and
  `TestExitCodeContract` (advisory/corpus stay exit 0; conflict and stale-only
  stay exit 1); the two `--json`/MCP shape assertions updated for the additive
  keys.

## Acceptance Criteria

- [x] `classify_path` returns `source`/`corpus`/`generated` from the path alone
- [x] corpus and generated planned files are excluded from `add_governance`
- [x] `source_changes`/`corpus_changes`/`generated_artifact_changes` appear in `--json` and MCP
- [x] `blocking_findings`/`advisory_findings`/`corpus_hygiene_findings` are additive JSON keys
- [x] human output leads with "Block now" / "Clean later" and a recommended next command
- [x] exit codes are unchanged: advisory/corpus-only exits 0, stale-only exits 1
- [x] the new JSON keys are documented in json-contracts.md, usage.md, and the MCP docstring
