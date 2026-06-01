---
date: '2026-05-12'
governs:
- src/decree/commands/queries.py
id: SPEC-01KT22NMRXWCS5TK5VC1FT6JER
references:
- PRD-01KT22NMRS4QGHSFDBZ858PP1T
- ADR-01KT22NMRV9CP14X5982JJH161
status: implemented
---

# SPEC-01KT22NMRXWCS5TK5VC1FT6JER decree why and decree refs — Governed-File and Reverse Queries

## Overview

Implements PRD-01KT22NMRS4QGHSFDBZ858PP1T R3 — the first user-facing query layer on top of the SQLite provenance index. Two new commands:

1. **`decree why <path>`** — given a repo-relative file or directory path (optionally with `#symbol`), return the set of decisions that govern it, ranked by status priority then recency.
2. **`decree refs <id>`** — given a decision id (e.g. `SPEC-01KT22NMRWENYKC3MGRA50M7GE`), return the reverse graph: what decisions reference it, what decisions it references, what files it governs, and what commits implement it (latter is empty until SPEC-01KT22NMRY8YK9RP4323KX4RQG ships).

Both commands read from `.decree/index.sqlite` exclusively. They never re-parse frontmatter or walk markdown. If the index is missing or stale, they emit a clear error pointing at `decree index rebuild` rather than silently fanning out.

This SPEC is **read-only** — no mutation of the index, no new schema columns, no migration. The substrate already exists; this SPEC monetizes it.

## Technical Design

### Query module

A new `src/decree/commands/queries.py` houses both `why_run` and `refs_run` plus their shared helpers. Co-locating them keeps the SQL surface in one place and lets SPEC-01KT22NMRYJ4482K92AX9GJTMA (MCP server) re-export the same helpers without code duplication.

```python
# src/decree/commands/queries.py

def why(db: IndexDB, path: str, *, limit: int = 20) -> list[GoverningDecision]: ...
def refs(db: IndexDB, decision_id: str) -> RefsReport: ...

def why_run(args: argparse.Namespace) -> int: ...
def refs_run(args: argparse.Namespace) -> int: ...
```

