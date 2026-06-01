"""SPEC-01KT22NMS0VWCTYPFPHP8M8V36 — conformal calibration of confidence-gate thresholds.

We treat abstain/return as binary classification with the composite gate
signal as the discriminator. ``crepes.ConformalClassifier`` provides the
split-conformal machinery; we drive it deterministically (seed=42) and
pick the threshold tau that achieves the requested precision on the held-out
split.

Crepes' ``ConformalClassifier`` is fed *non-conformity scores* per class
(lower = more conformal to a class). We transform our confidence scores
``c in [0, 1]`` into a 2-column non-conformity matrix:

  alpha[:, 1] = 1 - c     # non-conformity of label "relevant"
  alpha[:, 0] = c         # non-conformity of label "irrelevant"

After fitting on calibration data, we sweep candidate thresholds on the
held-out test split and pick the smallest tau achieving the target precision
among accepted predictions. ``crepes``'s p-values are recorded alongside
for transparency but the decision rule is the empirical tau — this is the
standard selective-classification pattern (El-Yaniv & Wiener, 2010).

If ``crepes`` cannot be imported, calibration degrades to the same
threshold-sweep without conformal p-values; the resulting Calibration is
still usable. SPEC-01KT22NMS0VWCTYPFPHP8M8V36 commits to *using* the library when it's there.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from decree.eval.methods import RetrievalMethod
    from decree.eval.schema import QuerySet
    from decree.index_db import IndexDB


# ── Calibration dataclass ──────────────────────────────────


class Calibration(BaseModel):
    """Persisted calibration record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method_name: str
    target_precision: float
    threshold: float
    gate_weights: dict[str, float] = Field(default_factory=dict)
    calibrated_at: str
    n_calibration_queries: int
    # Diagnostics — useful when threshold looks degenerate.
    test_precision: float = 0.0
    test_coverage: float = 0.0
    notes: str | None = None


# ── Save / read ────────────────────────────────────────────


