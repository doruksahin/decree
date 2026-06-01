---
date: 2026-05-12
governs:
- src/decree/llm_io.py
id: SPEC-01KT22NMS0BN1F5B01HEFK87W0
references:
- PRD-01KT22NMRTAF9581AXC53EHQTW
status: draft
---

# SPEC-01KT22NMS0BN1F5B01HEFK87W0 Claude Code CLI LLM Provider — Subprocess-based Routing

## Overview

Adds a `claude-code/...` model family to decree's LLM routing layer that shells out to the local `claude` CLI (Claude Code) via `subprocess`. Users with an existing Claude Code subscription incur **zero marginal cost** for `decree migrate governs --suggest` and `decree intent-check --judge-conflicts` (versus per-token Anthropic API charges).

This SPEC is a prerequisite for PRD-01KT22NMRTAF9581AXC53EHQTW R1/R2 — the validation work needs to make real LLM calls against jira-task-to-md's 167-doc corpus and the eval query set, and the agent environment has no working `ANTHROPIC_API_KEY`. With the Claude Code CLI provider, PRD-01KT22NMRTAF9581AXC53EHQTW ships without API-key dependencies.

The implementation is informed by **Nimbalyst's** production-grade Claude Code integration (TypeScript / Electron). Nimbalyst's `ClaudeCodeProvider.ts` uses `@anthropic-ai/claude-agent-sdk` (no Python equivalent), but their hardening posture and their flag choices translate directly. Specifically:

- `CLAUDE_CODE_ENTRYPOINT=cli` env override (better rate-limit lane than `sdk-ts`)
- `--strict-mcp-config` (no user MCP injection)
- `--permission-mode plan` (no filesystem writes)
- `--max-turns 1` (kills the agent loop for fire-and-forget batch usage)
- Env scrubbing of `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` (Nimbalyst's defense against SDK 0.2.111's silent overlay-vs-replace bug)
- Stderr-tail-buffer pattern for diagnostics
- `shutil.which("claude")` with explicit override hook

Drop everything Nimbalyst does for interactive multi-turn (session resume, tool hooks, MCP servers, plugins, plan mode). Decree's use case is fire-and-forget batch prompts.

## Technical Design

### Library: `decree/llm_io.py` extension

Add `complete_via_claude_code()` alongside the existing `parse_llm_json()`:

```python
import os, shutil, subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class ClaudeCodeError(RuntimeError):
    def __init__(self, returncode: int, stderr_tail: str) -> None:
        self.returncode = returncode
        self.stderr_tail = stderr_tail
        super().__init__(f"claude exit {returncode}: {stderr_tail}")


def complete_via_claude_code(
    prompt: str,
    *,
    model: str = "sonnet",                  # short alias: opus / sonnet / haiku / opus-4-7
    cwd: Optional[Path] = None,
    allowed_tools: Optional[list[str]] = None,  # None → no tools allowed
    max_turns: int = 1,                     # single-shot
    timeout_s: int = 120,
    extra_env: Optional[dict[str, str]] = None,
) -> str:
    """Send a single prompt through the local `claude` CLI and return text result.
    
    Uses Claude Code's existing subscription auth — no ANTHROPIC_API_KEY needed.
    Fire-and-forget single-turn. For agent-loop / streaming use cases, use a
    different surface.
    """
    bin_path = shutil.which("claude")
    if not bin_path:
        raise ClaudeCodeError(
            -1,
            "`claude` not found on PATH. Install Claude Code or pass --model anthropic/...",
        )
    
    args = [
        bin_path, "-p", prompt,
        "--model", model,
        "--output-format", "json",
        "--max-turns", str(max_turns),
        "--permission-mode", "plan",        # no filesystem writes
        "--strict-mcp-config",              # ignore user MCP servers
    ]
    if allowed_tools is not None:
        args += ["--allowedTools", ",".join(allowed_tools) if allowed_tools else "none"]
    
    # Env: keep PATH, HOME, USERPROFILE; scrub API keys; add Nimbalyst rate-lane hint.
    env = {k: v for k, v in os.environ.items()
           if k in {"PATH", "HOME", "USERPROFILE", "TERM", "LANG", "LC_ALL"}}
    env["CLAUDE_CODE_ENTRYPOINT"] = "cli"
    if extra_env:
        env.update(extra_env)
    
    proc = subprocess.run(
        args, capture_output=True, text=True,
        cwd=str(cwd) if cwd else None, env=env,
        timeout=timeout_s, check=False,
    )
    if proc.returncode != 0:
        stderr_tail = "\n".join(proc.stderr.splitlines()[-20:])
        raise ClaudeCodeError(proc.returncode, stderr_tail)
    
    payload = parse_llm_json(proc.stdout)
    # `claude -p --output-format json` returns:
    #   {"type":"result","result":"...","total_cost_usd":..., "duration_ms":...}
    if not isinstance(payload, dict) or "result" not in payload:
        raise ClaudeCodeError(0, f"unexpected payload shape: {list(payload.keys())[:5]}")
    return payload["result"]
```

