"""SPEC-01KT22NMRZXE5C42F6Z0ZY559A retrieval-method plugin interface + the v1 KeywordBaseline.

A retrieval method takes a (db, query, k) triple and returns an ordered
list of decision_ids. v1 ships one method — `keyword-v1` — which wraps the
existing PRD-01KT22NMRS4QGHSFDBZ858PP1T keyword stack (`commands.queries.why()` for file_path
queries, raw `decisions_fts` MATCH for concept queries).

Plugin registry: module-level `METHODS` dict. SPEC-01KT22NMS0VWCTYPFPHP8M8V36+ register new methods
by mutating this dict (or via Python entry-points in a future iteration).
"""

from __future__ import annotations

from pathlib import Path
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
    """PRD-01KT22NMRS4QGHSFDBZ858PP1T v1 keyword stack, packaged as a retrieval method.

    - file_path queries → reuse `commands.queries.why()` (governs lookup).
    - concept   queries → raw `decisions_fts MATCH` over title+body.

    DB and query failures are not swallowed here. ``run_evaluation`` records
    method errors explicitly so broken retrieval does not look like low recall.
    """

    name: str = "keyword-v1"
    description: str = (
        "PRD-01KT22NMRS4QGHSFDBZ858PP1T baseline: `decree why` for file_path queries, "
        "`decisions_fts MATCH` (FTS5 porter unicode61) for concept queries."
    )

    def query(self, db: IndexDB, query: Query, *, k: int = 10) -> list[str]:
        if query.kind == "file_path":
            return [m.decision_id for m in why(db, query.query, limit=k)]
        if query.kind == "concept":
            return self._fts_query(db, query.query, k=k)
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
        sql = "SELECT id FROM decisions_fts WHERE decisions_fts MATCH ? ORDER BY bm25(decisions_fts) LIMIT ?"
        rows = conn.execute(sql, (expr, k)).fetchall()
        return [r[0] for r in rows]


# ── KeywordCalibrated (SPEC-01KT22NMS0VWCTYPFPHP8M8V36) ────────────────────────────


class KeywordCalibrated:
    """SPEC-01KT22NMS0VWCTYPFPHP8M8V36 — KeywordBaseline + confidence gates + calibrated threshold.

    Behavior:
      1. Run ``keyword-v1`` for top-K candidates.
      2. Enrich them, compute the 7 gate signals, take the composite.
      3. If ``composite < threshold``: return ``[]`` (abstain). Store a
         human-readable reason on the instance.
      4. Otherwise return the baseline's candidates unchanged.

    Calibration is required. Missing or malformed calibration raises when the
    method is queried, and the evaluation runner records that as a method error.
    """

    name: str = "keyword-v1-calibrated"
    description: str = (
        "SPEC-01KT22NMS0VWCTYPFPHP8M8V36 calibrated layer atop keyword-v1: 7-gate composite "
        "confidence with a conformal threshold from eval/calibrations/."
    )

    def __init__(
        self,
        *,
        calibration_path: object | None = None,
        baseline: KeywordBaseline | None = None,
    ) -> None:
        self._baseline = baseline or KeywordBaseline()
        self._abstention_reason: str | None = None
        self._last_signals: list[object] = []
        self._last_composite: float = 0.0
        self._last_would_return: list[str] = []
        self._calibration = None
        self._calibration_path: Path | None = None

        # Resolve the calibration path. Default: <project>/eval/calibrations/<name>.json.
        if calibration_path is None:
            try:
                from decree.config import get_project_root

                root = get_project_root()
                calibration_path = root / "eval" / "calibrations" / f"{self.name.replace('-calibrated', '')}.json"
            except Exception:
                calibration_path = None

        if calibration_path is not None:
            self._calibration_path = Path(calibration_path)

    def _require_calibration(self):
        if self._calibration is not None:
            return self._calibration
        if self._calibration_path is None:
            raise FileNotFoundError(
                "calibration path could not be resolved; run `decree retrieval-eval --calibrate` "
                "or pass a calibration path"
            )
        if not self._calibration_path.exists():
            raise FileNotFoundError(
                f"calibration not found: {self._calibration_path}. Run `decree retrieval-eval --calibrate` first."
            )
        from decree.eval.calibration import read_calibration

        self._calibration = read_calibration(self._calibration_path)
        return self._calibration

    # ── Accessors ─────────────────────────────────────────

    @property
    def threshold(self) -> float:
        return float(self._require_calibration().threshold)

    @property
    def gate_weights(self) -> dict[str, float]:
        return dict(self._require_calibration().gate_weights)

    def last_abstention_reason(self) -> str | None:
        return self._abstention_reason

    def last_diagnostics(self) -> dict[str, object]:
        """Return per-signal scores + composite + threshold from the most recent query."""
        return {
            "composite": self._last_composite,
            "threshold": self.threshold,
            "signals": [
                {"name": s.name, "score": s.score, "hint": s.hint}  # type: ignore[attr-defined]
                for s in self._last_signals
            ],
            "would_return": list(self._last_would_return),
        }

    # ── Plug-in interface ─────────────────────────────────

    def query(self, db: IndexDB, query: Query, *, k: int = 10) -> list[str]:
        from decree.eval.gates import composite, compute_signals, enrich_rows

        calibration = self._require_calibration()

        # Reset per-call state.
        self._abstention_reason = None
        self._last_signals = []
        self._last_composite = 0.0
        self._last_would_return = []

        candidates = self._baseline.query(db, query, k=k)
        if not candidates:
            self._abstention_reason = "baseline returned no candidates"
            return []

        rows = enrich_rows(db, candidates)
        signals = compute_signals(query, rows, db)
        weights = dict(calibration.gate_weights) or None
        comp = composite(signals, weights=weights)

        # Cache diagnostics regardless of accept/reject.
        self._last_signals = list(signals)
        self._last_composite = comp
        self._last_would_return = list(candidates)

        tau = float(calibration.threshold)
        if comp < tau:
            # Find the weakest gates for the abstention hint.
            ranked = sorted(signals, key=lambda s: s.score)
            top_failures = ranked[:3]
            failure_str = ", ".join(f"{s.name}={s.score:.2f}" for s in top_failures)
            self._abstention_reason = (
                f"composite confidence {comp:.2f} below threshold {tau:.2f} (weakest: {failure_str})"
            )
            return []
        return candidates


# ── Module-level registry ───────────────────────────────────

METHODS: dict[str, RetrievalMethod] = {}


def register(method: RetrievalMethod) -> RetrievalMethod:
    """Register a method (idempotent; later registrations overwrite)."""
    METHODS[method.name] = method
    return method


# Register the v1 baseline at import time.
register(KeywordBaseline())


# Register the SPEC-01KT22NMS0VWCTYPFPHP8M8V36 calibrated method. Calibration
# loads lazily and raises as an explicit method error when missing or malformed.
register(KeywordCalibrated())
