"""Unit tests for ``decree.llm_io`` (SPEC-00000000000000000000000015).

Covers the 13 unit cases the SPEC enumerates plus the six-step
``resolve_model`` chain. No real subprocess calls; all use
``monkeypatch.setattr(subprocess, "run", ...)`` to capture the args/env
passed to the would-be ``claude`` invocation.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _ok_payload(result: str = "hello", **extra: Any) -> str:
    """Shape a ``claude -p --output-format json`` happy-path payload."""
    base = {
        "type": "result",
        "result": result,
        "total_cost_usd": 0.0,
        "duration_ms": 12,
    }
    base.update(extra)
    return json.dumps(base)


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def fake_claude_bin(monkeypatch):
    """Pretend ``claude`` is at /usr/local/bin/claude."""
    monkeypatch.setattr(
        "decree.llm_io.shutil.which",
        lambda name: "/usr/local/bin/claude" if name == "claude" else None,
    )
    return "/usr/local/bin/claude"


@pytest.fixture
def captured_run(monkeypatch):
    """Patch ``subprocess.run`` and capture its args/env per call.

    Returns a dict with ``last``: the most recent kwargs dict, and ``calls``:
    list of all kwargs dicts. The mock's return value can be set via
    ``state["return"] = subprocess.CompletedProcess(...)`` before the call.
    """
    state: dict[str, Any] = {
        "calls": [],
        "return": _completed(stdout=_ok_payload()),
        "exc": None,
    }

    def fake_run(args, **kw):
        state["calls"].append({"args": args, **kw})
        state["last"] = state["calls"][-1]
        if state["exc"] is not None:
            raise state["exc"]
        return state["return"]

    monkeypatch.setattr("decree.llm_io.subprocess.run", fake_run)
    return state


# ---------------------------------------------------------------------------
# complete_via_claude_code — 11 unit cases
# ---------------------------------------------------------------------------


class TestCompleteViaClaudeCode:
    def test_happy_path(self, fake_claude_bin, captured_run):
        from decree.llm_io import complete_via_claude_code

        captured_run["return"] = _completed(stdout=_ok_payload("hi there"))
        out = complete_via_claude_code("ping", model="sonnet")
        assert out == "hi there"
        assert captured_run["last"]["args"][0] == fake_claude_bin

    def test_missing_binary_raises(self, monkeypatch, captured_run):
        monkeypatch.setattr("decree.llm_io.shutil.which", lambda name: None)
        from decree.llm_io import ClaudeCodeError, complete_via_claude_code

        with pytest.raises(ClaudeCodeError) as exc:
            complete_via_claude_code("ping")
        assert exc.value.returncode == -1
        assert "not found on PATH" in exc.value.stderr_tail
        # subprocess.run must not have been called.
        assert captured_run["calls"] == []

    def test_nonzero_exit_raises_with_stderr_tail(self, fake_claude_bin, captured_run):
        from decree.llm_io import ClaudeCodeError, complete_via_claude_code

        stderr = "\n".join(f"line {i}" for i in range(1, 31))  # 30 lines
        captured_run["return"] = _completed(stdout="", stderr=stderr, returncode=2)
        with pytest.raises(ClaudeCodeError) as exc:
            complete_via_claude_code("ping")
        assert exc.value.returncode == 2
        # Last 20 lines only.
        tail_lines = exc.value.stderr_tail.splitlines()
        assert len(tail_lines) == 20
        assert tail_lines[0] == "line 11"
        assert tail_lines[-1] == "line 30"

    def test_malformed_json_propagates(self, fake_claude_bin, captured_run):
        from decree.llm_io import complete_via_claude_code

        captured_run["return"] = _completed(stdout="not json at all")
        with pytest.raises(json.JSONDecodeError):
            complete_via_claude_code("ping")

    def test_missing_result_key_raises(self, fake_claude_bin, captured_run):
        from decree.llm_io import ClaudeCodeError, complete_via_claude_code

        captured_run["return"] = _completed(stdout=json.dumps({"foo": "bar"}))
        with pytest.raises(ClaudeCodeError) as exc:
            complete_via_claude_code("ping")
        assert exc.value.returncode == 0
        assert "unexpected payload shape" in exc.value.stderr_tail

    def test_timeout_propagates(self, fake_claude_bin, captured_run):
        from decree.llm_io import complete_via_claude_code

        captured_run["exc"] = subprocess.TimeoutExpired(cmd="claude", timeout=1)
        with pytest.raises(subprocess.TimeoutExpired):
            complete_via_claude_code("ping", timeout_s=1)

    def test_env_scrubs_api_keys(self, fake_claude_bin, captured_run, monkeypatch):
        """ANTHROPIC_API_KEY and OPENAI_API_KEY MUST NOT be in subprocess env."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-secret")
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        from decree.llm_io import complete_via_claude_code

        complete_via_claude_code("ping")
        env = captured_run["last"]["env"]
        assert "ANTHROPIC_API_KEY" not in env
        assert "OPENAI_API_KEY" not in env
        # Confirm we still got PATH through (sanity).
        assert env["PATH"] == "/usr/bin:/bin"

    def test_env_sets_claude_code_entrypoint(self, fake_claude_bin, captured_run):
        from decree.llm_io import complete_via_claude_code

        complete_via_claude_code("ping")
        env = captured_run["last"]["env"]
        assert env["CLAUDE_CODE_ENTRYPOINT"] == "cli"

    def test_strict_mcp_config_flag(self, fake_claude_bin, captured_run):
        from decree.llm_io import complete_via_claude_code

        complete_via_claude_code("ping")
        args = captured_run["last"]["args"]
        assert "--strict-mcp-config" in args

    def test_permission_mode_plan_flag(self, fake_claude_bin, captured_run):
        from decree.llm_io import complete_via_claude_code

        complete_via_claude_code("ping")
        args = captured_run["last"]["args"]
        idx = args.index("--permission-mode")
        assert args[idx + 1] == "plan"

    def test_allowed_tools_default_none(self, fake_claude_bin, captured_run):
        from decree.llm_io import complete_via_claude_code

        complete_via_claude_code("ping")  # allowed_tools=None default
        args = captured_run["last"]["args"]
        idx = args.index("--allowedTools")
        assert args[idx + 1] == "none"

    def test_allowed_tools_empty_list_also_none(self, fake_claude_bin, captured_run):
        from decree.llm_io import complete_via_claude_code

        complete_via_claude_code("ping", allowed_tools=[])
        args = captured_run["last"]["args"]
        idx = args.index("--allowedTools")
        assert args[idx + 1] == "none"

    def test_allowed_tools_explicit_list(self, fake_claude_bin, captured_run):
        from decree.llm_io import complete_via_claude_code

        complete_via_claude_code("ping", allowed_tools=["Read", "Glob"])
        args = captured_run["last"]["args"]
        idx = args.index("--allowedTools")
        assert args[idx + 1] == "Read,Glob"

    def test_max_turns_and_output_format(self, fake_claude_bin, captured_run):
        from decree.llm_io import complete_via_claude_code

        complete_via_claude_code("ping")
        args = captured_run["last"]["args"]
        of_idx = args.index("--output-format")
        assert args[of_idx + 1] == "json"
        mt_idx = args.index("--max-turns")
        assert args[mt_idx + 1] == "1"

    def test_extra_env_merged_last(self, fake_claude_bin, captured_run):
        from decree.llm_io import complete_via_claude_code

        complete_via_claude_code("ping", extra_env={"CUSTOM_VAR": "hello"})
        env = captured_run["last"]["env"]
        assert env["CUSTOM_VAR"] == "hello"
        # CLAUDE_CODE_ENTRYPOINT still wins because extra_env can override
        # it intentionally; we don't override that here.
        assert env["CLAUDE_CODE_ENTRYPOINT"] == "cli"