The `why()` and `refs()` helpers are the **library API** (also called by SPEC-01KT22NMRYJ4482K92AX9GJTMA's MCP server). The `*_run` functions are the CLI handlers.

### `decree why <path>` — matching logic

Three match kinds, ranked highest to lowest:

| Kind | Example | Behavior |
|---|---|---|
| Exact path | `src/foo.py` matches `governs: src/foo.py` | Strongest signal. |
| Path prefix | `src/api/handlers.py` matches `governs: src/api/` | Directory governance covers files within. |
| Symbol strip | `src/foo.py#bar` is queried as `src/foo.py` plus the symbol stored on each match | Symbol resolution is informational; not used for ranking in v1. |

For each governing decision, we compute a `match_kind` field on the returned row. Callers (and the JSON consumer) can see exactly *why* a decision matched.

Two SQL queries cover all three cases:

```sql
-- Exact match
SELECT g.decision_id, g.path, g.symbol, d.status, d.title, d.date, d.type
FROM governs g JOIN decisions d ON d.id = g.decision_id
WHERE g.path = :path

-- Prefix match (governs entry ends with /, query path falls under it)
SELECT g.decision_id, g.path, g.symbol, d.status, d.title, d.date, d.type
FROM governs g JOIN decisions d ON d.id = g.decision_id
WHERE substr(g.path, -1) = '/'
  AND :query_path LIKE g.path || '%'
```

Results are merged, deduped by `decision_id` (with `exact` winning over `prefix` on conflict), then sorted by:
1. Status priority (per-type from `decree.toml` `statuses` order — terminal-success first; warn-on-reference last)
2. Doc date descending (newer first within the same status)

### `decree refs <id>` — fan-out

`refs(db, "SPEC-01KT22NMRWENYKC3MGRA50M7GE")` returns a `RefsReport` dataclass with five tuples:

- `forward_refs`: rows in `refs` where `from_id = "SPEC-01KT22NMRWENYKC3MGRA50M7GE"` (what SPEC-01KT22NMRWENYKC3MGRA50M7GE cites)
- `reverse_refs`: rows in `refs` where `to_id = "SPEC-01KT22NMRWENYKC3MGRA50M7GE"` (who cites SPEC-01KT22NMRWENYKC3MGRA50M7GE)
- `supersedes_chain`: transitive supersedes traversal — full chain ancestors and descendants
- `governs`: rows in `governs` for `decision_id = "SPEC-01KT22NMRWENYKC3MGRA50M7GE"`
- `commits`: rows in `commits` for `decision_id = "SPEC-01KT22NMRWENYKC3MGRA50M7GE"` (empty pre-SPEC-01KT22NMRY8YK9RP4323KX4RQG)

Plus a metadata block with the decision's status, title, date, body_hash — pulled from `decisions`.

The `supersedes_chain` traversal uses `networkx`: build a directed graph from `refs` rows of kind `supersedes` / `superseded-by`, then do a bidirectional reachability search from the queried id. This is the one place plain SQL is awkward (recursive CTEs work but networkx is more readable for a small in-memory graph).

### Index-staleness handling

Both commands call `IndexDB.status()` first. If `not status.exists`:

```
$ decree why src/foo.py
✗ index not found at .decree/index.sqlite
  Run `decree index rebuild` first.
$ echo $?
1
```

If `status.exists` but `verify()` reports drift, the commands fail closed before returning indexed results:

```
$ decree why src/foo.py
✗ index is stale (3 drift findings). Run `decree index rebuild` before querying.
$ echo $?
1
```

This is the smallest possible "stale index" surface — no auto-rebuild, no stale-result output, no silent re-parse. Predictable behavior under our hands.

### Output formats

Default (human) for `decree why`:

```
$ decree why src/decree/index_db.py
src/decree/index_db.py — 1 governing decision

  ▸ SPEC-01KT22NMRX176PCT00SKJ9G2AQ  implemented  2026-05-12  exact
    SQLite Provenance Index — Schema and Sync
```

`--json` for `decree why`:

```json
{
  "query": "src/decree/index_db.py",
  "match_count": 1,
  "matches": [
    {
      "decision_id": "SPEC-01KT22NMRX176PCT00SKJ9G2AQ",
      "type": "spec",
      "status": "implemented",
      "date": "2026-05-12",
      "title": "SQLite Provenance Index — Schema and Sync",
      "match_kind": "exact",
      "matched_path": "src/decree/index_db.py",
      "symbol": null
    }
  ]
}
```

`decree refs` similarly: a structured `RefsReport` with five sub-arrays. JSON-stable schema.

### Files touched

- **Create**: `src/decree/commands/queries.py` — `why()`, `refs()`, `why_run`, `refs_run`, dataclasses.
- **Modify**: `src/decree/cli.py` — register `decree why` and `decree refs` subcommands.
- **Modify**: `pyproject.toml` — add `networkx>=3` (the dep PRD-01KT22NMRS4QGHSFDBZ858PP1T reserved for graph traversal).
- **Create**: `tests/test_queries.py` — unit + integration coverage.

### What this SPEC does NOT do

- FTS-based concept queries (`decree why "auth"` returns docs whose title/body mention auth). FTS5 is already in the index; this SPEC doesn't surface it. Deferred to PRD-01KT22NMRSXYT95XE808VD8EV4 evaluation harness work.
- Multi-signal ranking (BM25 + dense + graph). PRD-01KT22NMRSXYT95XE808VD8EV4 territory.
- Symbol-level path resolution. The symbol part of `path#symbol` is preserved in output but not used for matching.
- Auto-rebuild on stale index. Fail closed and let the user decide when to rebuild.
- Body-link extraction (mistletoe-parsed `[text](path)` references in bodies). Deferred to SPEC-01KT22NMRYNFYM7EN80WS2HD6F.

## Testing Strategy

### Unit tests (`tests/test_queries.py`)

- **why — exact match**: fixture with `governs: ["src/foo.py"]`; query `src/foo.py` returns the doc with `match_kind="exact"`.
- **why — prefix match**: fixture with `governs: ["src/api/"]`; query `src/api/handlers.py` returns it with `match_kind="prefix"`.
- **why — no match**: query unrelated path returns empty list, exit code 0.
- **why — symbol stripped**: query `src/foo.py#bar` matches against `src/foo.py`; symbol surfaces in output.
- **why — status ordering**: two decisions govern the same file; implemented sorts before draft.
- **why — recency tiebreak**: same status, newer date first.
- **why — JSON output**: schema-stable, validates round-trip.
- **why — missing index**: returns exit 1 with a clear error pointing at `decree index rebuild`.
- **why — stale index**: returns exit 1 with a clear error pointing at `decree index rebuild`.

- **refs — forward refs**: SPEC referencing PRD and ADR returns both in forward_refs.
- **refs — reverse refs**: PRD with two referring SPECs returns both in reverse_refs.
- **refs — governs**: doc with two governs paths returns both.
- **refs — commits empty**: empty list (SPEC-01KT22NMRY8YK9RP4323KX4RQG not shipped).
- **refs — supersedes chain via networkx**: A superseded by B superseded by C; `refs A` shows the full chain.
- **refs — unknown decision**: returns exit 1, doesn't crash.
- **refs — JSON output**: schema-stable.

### Integration tests

- **End-to-end CLI**: `decree why src/decree/index_db.py` against the dogfood corpus returns SPEC-01KT22NMRX176PCT00SKJ9G2AQ with `match_kind=exact`.
- **End-to-end JSON**: stdout from `decree refs SPEC-01KT22NMRX176PCT00SKJ9G2AQ --json` parses as valid JSON with expected keys.

### Dogfood validation

- SPEC-01KT22NMRXWCS5TK5VC1FT6JER's frontmatter declares `governs: ["src/decree/commands/queries.py"]`.
- After implementation, `decree why src/decree/commands/queries.py` returns SPEC-01KT22NMRXWCS5TK5VC1FT6JER.

## v1 Acceptance Criteria

### Query module

- [x] `src/decree/commands/queries.py` exists with `why()`, `refs()`, `why_run()`, `refs_run()`.
- [x] `RefsReport` dataclass with five sub-tuples: forward_refs, reverse_refs, supersedes_chain, governs, commits.
- [x] Helpers are importable for SPEC-01KT22NMRYJ4482K92AX9GJTMA (MCP) to wrap without code duplication.

### `decree why`

- [x] Exact path match returns governing decisions.
- [x] Path-prefix match (governs entry ends with `/`) returns decisions for files within.
- [x] `path#symbol` queries strip the symbol; symbol surfaces in output.
- [x] Results sorted by status priority (per-type from decree.toml) then by date desc.
- [x] Empty result returns exit 0 (abstention is not an error condition).
- [x] `--json` produces a schema-stable structured response.
- [x] Missing index → exit 1 with a clear error message pointing at `decree index rebuild`.
- [x] Stale index → exit 1 with a clear error message pointing at `decree index rebuild`.

### `decree refs`

- [x] Returns forward_refs, reverse_refs, supersedes_chain, governs, commits for a given decision id.
- [x] Supersedes chain follows transitively (via networkx graph traversal).
- [x] `commits` list is empty pre-SPEC-01KT22NMRY8YK9RP4323KX4RQG (no error, no crash).
- [x] Unknown decision id → exit 1 with a clear error.
- [x] `--json` produces a schema-stable structured response.

### CLI

- [x] `decree why <path> [--json] [--project PATH]` registered.
- [x] `decree refs <id> [--json] [--project PATH]` registered.
- [x] Both subcommands documented in `decree --help`.

### Dependencies

- [x] `networkx>=3` added to `pyproject.toml`.
- [x] `uv tool install -e . --reinstall` confirmed to pick up the new dep.

### Tests

- [x] `tests/test_queries.py` covers all unit and integration cases listed in Testing Strategy.
- [x] All existing 279 tests continue to pass.

### Dogfood

- [x] SPEC-01KT22NMRXWCS5TK5VC1FT6JER's frontmatter declares `governs: ["src/decree/commands/queries.py"]`.
- [x] `decree why src/decree/commands/queries.py` returns SPEC-01KT22NMRXWCS5TK5VC1FT6JER as `match_kind=exact`.

## What this does NOT do (deferred)

- [ ] FTS / concept queries — PRD-01KT22NMRSXYT95XE808VD8EV4 evaluation harness.
- [ ] Multi-signal scoring — PRD-01KT22NMRSXYT95XE808VD8EV4.
- [ ] Symbol resolution / validation — v2 with tree-sitter or LSP.
- [ ] Auto-rebuild on stale index — too magical; users opt in.
- [ ] Body-link extraction — SPEC-01KT22NMRYNFYM7EN80WS2HD6F.

## References

- PRD-01KT22NMRS4QGHSFDBZ858PP1T R3 — the requirement this SPEC implements.
- ADR-01KT22NMRV9CP14X5982JJH161 — Option C hybrid: queries read from the index.
- SPEC-01KT22NMRX176PCT00SKJ9G2AQ — the index this SPEC consumes.
- SPEC-01KT22NMRXFWNE61NSETKATHBA — the typed `governs:` field this SPEC queries.
- SPEC-01KT22NMRYJ4482K92AX9GJTMA (future) — MCP server will re-export `why()` and `refs()` as MCP tools.