### Unified entry point + routing

```python
# decree/llm_io.py — alongside complete_via_claude_code

def complete(prompt: str, model: str, **kw) -> str:
    """Unified entry point. Routes to claude-code or litellm based on model prefix."""
    if model.startswith("claude-code/"):
        return complete_via_claude_code(
            prompt,
            model=model.split("/", 1)[1],
            timeout_s=kw.get("timeout", 120),
        )
    import litellm
    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=kw.get("temperature", 0.0),
        response_format={"type": "json_object"},
        timeout=kw.get("timeout", 60),
    )
    return response.choices[0].message.content
```

### Model-resolution chain

Update `resolve_model(args) -> str` in `commands/migrate.py` (and replicate or extract for `commands/intent_check.py`):

1. `args.model` set → use that. (May be `claude-code/sonnet`, `claude-3-5-sonnet-latest`, etc.)
2. `DECREE_LLM_MODEL` env → use that.
3. **`claude` binary on PATH** → `claude-code/sonnet`. **New default** when no explicit configuration.
4. `ANTHROPIC_API_KEY` env → `claude-3-5-sonnet-latest`.
5. `OPENAI_API_KEY` env → `gpt-4o-mini`.
6. Else exit 2 with help text describing the three install options.

The Claude Code CLI rejects unknown model aliases at startup, so `claude-code/<anything>` is forwarded as-is.

### Consumer wiring

Both `commands/migrate.py::suggest_governs` and `commands/intent_check.py::_judge_conflict` already build a prompt and call `litellm.completion()`. Both are replaced with a single call to `complete(prompt, model)`. The routing is internal to `llm_io.py`; consumers don't branch on model type.

This is a small refactor — ~5 lines changed per consumer, no behavioral change for litellm-routed models.

### Files touched

- **Modify**: `src/decree/llm_io.py` — add `complete_via_claude_code()`, `complete()`, `ClaudeCodeError`.
- **Modify**: `src/decree/commands/migrate.py` — `resolve_model()` extended; `suggest_governs` calls `complete()`.
- **Modify**: `src/decree/commands/intent_check.py` — `_judge_conflict` calls `complete()`. Extract `resolve_model` to `llm_io.py` if cleaner.
- **Create**: `tests/test_llm_io.py` — unit tests for new helpers (mock subprocess + mock litellm).
- **Modify**: `tests/test_migrate_governs.py`, `tests/test_intent_check.py` — extend with claude-code-routed paths (mocked).

### What this SPEC does NOT do

- **No agent loop / multi-turn** — `--max-turns 1`. Tool use is gated off (`--allowedTools "none"` by default).
- **No streaming** — uses `--output-format json` (single payload), not `--output-format stream-json`.
- **No session resume** — single-shot calls, no state.
- **No MCP server passthrough** — `--strict-mcp-config` blocks user MCP injection.
- **No cost tracking surface** — the `total_cost_usd` field from `claude -p --output-format json` is technically zero (subscription auth); out of scope.
- **No `claude-agent-sdk` Python port** — there isn't one in 2026; we route via the CLI binary which is the supported public surface.
- **No support for non-Claude models through this provider** — the `claude-code/` namespace is Anthropic-only.

## Testing Strategy

### Unit tests (`tests/test_llm_io.py`)

