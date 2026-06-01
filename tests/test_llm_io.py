"""Tests for provider-free JSON parsing helpers."""

from __future__ import annotations

import json

import pytest

from decree.llm_io import parse_llm_json


def test_parse_plain_json_object() -> None:
    assert parse_llm_json('{"ok": true}') == {"ok": True}


def test_parse_fenced_json_object() -> None:
    assert parse_llm_json('```json\n{"governs": ["src/foo.py"]}\n```') == {"governs": ["src/foo.py"]}


def test_parse_invalid_json_raises() -> None:
    with pytest.raises(json.JSONDecodeError):
        parse_llm_json("not json")


def test_parse_non_object_raises() -> None:
    with pytest.raises(TypeError):
        parse_llm_json('["not", "an", "object"]')
