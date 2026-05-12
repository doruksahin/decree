"""Shared helpers for LLM I/O across decree commands.

This module exists to eliminate duplication between SPEC-011 (`commands.migrate`)
and SPEC-014 (`commands.intent_check`) — both of which call `litellm.completion`
with `response_format={"type": "json_object"}` and need fence-tolerant JSON
parsing on the response.

Future LLM-using commands (e.g., research-frontier C.3 ADR refinement) should
import from here rather than re-implement.
"""

from __future__ import annotations

import json


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