# ---------------------------------------------------------------------------
# complete() — routing
# ---------------------------------------------------------------------------


class TestCompleteRouting:
    def test_routes_claude_code_prefix(self, monkeypatch):
        from decree import llm_io

        captured: dict[str, Any] = {}

        def fake_ccc(prompt, *, model, timeout_s):
            captured["prompt"] = prompt
            captured["model"] = model
            captured["timeout_s"] = timeout_s
            return "from-claude-code"

        monkeypatch.setattr(llm_io, "complete_via_claude_code", fake_ccc)
        out = llm_io.complete("hi", "claude-code/sonnet")
        assert out == "from-claude-code"
        assert captured["model"] == "sonnet"
        assert captured["prompt"] == "hi"

    def test_routes_claude_code_opus(self, monkeypatch):
        from decree import llm_io

        captured: dict[str, Any] = {}

        def fake_ccc(prompt, *, model, timeout_s):
            captured["model"] = model
            return "ok"

        monkeypatch.setattr(llm_io, "complete_via_claude_code", fake_ccc)
        llm_io.complete("hi", "claude-code/opus")
        assert captured["model"] == "opus"

    def test_routes_litellm_for_other(self, monkeypatch):
        from decree import llm_io

        called: dict[str, Any] = {}

        def fake_completion(**kw):
            called["model"] = kw["model"]
            called["messages"] = kw["messages"]
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="from-litellm"))])

        import litellm

        monkeypatch.setattr(litellm, "completion", fake_completion)
        out = llm_io.complete("hi", "gpt-4o-mini")
        assert out == "from-litellm"
        assert called["model"] == "gpt-4o-mini"
        assert called["messages"][0]["content"] == "hi"


