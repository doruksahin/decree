"""Shared helpers for parsing agent-produced JSON.

Core decree does not own LLM provider execution. Agent integrations may call
any model/runtime they choose, but data handed back to decree must be explicit
JSON contracts that deterministic commands can validate.
"""

from __future__ import annotations

import json


def parse_llm_json(content: str) -> dict:
    """Parse a JSON object, tolerating one markdown code-fence wrapper.

    Agent runtimes often return JSON wrapped in `````json`` fences. Decree
    strips one leading/trailing fence pair and then delegates to ``json.loads``.
    Invalid JSON intentionally raises ``json.JSONDecodeError``.
    """
    text = content.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise TypeError("expected a JSON object")
    return payload
