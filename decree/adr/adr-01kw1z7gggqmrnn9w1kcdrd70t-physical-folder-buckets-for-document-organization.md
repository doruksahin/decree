---
id: ADR-01KW1Z7GGGQMRNN9W1KCDRD70T
status: proposed
date: 2026-06-26
references:
- PRD-01KW1Z5ZYPQGB8E35RWP3CA9R3
---

# ADR-01KW1Z7GGGQMRNN9W1KCDRD70T Physical Folder Buckets for Document Organization

## Context and Problem Statement

Decree needs a way to group related PRDs, ADRs, and SPECs by concern or feature
without overloading decision relationships. The grouping should help humans and
agents navigate a large corpus, while `references:`, `supersedes:`, and
`governs:` continue to carry decision semantics.

The design choice is where the bucket source of truth should live: in physical
folders, in frontmatter metadata, or in an external manifest.

## Decision Drivers

- Buckets must be visible in normal file trees and git diffs.
- Existing flat corpora must remain valid.
- Moving a document between buckets must not change its ID or references.
- The design must avoid metadata drift between file path and frontmatter.
- Query commands must not infer governance or lifecycle relationships from a
  bucket.
- Implementation should fit the current parser and CLI model without adding a
  separate database requirement.

## Considered Options

- Physical folder buckets: the bucket is the relative directory below the
  configured type directory, for example `decree/prd/sprint/`.
- Frontmatter bucket field: each document declares `bucket: sprint` while files
  may remain flat.
- External bucket manifest: a separate structured file maps document IDs to
  buckets.
- Status quo: keep all type directories flat and rely on references/search.

## Decision Outcome

Chosen option: physical folder buckets.

Physical folders make the organization visible to every editor, shell command,
code review, and git diff. They avoid the main drift risk of a frontmatter
field, where `bucket: sprint` could disagree with a file living under
`decree/prd/provenance/`. They also avoid a separate manifest that must be kept
in sync with document moves.

The bucket is intentionally non-semantic. It is a navigation lens only. Decree
must continue to resolve documents by global `TYPE-ULID`, validate references by
ID, and treat governance/sprint/lifecycle relationships as explicit structured
fields rather than path-derived facts.

Flat documents remain valid: the root of each type directory is the default
bucket.
