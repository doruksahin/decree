"""SPEC-012 query-set schema — pydantic models + YAML loader.

Schema rules (validated):
    * `kind` is "file_path" or "concept".
    * Every entry in `relevant` matches the decree decision-id regex
      (`^[A-Z]+-\\d+$`). Same for grade keys.
    * Per-query `id` is unique within a query set.
    * Unknown keys are rejected (model_config has extra="forbid").
    * Both binary (`relevant: [...]`) and graded
      (`grades: {DECISION-NNN: int}`) relevance are supported.
      For binary, all relevant docs are assigned grade 1.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# Matches PRD-001, ADR-0001, SPEC-001, etc. Prefix must be ALL-CAPS letters
# (allowing the prefix length to grow without code change).
DECISION_ID_RE = re.compile(r"^[A-Z]+-\d+$")

QueryKind = Literal["file_path", "concept"]


class Query(BaseModel):
    """One labeled query."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: QueryKind
    query: str
    relevant: list[str] = Field(default_factory=list)
    grades: dict[str, int] | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "Query":
        # decision-id format for relevant + grades keys
        for did in self.relevant:
            if not DECISION_ID_RE.match(did):
                raise ValueError(
                    f"query {self.id!r}: 'relevant' entry {did!r} does not match {DECISION_ID_RE.pattern}"
                )
        if self.grades is not None:
            for did, grade in self.grades.items():
                if not DECISION_ID_RE.match(did):
                    raise ValueError(
                        f"query {self.id!r}: 'grades' key {did!r} does not match {DECISION_ID_RE.pattern}"
                    )
                if not isinstance(grade, int) or grade < 0:
                    raise ValueError(
                        f"query {self.id!r}: 'grades' value for {did!r} must be a non-negative int (got {grade!r})"
                    )
        # ID can't be empty
        if not self.id:
            raise ValueError("query id must be non-empty")
        # Query string can't be empty
        if not self.query:
            raise ValueError(f"query {self.id!r}: 'query' must be non-empty")
        return self

    def effective_grades(self) -> dict[str, int]:
        """Return {decision_id: grade}. Falls back to binary 1 when no grades block."""
        if self.grades is not None:
            return dict(self.grades)
        return {did: 1 for did in self.relevant}


class QuerySet(BaseModel):
    """A labeled query set parsed from YAML."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    corpus: str
    description: str = ""
    created: str | None = None
    author_note: str | None = None
    total_queries: int | None = None
    queries: list[Query]

    @model_validator(mode="after")
    def _validate(self) -> "QuerySet":
        if not self.queries:
            raise ValueError("queries list must be non-empty")
        seen: set[str] = set()
        for q in self.queries:
            if q.id in seen:
                raise ValueError(f"duplicate query id: {q.id!r}")
            seen.add(q.id)
        if self.total_queries is not None and self.total_queries != len(self.queries):
            # Soft constraint: keep declared and actual counts in sync to catch
            # author drift. Strict equality keeps the YAML honest.
            raise ValueError(
                f"total_queries={self.total_queries} disagrees with actual {len(self.queries)} entries"
            )
        return self


def load_query_set(path: Path) -> QuerySet:
    """Parse and validate a YAML query set."""
    with open(path) as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping")
    return QuerySet.model_validate(raw)