- **Happy path**: mock `subprocess.run` returning JSON `{"type":"result","result":"hello",...}`, assert returned string `== "hello"`.
- **Missing binary**: patch `shutil.which` → None; assert `ClaudeCodeError(-1, ...)` raised.
- **Non-zero exit**: mock `returncode=1`, stderr with multi-line text; assert `ClaudeCodeError` with last 20 lines in `stderr_tail`.
- **Malformed JSON**: mock stdout = `"not json"`; assert `json.JSONDecodeError` (or wrapped) propagates.
- **Missing `result` key**: mock returns `{"foo":"bar"}`; assert `ClaudeCodeError` raised with shape hint.
- **Timeout**: mock `subprocess.run` raises `subprocess.TimeoutExpired`; assert propagates.
- **Env scrubbing**: set `ANTHROPIC_API_KEY` + `OPENAI_API_KEY` in `os.environ` via monkeypatch; capture the `env` kwarg passed to `subprocess.run`; assert neither key is in it.
- **`CLAUDE_CODE_ENTRYPOINT=cli`**: assert that exact env var is set.
- **`--strict-mcp-config` flag**: assert in args list.
- **`--permission-mode plan` flag**: assert in args list.
- **`--allowedTools "none"` default**: when `allowed_tools=None`, assert `--allowedTools none` is in args.
- **`complete()` routing — claude-code/**: model `claude-code/sonnet` → calls `complete_via_claude_code` with `model="sonnet"`.
- **`complete()` routing — litellm**: model `gpt-4o-mini` → calls `litellm.completion`; mock both, assert correct branch.

### Integration / regression

- **`tests/test_migrate_governs.py`**: add 2 cases mocking `subprocess.run` for the claude-code path. End-to-end suggest flow via claude-code routing.
- **`tests/test_intent_check.py`**: add 2 cases mocking subprocess for `--judge-conflicts` via claude-code.
- **Model resolution permutations** in a new test class: env-var combos via `monkeypatch.setenv`/`delenv` + mock `shutil.which`.

### Dogfood

- Run `decree migrate governs --suggest --only SPEC-01KT22NMRWENYKC3MGRA50M7GE` against the decree corpus on a machine with `claude` on PATH and no `ANTHROPIC_API_KEY`. Capture the actual LLM-generated governs proposal in the SPEC-01KT22NMS0BN1F5B01HEFK87W0 completion report.
- Run `decree intent-check --plan "Add stale-PR-detector subcommand" --files src/decree/commands/health.py --judge-conflicts` with no API key. Capture output. (Should run cleanly even if no conflicts found, because the path requires zero LLM calls in the no-conflict case — but the routing is exercised.)

## v1 Acceptance Criteria

### Library

- [ ] `src/decree/llm_io.py` gains `complete_via_claude_code()`, `complete()`, `ClaudeCodeError`.
- [ ] Env scrubbing: `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` removed from the subprocess env.
- [ ] `CLAUDE_CODE_ENTRYPOINT=cli` always set in the subprocess env.
- [ ] Default flags: `--output-format json`, `--max-turns 1`, `--permission-mode plan`, `--strict-mcp-config`.
- [ ] `--allowedTools "none"` set when `allowed_tools=None` (default).
- [ ] Binary resolution: `shutil.which("claude")` with clear `ClaudeCodeError(-1, ...)` if not found.
- [ ] Stderr tail (last 20 lines) included in error on non-zero exit.

### Model resolution

- [ ] `resolve_model()` chain implemented (6 steps).
- [ ] Default behavior when no flags/env: `claude` on PATH → `claude-code/sonnet`.
- [ ] `--model claude-code/opus`, `claude-code/haiku`, `claude-code/opus-4-7` route correctly.
- [ ] `DECREE_LLM_MODEL` honored, `--model` flag overrides env.
- [ ] Exit 2 with helpful message when no LLM provider available.

### Consumers wired

- [ ] `commands/migrate.py::suggest_governs` calls `complete(prompt, model)` (no direct `litellm.completion`).
- [ ] `commands/intent_check.py::_judge_conflict` calls `complete(prompt, model)`.

### Tests

- [ ] `tests/test_llm_io.py` covers all 13 unit cases above.
- [ ] `tests/test_migrate_governs.py` extended with 2 claude-code-routed cases (mocked subprocess).
- [ ] `tests/test_intent_check.py` extended with 2 claude-code-routed cases.
- [ ] Model-resolution permutation tests cover the 6-step chain.
- [ ] No live LLM calls in CI. Full suite passes.

### Dogfood

- [ ] Live `decree migrate governs --suggest --only SPEC-01KT22NMRWENYKC3MGRA50M7GE` against decree corpus succeeds **with `ANTHROPIC_API_KEY` unset** and `claude` on PATH. Output recorded.
- [ ] SPEC-01KT22NMS0BN1F5B01HEFK87W0 frontmatter `governs:` declares `["src/decree/llm_io.py"]` after implementation.

## What this does NOT do (deferred)

- [ ] Streaming output via `--output-format stream-json`.
- [ ] Multi-turn agent loops.
- [ ] Tool use / MCP passthrough through Claude Code.
- [ ] Cost tracking surface (`total_cost_usd` from JSON output).
- [ ] Python port of `claude-agent-sdk` — doesn't exist, we don't write it.
- [ ] Session resume.
- [ ] Plan-mode integration.
- [ ] Bedrock / Vertex AI passthrough (`claude` CLI supports these via env vars; decree doesn't surface).

## References

- PRD-01KT22NMRTAF9581AXC53EHQTW — this SPEC unblocks R1/R2 by removing the API-key dependency.
- SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S, SPEC-01KT22NMS0KTWGNKB36RR7K0JR — current `litellm.completion` consumers extended here.
- Nimbalyst `ClaudeCodeProvider.ts` (https://github.com/nimbalyst/nimbalyst) — pattern + hardening reference (`@anthropic-ai/claude-agent-sdk` TS path; we translate to Python subprocess).
- `claude -p` documentation — Claude Code's non-interactive print mode.
- The conversation context's "no brittle code, leverage OSS" directive — Claude CLI is the "existing tool" we lean on rather than re-implementing.
