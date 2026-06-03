---
date: '2026-06-03'
governs:
- src/decree/commands/commit_check.py
- src/decree/commands/mcp_server.py
id: SPEC-01KT7E7SQ7QVXZYK2Q0Y37QD3J
references:
- ADR-01KT7E7RD6NYASNDWVE0PQ7J8G
status: implemented
---

# SPEC-01KT7E7SQ7QVXZYK2Q0Y37QD3J Trailer-coverage gate via decree commit-check

## Overview

`decree commit-check` reports — and can gate CI on — the **trailer coverage** of a
change: of the files a diff touches that are governed by an *in-flight* decision, how
many carry a matching `Implements:/Refs:/Fixes:` trailer linking the commit to that
decision. It is a deterministic, read-only sibling of `intent-check`/`intent-review`
(same 0/1/2 exit-code contract, `--json`, MCP tool), advisory by default with opt-in
`--strict`/`--min-coverage`. It implements [ADR-01KT7E7RD6NYASNDWVE0PQ7J8G](../adr/adr-01kt7e7rd6nyasndwve0pq7j8g-commit-check-as-a-ci-coverage-gate-not-a-commit-msg.md).
Full plan: `docs/plans/2026-06-03-commit-check.md`.

## Technical Design

- **Inputs / modes:** `--diff-base REF` (CI, primary; paths from `git diff REF...HEAD`,
  trailers from the union across commits in `REF..HEAD` — squash-safe), `--diff PATH`/`-`,
  `--message FILE` (candidate-message mode for an opt-in local hook; trailers from the
  message). Paths via the reused `intent_review._read_diff_source`/`parse_diff`.
- **Governed changes:** for each path, `queries.why()` (authoritative declared `governs:`),
  keep decisions with `_status_priority(type,status) == 1` (in-flight; mirrors
  `commit.infer_active_spec`). Never reads `observed_governs`/`commits`-as-truth; never an LLM.
- **Trailers:** parsed via the canonical `git interpret-trailers --parse` (same parser as
  `index_db.sync_commits_from_git`); `Implements:`/`Refs:`/`Fixes:` all satisfy.
- **Coverage:** `(covered, total, fraction)` over `(path, in-flight decision)` pairs;
  zero governed pairs is vacuously covered (exit 0).
- **Exit codes:** 0 clean or advisory-only; 1 a finding under `--strict`/`--min-coverage`;
  2 config error. `--json` is a stable contract; the MCP `commit_check` tool returns the
  same payload through the same formatter.
- **Honesty:** framed as "coverage you can gate," never a guarantee (bypassable). Tickets
  are orthogonal — never read or mapped.
- **Deferred (out of scope):** core git-hook installer (documented opt-in snippet only),
  `health`/`ddd` coverage surfacing, ticket mapping, LLM inference, auto-writing trailers.

## Testing Strategy

`tests/test_commit_check.py` (reusing the `git_project` fixture) covers the 15-case matrix
in the plan: matching trailer → 0; no trailer advisory → 0, `--strict` → 1; `--min-coverage`
thresholds; `Refs:`/`Fixes:` satisfy; wrong/multi-value trailers; ungoverned-only → 0;
terminal-SPEC excluded; squash range-union (`--diff-base`); multi-decision file; prefix
governance; missing-input/missing-index → 2; `--json` shape; MCP payload parity; a
500-path scalability check.

## Acceptance Criteria

- [x] `governed_changes(db, paths)` returns in-flight declared `(path, decision)` pairs only
- [x] `trailer_ids(message)` parses Implements/Refs/Fixes via `git interpret-trailers`
- [x] `range_trailer_ids(repo, ref)` unions trailers across `REF..HEAD` (squash-safe)
- [x] `coverage(governed, trailers)` returns the covered/total/fraction scalar
- [x] `decree commit-check` CLI registered; input-mode resolution + flags (`--diff-base`, `--diff`, `--message`, `--strict`, `--min-coverage`, `--json`, `--project`)
- [x] Human report output + exit-code contract (0/1/2) per the test matrix
- [x] `--json` stable contract
- [x] MCP `commit_check` tool returns the identical payload
- [x] Docs: provenance-model honesty framing + llm-agent-integration loop/MCP list + usage/README CI recipe + orthogonality note
- [x] Towncrier `feature` fragment
- [x] All gates green: pytest, ruff, decree lint, decree index verify, lychee
