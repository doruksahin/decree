---
id: PRD-01KW22JY2RQJD7B759ET0BM2NP
status: draft
date: 2026-06-26
---

# PRD-01KW22JY2RQJD7B759ET0BM2NP HTML Board Export and Required Buckets

## Problem Statement

After foldered document buckets exist, new decision documents can still be
created in the type root when `--bucket` is omitted. That lets new work drift
back into the old flat corpus and weakens the navigation model.

Users also need a quick visual way to review current decree work without
opening multiple markdown files. `decree progress` is useful in terminals, but
team review benefits from a shareable, read-only board that shows sprint work,
document buckets, and acceptance-criteria progress in one place.

## Requirements

- New document creation must require a non-root bucket path.
- The bucket requirement must apply to every configured document type, not only
  PRDs, ADRs, and SPECs.
- Existing documents remain valid; this is an authoring rule for new documents.
- A read-only HTML board export must be available from the CLI.
- The first HTML export may be a self-contained PoC, but it must render a
  useful sprint-oriented kanban board from real decree data.
- The generated HTML must let users choose a sprint from the available sprint
  ledger records.
- The board must make document type, bucket, status, sprint outcome, and
  acceptance-criteria progress visible without implying new governance edges.

## Success Criteria

- `decree new <type> "Title"` fails until `--bucket PATH` is provided.
- `decree new <type> "Title" --bucket feature-name` writes to the expected
  bucket folder.
- `decree generate-html --output FILE` creates a single local HTML file.
- The generated file can be opened directly in a browser without a server.
- The generated board can switch between sprints and show cards in kanban
  columns based on sprint item state and document progress.

## Scope

In scope for the PoC:

- Required non-root buckets for new document generation.
- A self-contained HTML template bundled with decree.
- A `generate-html` CLI command that writes one HTML file.
- Sprint selection and kanban-style document cards.

Out of scope for this slice:

- Publishing a new package release.
- Astro build integration.
- Interactive mutation from the generated board.
- Moving existing documents into buckets.
