---
id: SPEC-01KW22KE3K4J7M2RJYAC110MPH
status: draft
date: 2026-06-26
references:
- PRD-01KW22JY2RQJD7B759ET0BM2NP
- ADR-01KW22K6H6FFWJFTPHNXHA1GSD
governs:
- src/decree/buckets.py
- src/decree/cli.py
- src/decree/commands/ddd.py
- src/decree/commands/new.py
- src/decree/commands/generate_html.py
- src/decree/templates/html_board.html.j2
- tests/test_cli.py
- tests/test_ddd.py
- tests/test_new.py
- tests/test_generate_html.py
- docs/index.md
- docs/usage.md
---

# SPEC-01KW22KE3K4J7M2RJYAC110MPH Required Buckets and Generate HTML PoC

## Overview

This PoC tightens document creation so every newly generated decree document
must declare a non-root bucket, then adds a read-only static HTML board export.

The generated board is an inspection surface, not a source of truth. It reads
the same documents and sprint ledger that existing CLI commands use, embeds a
stable JSON payload into one HTML file, and uses client-side JavaScript only for
switching selected sprint views.

## Technical Design

### Required Buckets

`decree new` must require `--bucket PATH`. The command should reject missing,
empty, or root bucket values before generating an ID or writing a file.

Bucket validation remains centralized in `buckets.py`. Read-only commands such
as `decree list --bucket .` may still accept the root bucket; only generation
requires a real folder path.

### HTML Board Command

Add top-level command:

```bash
decree generate-html --output decree-board.html
decree generate-html --sprint SPRINT-01KW212NVEEDAZF2343KSX6QNM --output /tmp/board.html
```

The command loads:

- all configured document types through `load_all_types()`;
- sprint ledger records when sprint mode is enabled;
- checkbox progress using the same deferred-section configuration as reports;
- bucket labels from each document path.

It writes one self-contained HTML file from a bundled template:

```text
src/decree/templates/html_board.html.j2
```

The HTML embeds a `decree.board.v1` payload with:

- generated timestamp;
- project root display path;
- selected sprint id;
- sprints with items;
- document metadata, bucket, path, references, status, and progress;
- all corpus documents for client-side filters and PRD/ADR context;
- backlog and draft-pool cards.

### Board Representation

Each sprint item maps to one card. Columns are derived from sprint membership
and progress:

- `Planning`: sprint items with `kind: planning`;
- `Todo`: execution items with no primary progress;
- `In progress`: execution items with partial primary progress;
- `Ready`: execution items with 100% primary progress but no close outcome;
- `Done`: completed outcomes;
- `Carried over`, `Deferred`, `Dropped`, and `Superseded`: closed outcomes.

The card must show document ID, type, title, bucket, status, progress, and
source/outcome details. The board must not infer references or governance from
bucket placement.

The board distinguishes sprint work from decision context. Sprint ledger items
render as kanban cards; referenced PRDs and ADRs render as related context and
support accountability checks such as no-context and root-bucket counts.

## Testing Strategy

Add focused command tests for:

- `decree new` rejects missing/root bucket values;
- `decree new` still writes into nested bucket folders;
- `generate-html` writes a single HTML file with the board payload;
- `generate-html --sprint ID` selects the requested sprint;
- unknown sprint ids fail clearly.

Run targeted tests first, then `decree lint`, `decree index verify`, and the
affected CLI tests.

## Acceptance Criteria

- [x] `decree new <type> "Title"` fails before writing and reports that
  `--bucket` is required.
- [x] `decree new <type> "Title" --bucket .` fails because generation requires
  a non-root bucket folder.
- [x] `decree new <type> "Title" --bucket feature-name` preserves existing
  bucketed write behavior and sprint destination behavior.
- [x] `decree generate-html --output FILE` writes one self-contained HTML file.
- [x] The generated HTML embeds a `decree.board.v1` payload with sprints,
  cards, buckets, document metadata, references, and progress.
- [x] The generated HTML can switch between sprint records in the browser.
- [x] `decree generate-html --sprint SPRINT-ID` selects that sprint by default
  and rejects unknown sprint IDs.
- [x] Public docs explain required buckets and the PoC status of
  `generate-html`.
- [x] The generated HTML can filter work by bucket, document type, status, and
  progress while keeping related PRD/ADR context visible.

### Deferred (post-PoC)

- [ ] Decide whether to replace the Jinja template with Astro.
- [ ] Add visual regression screenshots for the generated board.
