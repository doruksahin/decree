"""Shared helpers for LLM I/O across decree commands.

This module exists to eliminate duplication between SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S (`commands.migrate`)
and SPEC-01KT22NMS0KTWGNKB36RR7K0JR (`commands.intent_check`) — both of which call `litellm.completion`
with `response_format={"type": "json_object"}` and need fence-tolerant JSON
parsing on the response.

SPEC-01KT22NMS0BN1F5B01HEFK87W0 adds:

* `complete_via_claude_code()` — route a single-shot prompt through the local
  ``claude`` CLI (Claude Code) via subprocess so users with an existing
  Claude Code subscription incur zero marginal cost.
* `complete()` — unified entry point that routes to claude-code or litellm
  based on the ``model`` prefix (``claude-code/...`` → CLI, else → litellm).
* `resolve_model()` — six-step model-resolution chain extracted here so both
  ``commands.migrate`` and ``commands.intent_check`` reuse it.

Future LLM-using commands (e.g., research-frontier C.3 ADR refinement) should
import from here rather than re-implement.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# JSON parsing (SPEC-01KT22NMRZZ0ZZ0DQ4N0SJPN9S)
# ---------------------------------------------------------------------------


def parse_llm_json(content: str) -> dict:
    """Parse an LLM response body as JSON, tolerating markdown code-fence wrapping.

    litellm with `response_format={"type": "json_object"}` returns the JSON
    payload as a string in `choices[0].message.content`. Some providers
    (notably Anthropic) wrap the response in ```/```json fences even when
    asked for `json_object` — strip a single leading/trailing fence pair if
    present, then `json.loads`.

    Raises `json.JSONDecodeError` if the (potentially de-fenced) content isn't
    valid JSON. Callers are expected to handle that exception per their own
    error-isolation policy.
    """
    text = content.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


# ---------------------------------------------------------------------------
# Claude Code CLI subprocess provider (SPEC-01KT22NMS0BN1F5B01HEFK87W0)
# ---------------------------------------------------------------------------


class ClaudeCodeError(RuntimeError):
    """Raised when the ``claude`` CLI subprocess fails or returns garbage.

    ``returncode`` is the process exit code (``-1`` for "binary missing" or
    "payload shape unexpected"). ``stderr_tail`` is the last 20 lines of
    stderr from the subprocess (or a one-line diagnostic when there is no
    subprocess output).
    """

    def __init__(self, returncode: int, stderr_tail: str) -> None:
        self.returncode = returncode
        self.stderr_tail = stderr_tail
        super().__init__(f"claude exit {returncode}: {stderr_tail}")


# Env vars to preserve when invoking the subprocess. We explicitly DO NOT
# forward ANTHROPIC_API_KEY / OPENAI_API_KEY — Claude Code uses its own
# subscription auth, and forwarding API keys risks the SDK 0.2.111 silent
# overlay-vs-replace bug (see Nimbalyst ClaudeCodeProvider.ts).
_PASSTHROUGH_ENV_VARS = frozenset({"PATH", "HOME", "USERPROFILE", "TERM", "LANG", "LC_ALL"})


def complete_via_claude_code(
    prompt: str,
    *,
    model: str = "sonnet",
    cwd: Path | None = None,
    allowed_tools: list[str] | None = None,
    max_turns: int = 1,
    timeout_s: int = 120,
    extra_env: dict[str, str] | None = None,
) -> str:
    """Send a single prompt through the local ``claude`` CLI and return the text result.

    Uses Claude Code's existing subscription auth — no ``ANTHROPIC_API_KEY``
    needed. Fire-and-forget single-turn. For agent-loop / streaming use cases,
    use a different surface.

    Flags applied (informed by Nimbalyst's ``ClaudeCodeProvider.ts``):
      * ``--output-format json`` (single payload, parseable)
      * ``--max-turns 1`` (kills the agent loop for batch usage)
      * ``--permission-mode plan`` (no filesystem writes)
      * ``--strict-mcp-config`` (ignore user MCP servers)
      * ``--allowedTools "none"`` when ``allowed_tools`` is None / empty
      * ``CLAUDE_CODE_ENTRYPOINT=cli`` env (better rate-limit lane)
    """
    bin_path = shutil.which("claude")
    if not bin_path:
        raise ClaudeCodeError(
            -1,
            "`claude` not found on PATH. Install Claude Code or pass --model anthropic/... / openai/...",
        )

    args: list[str] = [
        bin_path,
        "-p",
        prompt,
        "--model",
        model,
        "--output-format",
        "json",
        "--max-turns",
        str(max_turns),
        "--permission-mode",
        "plan",
        "--strict-mcp-config",
    ]
    if allowed_tools is not None:
        # Empty list also produces "none" — explicit per SPEC-01KT22NMS0BN1F5B01HEFK87W0.
        joined = ",".join(allowed_tools) if allowed_tools else "none"
        args += ["--allowedTools", joined]
    else:
        args += ["--allowedTools", "none"]

    # Build the subprocess env from scratch. Only pass through a whitelist;
    # in particular, ANTHROPIC_API_KEY / OPENAI_API_KEY are dropped to avoid
    # the SDK's silent-overlay bug and to make the subscription auth path the
    # only one that applies.
    env: dict[str, str] = {k: v for k, v in os.environ.items() if k in _PASSTHROUGH_ENV_VARS}
    env["CLAUDE_CODE_ENTRYPOINT"] = "cli"
    if extra_env:
        env.update(extra_env)

    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        env=env,
        timeout=timeout_s,
        check=False,
    )
    if proc.returncode != 0:
        stderr_tail = "\n".join((proc.stderr or "").splitlines()[-20:])
        raise ClaudeCodeError(proc.returncode, stderr_tail)

    payload = parse_llm_json(proc.stdout or "")
    # ``claude -p --output-format json`` returns:
    #   {"type":"result","result":"...","total_cost_usd":..., "duration_ms":...}
    if not isinstance(payload, dict) or "result" not in payload:
        keys = list(payload.keys())[:5] if isinstance(payload, dict) else []
        raise ClaudeCodeError(0, f"unexpected payload shape: {keys}")
    return str(payload["result"])


# ---------------------------------------------------------------------------
# Unified entry point + model-resolution chain
# ---------------------------------------------------------------------------


def complete(prompt: str, model: str, **kw) -> str:
    """Unified entry point. Routes to claude-code or litellm based on prefix.

    * ``model.startswith("claude-code/")`` → ``complete_via_claude_code``
      with the part after the slash (e.g. ``claude-code/sonnet`` → ``sonnet``).
    * Otherwise → ``litellm.completion`` with JSON-object response format.

    Optional kwargs forwarded:
      * ``timeout`` (int seconds) — used for both providers.
      * ``temperature`` (float) — litellm only.
    """
    if model.startswith("claude-code/"):
        return complete_via_claude_code(
            prompt,
            model=model.split("/", 1)[1],
            timeout_s=int(kw.get("timeout", 120)),
        )
    # Lazy import — keep litellm out of the cold path / CLI startup.
    import litellm

    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=kw.get("temperature", 0.0),
        response_format={"type": "json_object"},
        timeout=kw.get("timeout", 60),
    )
    return response.choices[0].message.content


def resolve_model(args: argparse.Namespace | None = None) -> str:
    """Pick an LLM model string using the SPEC-01KT22NMS0BN1F5B01HEFK87W0 six-step chain.

    Priority:
      1. ``args.model`` if non-empty.
      2. ``DECREE_LLM_MODEL`` env var.
      3. ``claude`` binary on PATH → ``claude-code/sonnet`` (new default).
      4. ``ANTHROPIC_API_KEY`` env → ``claude-3-5-sonnet-latest``.
      5. ``OPENAI_API_KEY`` env → ``gpt-4o-mini``.
      6. Else ``SystemExit(2)`` with help text.

    No validation that the model string is well-formed; the provider surfaces
    that at call time with a clear message.
    """
    explicit = getattr(args, "model", None) if args is not None else None
    if explicit:
        return str(explicit)
    env_model = os.environ.get("DECREE_LLM_MODEL")
    if env_model:
        return env_model
    if shutil.which("claude"):
        return "claude-code/sonnet"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude-3-5-sonnet-latest"
    if os.environ.get("OPENAI_API_KEY"):
        return "gpt-4o-mini"
    raise SystemExit("no LLM provider available; install Claude Code, or set ANTHROPIC_API_KEY / OPENAI_API_KEY")