# ---------------------------------------------------------------------------
# resolve_model() — six-step chain
# ---------------------------------------------------------------------------


class TestResolveModelChain:
    """Six-step chain per SPEC-00000000000000000000000015."""

    def _ns(self, model=None):
        return argparse.Namespace(model=model)

    def test_step1_explicit_model_wins(self, monkeypatch):
        monkeypatch.setenv("DECREE_LLM_MODEL", "env-model")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        monkeypatch.setattr(shutil, "which", lambda n: "/bin/claude")
        from decree.llm_io import resolve_model

        assert resolve_model(self._ns(model="explicit")) == "explicit"

    def test_step2_env_var(self, monkeypatch):
        monkeypatch.setenv("DECREE_LLM_MODEL", "env-model")
        monkeypatch.setattr(shutil, "which", lambda n: "/bin/claude")
        from decree.llm_io import resolve_model

        assert resolve_model(self._ns()) == "env-model"

    def test_step3_claude_on_path(self, monkeypatch):
        monkeypatch.delenv("DECREE_LLM_MODEL", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(
            "decree.llm_io.shutil.which",
            lambda n: "/usr/local/bin/claude" if n == "claude" else None,
        )
        from decree.llm_io import resolve_model

        assert resolve_model(self._ns()) == "claude-code/sonnet"

    def test_step4_anthropic_key(self, monkeypatch):
        monkeypatch.delenv("DECREE_LLM_MODEL", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        monkeypatch.setattr("decree.llm_io.shutil.which", lambda n: None)
        from decree.llm_io import resolve_model

        assert resolve_model(self._ns()) == "claude-3-5-sonnet-latest"

    def test_step5_openai_key(self, monkeypatch):
        monkeypatch.delenv("DECREE_LLM_MODEL", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        monkeypatch.setattr("decree.llm_io.shutil.which", lambda n: None)
        from decree.llm_io import resolve_model

        assert resolve_model(self._ns()) == "gpt-4o-mini"

    def test_step6_no_provider_exits(self, monkeypatch):
        monkeypatch.delenv("DECREE_LLM_MODEL", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr("decree.llm_io.shutil.which", lambda n: None)
        from decree.llm_io import resolve_model

        with pytest.raises(SystemExit):
            resolve_model(self._ns())

    def test_claude_code_models_pass_through(self, monkeypatch):
        """``--model claude-code/opus-4-7`` should be returned verbatim."""
        from decree.llm_io import resolve_model

        ns = self._ns(model="claude-code/opus-4-7")
        assert resolve_model(ns) == "claude-code/opus-4-7"

    def test_resolve_model_accepts_none(self, monkeypatch):
        """``resolve_model()`` with no args should still work."""
        monkeypatch.delenv("DECREE_LLM_MODEL", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(
            "decree.llm_io.shutil.which",
            lambda n: "/bin/claude" if n == "claude" else None,
        )
        from decree.llm_io import resolve_model

        assert resolve_model() == "claude-code/sonnet"
