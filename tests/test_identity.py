"""Tests for canonical decree document IDs."""

import re

import pytest

from decree.identity import (
    DOC_ID_RE,
    filename_for_doc_id,
    filename_matches_doc_id,
    generate_doc_id,
    generate_ulid,
    require_doc_id,
)


def test_generate_ulid_is_valid_and_sortable_for_timestamp():
    first = generate_ulid(timestamp_ms=1, random_bits=0)
    second = generate_ulid(timestamp_ms=2, random_bits=0)
    assert first < second
    assert re.match(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$", first)


def test_generate_doc_id_uses_prefix():
    doc_id = generate_doc_id("spec")
    assert DOC_ID_RE.match(doc_id)
    assert doc_id.startswith("SPEC-")


def test_require_doc_id_rejects_wrong_prefix():
    with pytest.raises(ValueError, match="PRD-ULID"):
        require_doc_id("SPEC-00000000000000000000000001", prefix="PRD")


def test_filename_for_doc_id_and_match():
    doc_id = "SPEC-00000000000000000000000001"
    filename = filename_for_doc_id(doc_id, "test-spec")
    assert filename == "spec-00000000000000000000000001-test-spec.md"
    assert filename_matches_doc_id(filename, doc_id)
