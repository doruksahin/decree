"""Tests for `config.classify_path` — path-only source/corpus/generated classifier.

Backlog B7 (docs/dogfooding-feedback/06-research-backlog.md). The classifier is
deterministic and reads only the path string (never the working tree), so a
planned decree-document edit is not mistaken for ungoverned source code.
"""

from __future__ import annotations

import pytest

from decree.config import classify_path

DOC_DIRS = ["decree/prd", "decree/adr", "decree/spec"]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        # Source: real implementation files, and non-corpus markdown.
        ("src/decree/commands/intent_check.py", "source"),
        ("docs/usage.md", "source"),
        ("README.md", "source"),
        # Corpus: a decree decision document (self-edit), including bucketed ones.
        ("decree/adr/adr-01k-foo.md", "corpus"),
        ("decree/spec/intent-check/spec-01k-bar.md", "corpus"),
        ("decree/prd/prd-01k-baz.md", "corpus"),
        # Generated: decree-produced artifacts living under a doc dir.
        ("decree/adr/index.md", "generated"),
        ("decree/spec/index.md", "generated"),
        ("decree/adr/reports/adr-01k-foo-report.md", "generated"),
    ],
)
def test_classify_path_explicit_dirs(path: str, expected: str) -> None:
    assert classify_path(path, DOC_DIRS) == expected


def test_classify_path_normalizes_leading_dot_slash() -> None:
    assert classify_path("./decree/adr/adr-01k-foo.md", DOC_DIRS) == "corpus"


def test_classify_path_is_deterministic_without_working_tree() -> None:
    # No file exists at this path; classification must still resolve (path-only).
    assert classify_path("decree/spec/spec-does-not-exist.md", DOC_DIRS) == "corpus"
