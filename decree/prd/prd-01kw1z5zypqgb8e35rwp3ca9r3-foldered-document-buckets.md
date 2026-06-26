---
id: PRD-01KW1Z5ZYPQGB8E35RWP3CA9R3
status: draft
date: 2026-06-26
---

# PRD-01KW1Z5ZYPQGB8E35RWP3CA9R3 Foldered Document Buckets

## Problem Statement

As a decree corpus grows, PRDs, ADRs, and SPECs become hard to scan when every
document lives in one flat type directory. Related work is currently expressed
through `references:`, `supersedes:`, and status, but those fields describe
decision relationships, not navigation structure.

Developers and agents need a low-friction way to browse decisions by product
area, concern, or feature without changing the identity model or implying false
governance relationships.

## Requirements

- Support optional nested folders under configured document type directories,
  such as `decree/prd/sprint/` or `decree/spec/provenance/`.
- Treat folder placement as an organization bucket only; it must not imply
  `references:`, `supersedes:`, ownership, sprint membership, or status.
- Keep canonical document identity global and ID-based. Moving a document
  between buckets must not change its `TYPE-ULID`.
- Read, lint, index, and progress over nested documents wherever the current
  flat-directory behavior reads documents today.
- Add CLI affordances for creating documents inside a bucket and listing the
  corpus as a tree grouped by bucket.
- Keep existing flat corpora valid with no migration required.
- Exclude generated indexes, completion reports, and other derived artifacts
  from recursive document loading.
- Make bucket names deterministic, repo-relative, and safe for git paths.

## Success Criteria

- A project with only flat `decree/prd/*.md`, `decree/adr/*.md`, and
  `decree/spec/*.md` continues to lint and list exactly as before.
- A project with nested files such as `decree/prd/sprint/prd-...md` loads those
  documents in `decree lint`, `decree progress --corpus`, index rebuild/verify,
  and MCP progress.
- `decree new prd "Title" --bucket sprint` writes to
  `decree/prd/sprint/prd-...-title.md` and refuses unsafe bucket paths.
- `decree list --tree` shows documents grouped by bucket and type so users can
  scan related work without opening every file.
- References remain ID-based across buckets and continue to pass lint when a
  referenced document is moved.
- Generated `index.md` and `reports/` files are not parsed as source documents.

## Scope

In scope: nested bucket discovery, safe bucket path validation, new-document
bucket placement, tree/list output, docs, tests, and backward compatibility.

Out of scope for the first release: automatic bucket inference, moving existing
documents, bucket-specific permissions, UI dashboards, and treating buckets as
governance or sprint scopes.
