---
id: SPEC-01KW25D3W2KH097XXDP4EVE1X4
status: draft
date: 2026-06-26
references:
- PRD-01KW22JY2RQJD7B759ET0BM2NP
- ADR-01KW22K6H6FFWJFTPHNXHA1GSD
governs:
- src/decree/commands/generate_html.py
- src/decree/templates/html_board.html.j2
- tests/test_generate_html.py
- docs/usage.md
---

# SPEC-01KW25D3W2KH097XXDP4EVE1X4 HTML Board Markdown Overlay

## Overview

The HTML board should let users inspect the underlying decree markdown without
leaving the board. Sprint cards and related PRD/ADR context entries should open
a read-only overlay that shows document progress, references, metadata, and the
rendered markdown body.

The export must remain a single self-contained HTML file. Markdown rendering
should happen at generation time using the existing Python markdown dependency
instead of loading a browser-side CDN package.

## Technical Design

Use `mistletoe.markdown(...)` to render each document body into HTML while
building the `decree.board.v1` payload. Context7 lookup for
`/miyuchina/mistletoe` confirmed the current API supports passing markdown text
or an open file handle to `mistletoe.markdown(...)` for HTML output.

Each document record should include:

- existing metadata: id, type, title, status, bucket, path, references;
- checkbox progress;
- rendered markdown HTML;
- a compact source excerpt or body text for future search if needed.

The template should add one modal overlay with:

- document title, id, type, status, bucket, and path;
- primary/deferred progress metrics;
- references;
- rendered markdown content;
- clickable references;
- file actions for opening the document, opening the containing folder, copying
  the full path, and copying the file URL;
- a custom context menu exposing the same file actions from cards, context
  entries, and the overlay;
- close affordances via button, backdrop click, and Escape.

Cards and context documents should expose a clear "Open" action. Opening the
overlay must not mutate project state and must not require a local server.

## Testing Strategy

Add focused generator tests that assert:

- document payloads include rendered markdown HTML;
- generated HTML includes overlay controls and `openDocument` behavior;
- the export remains self-contained and still rejects unknown sprint IDs.

Run targeted tests, `decree lint`, and `decree index verify` after updating
dogfood docs.

## Acceptance Criteria

- [x] `decree generate-html` embeds rendered markdown HTML for each document.
- [x] Sprint cards can open a document overlay from the generated HTML.
- [x] Related PRD/ADR context entries can open the same overlay.
- [x] Overlay shows document metadata, references, and primary/deferred
  progress.
- [x] Overlay can be closed by close button, backdrop click, and Escape.
- [x] Generated HTML stays self-contained and does not require a server or CDN.
- [x] Tests cover rendered markdown payload and overlay template behavior.
- [x] Document payloads include absolute path, file URL, folder path, and folder
  URL for local navigation.
- [x] References in card details and overlays are clickable when the target
  document is present in the generated payload.
- [x] Cards, context entries, and the overlay expose a context menu with open
  file, open folder, copy full path, and copy file URL actions.
