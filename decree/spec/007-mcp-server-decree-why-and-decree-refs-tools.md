---
date: '2026-05-12'
governs:
- src/decree/commands/mcp_server.py
references:
- PRD-003
- ADR-0002
status: implemented
---

# SPEC-007 MCP Server — decree.why and decree.refs Tools

## Overview

Implements the first slice of PRD-003 R5 — a Model Context Protocol (MCP) server exposing decree's existing query API as task-shaped tools. v1 ships two tools (`decree.why` and `decree.refs`) that wrap the library functions already shipped in SPEC-005. The remaining R5 tools (`stale`, `health`, `intent_review`) ship alongside their underlying feature SPECs:

- `decree.stale` and `decree.health` — added when SPEC-008 ships (staleness + hotspots).
- `decree.intent_review` — added when SPEC-009 ships (intent-review + migration).

This is intentional. Each SPEC ships its CLI command **and** its MCP tool surface together. The MCP server's tool registry grows as features land, rather than ship-then-stub.

## Technical Design

### Surface

A single executable entry point exposes the MCP server over stdio (the canonical MCP transport for Claude Code / Cursor / agent runtimes):

```
decree mcp serve [--project PATH]
```

`--project` (optional) locks the server to a specific decree project root. If omitted, the server uses `cwd-walk` (the same `get_project_root()` machinery the CLI uses) at startup. The server does **not** allow runtime project switching — one server, one project, one index. Cross-project queries require running multiple servers (consumers configure them per repo).

### Library: `mcp[cli]`

PRD-003's dependency table reserved `mcp[cli]` (the official Python SDK with FastMCP merged in, MIT). This SPEC pulls it in. Tool definitions use the FastMCP decorator pattern:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("decree")

@mcp.tool()
def why(path: str) -> dict:
    """Return the decisions that govern a given file or directory path.
    
    Args:
        path: A repo-relative file or directory path. Optionally suffixed
              with `#symbol` (the symbol is preserved but not used for
              ranking in v1).
    
    Returns:
        A dict with `query`, `match_count`, and `matches` — same shape as
        `decree why <path> --json`. Empty `matches` is a valid response
        when no decision governs the path (abstention is correct behavior;
        do NOT confabulate a match).
    """
    ...
