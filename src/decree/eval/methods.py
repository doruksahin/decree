"""SPEC-012 retrieval-method plugin interface + the v1 KeywordBaseline.

A retrieval method takes a (db, query, k) triple and returns an ordered
list of decision_ids. v1 ships one method — `keyword-v1` — which wraps the
existing PRD-003 keyword stack (`commands.queries.why()` for file_path
queries, raw `decisions_fts` MATCH for concept queries).

Plugin registry: module-level `METHODS` dict. SPEC-013+ register new methods
by mutating this dict (or via Python entry-points in a future iteration).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from decree.commands.queries import why
from decree.eval.schema import Query
from decree.index_db import IndexDB


@runtime_checkable
class RetrievalMethod(Protocol):
    """Plug-in interface — one signature, one return."""

    name: str
    description: str

    def query(self, db: IndexDB, query: Query, *, k: int = 10) -> list[str]:
        """Return an ordered list of decision_ids (best first), truncated to k."""
        ...


# ── KeywordBaseline ─────────────────────────────────────────


class KeywordBaseline:
    """PRD-003 v1 keyword stack, packaged as a retrieval method.

    - file_path queries → reuse `commands.queries.why()` (governs lookup).
    - concept   queries → raw `decisions_fts MATCH` over title+body.

    Failures are isolated per-query: any DB-side exception is caught and an
    empty list is returned so the overall harness can keep going.
    """

    name: str = "keyword-v1"
    description: str = (
        "PRD-003 baseline: `decree why` for file_path queries, "
        "`decisions_fts MATCH` (FTS5 porter unicode61) for concept queries."
    )

    def query(self, db: IndexDB, query: Query, *, k: int = 10) -> list[str]:
        try:
            if query.kind == "file_path":
                return [m.decision_id for m in why(db, query.query, limit=k)]
            if query.kind == "concept":
                return self._fts_query(db, query.query, k=k)
        except Exception:  # noqa: BLE001 — per-query isolation per SPEC
            return []
        return []

    @staticmethod
    def _fts_query(db: IndexDB, q: str, *, k: int) -> list[str]:
        """Run a FTS5 MATCH query and return BM25-ranked decision_ids.

        Strategy: tokenise the input on non-alphanumeric characters and
        OR-join the surviving tokens as FTS5 single-token terms. This:
          * survives natural-language input with punctuation, quotes, dashes.
          * widens recall (any matched token retrieves the doc), which is
            the right default for v1 keyword retrieval — phrase matching is
            too strict for ~17-doc corpus.
          * ranks by FTS5's built-in `bm25(decisions_fts)`.

        Each token is wrapped in double quotes so FTS5 treats it as a
        literal term (e.g. `python` rather than a column-filter or operator).
        """
        import re

        tokens = [t for t in re.findall(r"[A-Za-z0-9]+", q) if t]
        if not tokens:
            return []
        # OR-join quoted single tokens; FTS5 treats `"foo" OR "bar"` as the
        # union of postings.
        expr = " OR ".join(f'"{t}"' for t in tokens)
        conn = db.db.conn  # type: ignore[attr-defined]
        sql = (
            "SELECT id FROM decisions_fts "
            "WHERE decisions_fts MATCH ? "
            "ORDER BY bm25(decisions_fts) "
            "LIMIT ?"
        )
        rows = conn.execute(sql, (expr, k)).fetchall()
        return [r[0] for r in rows]


# ── Module-level registry ───────────────────────────────────

METHODS: dict[str, RetrievalMethod] = {}


def register(method: RetrievalMethod) -> RetrievalMethod:
    """Register a method (idempotent; later registrations overwrite)."""
    METHODS[method.name] = method
    return method


# Register the v1 baseline at import time.
register(KeywordBaseline())