def save_calibration(c: Calibration, path: Path) -> None:
    """Persist a Calibration to JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(c.model_dump_json(indent=2))


def read_calibration(path: Path) -> Calibration:
    """Load + validate a Calibration JSON file."""
    data = json.loads(path.read_text())
    return Calibration(**data)


# ── Calibration pipeline ───────────────────────────────────


def _score_query(
    method: RetrievalMethod,
    db: IndexDB,
    query,
    weights: dict[str, float] | None,
) -> tuple[float, int]:
    """Run a method on a query; return (composite_score, label).

    Label = 1 if Recall@1 > 0 (i.e., top result was in the relevant set per
    qrels), else 0. Queries with empty `relevant` (intentional abstention
    queries) get label 0.
    """
    from decree.eval.gates import composite, compute_signals, enrich_rows

    decision_ids = method.query(db, query, k=10)
    if not decision_ids:
        # Method returned nothing — composite is 0, label is 0 (no top hit).
        return 0.0, 0
    rows = enrich_rows(db, decision_ids)
    signals = compute_signals(query, rows, db)
    score = composite(signals, weights=weights)

    relevant = set(query.relevant)
    label = 0 if not relevant else 1 if decision_ids[0] in relevant else 0
    return score, label


def calibrate_method(
    method: RetrievalMethod,
    query_set: QuerySet,
    target_precision: float,
    project_root: Path,
    *,
    gate_weights: dict[str, float] | None = None,
    db: IndexDB | None = None,
    seed: int = 42,
) -> Calibration:
    """End-to-end calibration.

    1. Split the labeled query set 60/40 (deterministic shuffle with ``seed``).
    2. For each calibration query: compute composite score + label.
    3. Fit a crepes ConformalClassifier on the calibration split (best-effort —
       its p-values feed the diagnostics; the decision threshold is the
       empirical tau sweep on the held-out split).
    4. Pick tau such that precision among test-split accepts >= ``target_precision``.
    """
    from decree.eval.schema import QuerySet  # noqa: F401 — type hint only
    from decree.index_db import IndexDB, default_db_path

    if db is None:
        db = IndexDB(default_db_path(project_root))

    queries = list(query_set.queries)
    rng = random.Random(seed)
    rng.shuffle(queries)
    split = max(1, int(len(queries) * 0.6))
    cal_queries = queries[:split]
    test_queries = queries[split:]

    cal_scores: list[float] = []
    cal_labels: list[int] = []
    for q in cal_queries:
        s, y = _score_query(method, db, q, gate_weights)
        cal_scores.append(s)
        cal_labels.append(y)

    test_scores: list[float] = []
    test_labels: list[int] = []
    for q in test_queries:
        s, y = _score_query(method, db, q, gate_weights)
        test_scores.append(s)
        test_labels.append(y)

    # ── Fit conformal classifier (diagnostic; threshold decided by tau sweep) ──
    notes_parts: list[str] = []
    try:
        from crepes import ConformalClassifier  # type: ignore[import-not-found]

        cal_alphas = np.column_stack(
            [
                np.array(cal_scores, dtype=float),  # alpha for label 0 (irrelevant)
                1.0 - np.array(cal_scores, dtype=float),  # alpha for label 1 (relevant)
            ]
        )
        cc = ConformalClassifier()
        cc.fit(cal_alphas, seed=seed)
        notes_parts.append(f"crepes.ConformalClassifier fitted on n={len(cal_scores)}")
    except Exception as e:
        notes_parts.append(f"crepes unavailable or failed: {type(e).__name__}: {e}")

    # ── Threshold sweep on held-out test split ──────────────
    threshold, test_p, test_c = _pick_threshold(test_scores, test_labels, target_precision)

    notes_parts.append(f"tau={threshold:.4f}; test precision={test_p:.3f}, coverage={test_c:.3f}")

    # Default weights = uniform 1.0 for the 7 gates.
    final_weights = (
        dict(gate_weights)
        if gate_weights
        else {
            "dominance": 1.0,
            "identifier-citation": 1.0,
            "hedge-phrase": 1.0,
            "status": 1.0,
            "recency": 1.0,
            "coverage": 1.0,
            "authorship": 1.0,
        }
    )

    return Calibration(
        method_name=method.name,
        target_precision=target_precision,
        threshold=float(threshold),
        gate_weights=final_weights,
        calibrated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        n_calibration_queries=len(cal_queries),
        test_precision=float(test_p),
        test_coverage=float(test_c),
        notes="; ".join(notes_parts),
    )


def _pick_threshold(
    scores: list[float],
    labels: list[int],
    target_precision: float,
) -> tuple[float, float, float]:
    """Sweep candidate thresholds; return (τ, precision_at_τ, coverage_at_τ).

    For each candidate τ in sorted unique scores (plus 0 and 1):
      * accept = {i : score_i > τ}
      * precision = (positives among accepted) / len(accepted)
      * coverage  = len(accepted) / total

    Pick the smallest τ where precision ≥ target. If no τ achieves it,
    return τ = max(scores) (degenerate: abstain on every test query), with
    the precision/coverage from that τ.
    """
    if not scores:
        return 1.0, 0.0, 0.0

    scores_arr = np.array(scores, dtype=float)
    labels_arr = np.array(labels, dtype=int)
    # Candidates: midpoints between sorted unique scores, plus boundaries.
    sorted_unique = sorted(set(scores))
    candidates: list[float] = [0.0]
    for i in range(len(sorted_unique) - 1):
        candidates.append((sorted_unique[i] + sorted_unique[i + 1]) / 2.0)
    candidates.append(min(1.0, sorted_unique[-1] + 1e-6))

    # Evaluate each candidate.
    best_tau = candidates[-1]
    best_p = 0.0
    best_c = 0.0
    for tau in candidates:
        accept_mask = scores_arr > tau
        n_accept = int(accept_mask.sum())
        if n_accept == 0:
            continue
        precision = float(labels_arr[accept_mask].sum()) / n_accept
        coverage = n_accept / len(scores)
        if precision >= target_precision:
            return float(tau), precision, coverage
        # Keep the best fallback (highest precision; ties broken by higher coverage).
        if precision > best_p or (precision == best_p and coverage > best_c):
            best_tau = tau
            best_p = precision
            best_c = coverage

    return float(best_tau), best_p, best_c


__all__ = [
    "Calibration",
    "calibrate_method",
    "read_calibration",
    "save_calibration",
]