```

The LLM-facing prose (docstring) is **the product** — it's what the agent reads to decide whether/how to call the tool. Treat docstrings as part of the deliverable, not afterthought.

### Tool surface in v1

| Tool | Args | Returns | Wraps |
|---|---|---|---|
| `why` | `path: str` | dict matching CLI `--json` shape | `commands.queries.why()` |
| `refs` | `decision_id: str` | dict matching CLI `--json` shape | `commands.queries.refs()` |

Both tools reuse the helpers shipped in SPEC-005. No new query logic. The MCP server is a **thin protocol layer** over existing library functions.

### Server lifecycle

- **Startup**: resolve project root → instantiate `IndexDB` → check `status().exists`; if missing, log a one-line warning at startup and continue (tools will return errors per-call rather than refusing to start).
- **Per-call**: each tool call re-checks `status().exists`. Stale-index handling matches CLI behavior (warning surfaced in the response, not an error).
- **Shutdown**: stdio EOF or signal → close DB connection, exit 0.

### MCP tool descriptions — quality bar

Each tool's docstring follows a deliberate structure that maps to MCP's expected metadata:

1. **One-line summary** — what the tool answers, in agent-actionable terms.
2. **Args section** — each arg with its type, format, examples.
3. **Returns section** — the shape of the response, with key invariants surfaced (e.g., "empty matches = abstention, not error").
4. **When to call** — guidance on when an agent *should* invoke the tool ("call this before modifying any file you didn't author, to surface governance constraints").
5. **When not to call** — anti-patterns ("don't call this on test files or generated code; governs is for source").

This is the surface where Repowise's "tool descriptions are LLM-facing prose" insight pays off. Don't ship terse docstrings.

### `decree mcp` CLI

The server is registered as a subcommand alongside the existing ones, using a sub-namespace for future extensibility (`mcp serve` today; `mcp tools` listing could come later):

```
decree mcp serve [--project PATH]
```

Implementation: `src/decree/commands/mcp_server.py` calls `mcp.run(transport="stdio")`. Standard MCP machinery from there.

### Files touched

- **Create**: `src/decree/commands/mcp_server.py` — FastMCP setup, tool definitions wrapping `queries.why` / `queries.refs`, `mcp_serve_run` CLI handler.
- **Modify**: `src/decree/cli.py` — register `decree mcp` sub-namespace with `serve` action.
- **Modify**: `pyproject.toml` — add `mcp[cli]>=1.0`.
- **Create**: `tests/test_mcp_server.py` — direct tool-function tests + protocol-level smoke test (in-process FastMCP testing facilities, no subprocess).

### What this SPEC does NOT do

- **No `stale` / `health` MCP tools** — they don't exist as library functions yet. SPEC-008 adds them.
- **No `intent_review(diff)` MCP tool** — same, SPEC-009 adds it.
- **No HTTP / SSE transport** — stdio only in v1.
- **No authentication / authorization** — local stdio server.
- **No tool-level rate limiting / caching** — relies on SQLite query speed.
- **No subscription / notification surface** — query-only.
- **No agent-side install scripts** — document the recipe in the README, don't automate it.

## Testing Strategy

### Unit tests (`tests/test_mcp_server.py`)

- **`why` tool — exact match**: call the tool function directly with a fixture corpus, assert returns dict with `match_count=1`, `matches[0].decision_id` set.
- **`why` tool — no match**: call with unrelated path, assert `match_count=0`, empty matches (abstention).
- **`why` tool — index missing**: temporarily remove the index, assert tool returns an error response (structured), not an exception.
- **`refs` tool — known decision**: call with a known id, assert returns dict with the expected sub-arrays.
- **`refs` tool — unknown decision**: assert returns a structured error response.
- **Tool registry**: the FastMCP instance has exactly two tools registered (no stubs / placeholders for unimplemented R5 items).

### Integration test (in-process MCP protocol)

- **Protocol round-trip**: use `mcp[cli]`'s in-process client/server pair (or a minimal stdio simulation) to send `tools/list`, assert the response contains `why` and `refs` with proper descriptions and arg schemas. Send `tools/call` for `why`, assert the response matches the library output.

### Dogfood

- After SPEC-007 ships, register the decree MCP server with Claude Code. From a session, the agent should be able to call `decree.why("src/decree/index_db.py")` and get SPEC-003 back. PM does this manual smoke once.

## v1 Acceptance Criteria

### MCP server

- [ ] `src/decree/commands/mcp_server.py` exists with a `FastMCP("decree")` instance, `why` and `refs` tool functions, `mcp_serve_run` CLI handler.
- [ ] Both tools wrap the existing `commands.queries.why()` / `commands.queries.refs()` library functions — no new query logic.
- [ ] Both tool docstrings follow the 5-section structure: summary / args / returns / when to call / when not to call.
- [ ] Tool responses preserve the CLI `--json` schemas exactly (so consumers can rely on one shape).
- [ ] Server resolves project root at startup; missing index logs a warning but doesn't refuse to start.
- [ ] Each tool call re-checks index status; missing index returns a structured error response (not an exception).

### CLI

- [ ] `decree mcp serve` subcommand registered, accepts `--project PATH`.
- [ ] Subcommand documented in `decree --help`.
- [ ] Invoking `decree mcp serve` enters the FastMCP stdio loop (verifiable via a short-timeout test).

### Dependencies

- [ ] `mcp[cli]>=1.0` added to `pyproject.toml`.
- [ ] `uv tool install -e . --reinstall` confirmed to pick up the new dep.

### Tests

- [ ] `tests/test_mcp_server.py` covers all unit cases.
- [ ] At least one integration test exercises the MCP protocol end-to-end (tools/list + tools/call).
- [ ] Existing 336 tests continue to pass.

### Dogfood

- [ ] PM smoke-tested the server with Claude Code (or equivalent MCP client); note result in the SPEC-007 completion report.
- [ ] SPEC-007's frontmatter declares `governs: ["src/decree/commands/mcp_server.py"]` after the file exists.

## What this does NOT do (deferred)

- [ ] `decree.stale` / `decree.health` MCP tools — SPEC-008.
- [ ] `decree.intent_review` MCP tool — SPEC-009.
- [ ] HTTP / SSE transport.
- [ ] Tool-level auth / rate-limiting / caching.
- [ ] Subscription / notification surface.
- [ ] Runtime project switching.

## References

- PRD-003 R5 — the requirement this SPEC partially implements (v1 = 2 of 5 tools).
- ADR-0002 — Option C hybrid; the MCP server reads from the index.
- SPEC-005 — the `why()` and `refs()` library functions this SPEC wraps.
- SPEC-008 (future) — will add `stale` and `health` MCP tools.
- SPEC-009 (future) — will add `intent_review` MCP tool.
- `mcp[cli]` (official Python SDK with FastMCP) — https://github.com/modelcontextprotocol/python-sdk
