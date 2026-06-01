"""SPEC-01KT22NMS0VWCTYPFPHP8M8V36 — confidence gates for calibrated abstention.

Seven gates, each a pure function reading from the IndexDB. Each emits a
``GateSignal`` in ``[0, 1]`` where higher = more confident the top hit is
genuinely relevant. Gates compose via a weighted geometric mean
(``composite()``) — the veto property is intentional: if any one signal is
near 0, the composite collapses, which is exactly what we want for an
"abstain unless all signals concur" policy.

Gates split into two camps:

* 3 Repowise-replica gates (``dominance``, ``identifier_citation``,
  ``hedge_phrase``).
* 4 SPEC-01KT22NMS0VWCTYPFPHP8M8V36 gates (``status``, ``recency``, ``coverage``, ``authorship``).

The interface ``GateFn = Callable[[Query, list[RetrievalRow], IndexDB], GateSignal]``
is intentionally pin-thin: a gate reads exactly what it needs from the row
or the DB, returns a scalar score. No side effects.
"""

from __future__ import annotations

import math
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from decree.eval.schema import Query
from decree.index_db import IndexDB

# ── Dataclasses ─────────────────────────────────────────────


@dataclass(frozen=True)
class GateSignal:
    """One gate's verdict on a query/result pair."""

    name: str
    score: float
    hint: str | None = None


@dataclass(frozen=True)
class RetrievalRow:
    """A rich row fed to the gates.

    Carries enough metadata that no gate needs to re-query the DB for fields
    that the runner already had to fetch. ``body`` and ``governs_paths``
    are populated by :func:`enrich_rows`.
    """

    decision_id: str
    rank: int
    raw_score: float
    title: str = ""
    status: str = ""
    date_str: str = ""
    body: str = ""
    governs_paths: tuple[str, ...] = ()
    doc_path: str = ""


GateFn = Callable[[Query, list[RetrievalRow], IndexDB], GateSignal]


# ── Helpers ─────────────────────────────────────────────────


_IDENT_SPLIT_RE = re.compile(r"[\/\\_\-.\s]+")


def _split_identifiers(text: str) -> list[str]:
    """Split a query string into identifier tokens.

    Splits on path separators, snake/kebab, dots, and whitespace. Empty
    tokens dropped, lowercased. e.g. ``"src/decree/index_db.py"`` →
    ``["src", "decree", "index", "db", "py"]``.
    """
    return [t.lower() for t in _IDENT_SPLIT_RE.split(text) if t]


def _parse_date(date_str: str) -> date | None:
    """Parse an ISO date string or return None on failure."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def enrich_rows(
    db: IndexDB,
    decision_ids: list[str],
    *,
    raw_scores: dict[str, float] | None = None,
) -> list[RetrievalRow]:
    """Turn a list of decision_ids into RetrievalRows with body + governs.

    Single batched SQL fan-out: one query for decisions metadata, one for
    governs, one for body via FTS table. Keeps the gate API decoupled from
    the schema.
    """
    if not decision_ids:
        return []

    conn = db.db.conn  # type: ignore[attr-defined]

    placeholders = ",".join("?" for _ in decision_ids)

    meta_rows = {
        r[0]: r
        for r in conn.execute(
            f"SELECT id, title, status, date, path FROM decisions WHERE id IN ({placeholders})",
            decision_ids,
        )
    }

    bodies: dict[str, str] = {}
    for r in conn.execute(
        f"SELECT id, body FROM decisions_fts WHERE id IN ({placeholders})",
        decision_ids,
    ):
        bodies[r[0]] = r[1] or ""

    governs: dict[str, list[str]] = {did: [] for did in decision_ids}
    for r in conn.execute(
        f"SELECT decision_id, path FROM governs WHERE decision_id IN ({placeholders}) "
        f"ORDER BY decision_id, order_index",
        decision_ids,
    ):
        governs.setdefault(r[0], []).append(r[1])

    rows: list[RetrievalRow] = []
    for rank, did in enumerate(decision_ids):
        meta = meta_rows.get(did)
        if meta is None:
            # Decision not in DB anymore (stale rank list). Emit a sparse row.
            rows.append(
                RetrievalRow(
                    decision_id=did,
                    rank=rank,
                    raw_score=(raw_scores or {}).get(did, 0.0),
                )
            )
            continue
        rows.append(
            RetrievalRow(
                decision_id=did,
                rank=rank,
                raw_score=(raw_scores or {}).get(did, float(len(decision_ids) - rank)),
                title=meta[1] or "",
                status=meta[2] or "",
                date_str=str(meta[3] or ""),
                body=bodies.get(did, ""),
                governs_paths=tuple(governs.get(did, [])),
                doc_path=meta[4] or "",
            )
        )
    return rows


# ── Gates ───────────────────────────────────────────────────


def dominance_gate(query: Query, rows: list[RetrievalRow], db: IndexDB) -> GateSignal:
    """Top score / second score ratio, saturating at 2x -> 1.0.

    A clean win means the top hit's raw retrieval score is at least 2x the
    runner-up's. If only one result, we cannot judge dominance -> 1.0
    (don't penalize a pure exact-match case where there's nothing to compare).
    """
    if len(rows) == 0:
        return GateSignal("dominance", 0.0, hint="no candidates")
    if len(rows) == 1:
        return GateSignal("dominance", 1.0, hint="single candidate (no runner-up)")
    top = rows[0].raw_score
    second = rows[1].raw_score
    if second <= 0:
        # Top has positive score, runner-up is zero → maximal dominance.
        if top > 0:
            return GateSignal("dominance", 1.0, hint=f"runner-up score 0 (top {top:.2f})")
        return GateSignal("dominance", 0.0, hint="all candidates score 0")
    ratio = top / second
    score = min(ratio / 2.0, 1.0)
    return GateSignal(
        "dominance",
        max(0.0, score),
        hint=f"top {top:.2f} / second {second:.2f} = {ratio:.2f}x",
    )


def identifier_citation_gate(query: Query, rows: list[RetrievalRow], db: IndexDB) -> GateSignal:
    """Fraction of query identifiers appearing in the top doc's title or governs paths."""
    if not rows:
        return GateSignal("identifier-citation", 0.0, hint="no candidates")
    top = rows[0]
    tokens = _split_identifiers(query.query)
    if not tokens:
        return GateSignal("identifier-citation", 1.0, hint="query has no identifiers")

    # Build the searchable haystack from title + governs paths.
    haystack_parts = [top.title.lower()]
    haystack_parts.extend(p.lower() for p in top.governs_paths)
    haystack = " ".join(haystack_parts)

    hits = sum(1 for t in tokens if t in haystack)
    score = hits / len(tokens)
    return GateSignal(
        "identifier-citation",
        score,
        hint=f"{hits} of {len(tokens)} query identifiers in top hit (title + governs)",
    )


_HEDGE_TERMS = ("might", "possibly", "tbd", "consider", "unclear")


def hedge_phrase_gate(query: Query, rows: list[RetrievalRow], db: IndexDB) -> GateSignal:
    """Count hedging phrases in top doc's body; signal = 1 - normalized count.

    Normalization: 5 or more hedges → 0.0 (very hedged), 0 hedges → 1.0.
    Linear interpolation between.
    """
    if not rows:
        return GateSignal("hedge-phrase", 0.0, hint="no candidates")
    body = rows[0].body.lower()
    if not body:
        # Empty body — can't judge. Don't penalize.
        return GateSignal("hedge-phrase", 1.0, hint="empty body (cannot judge)")
    count = sum(len(re.findall(rf"\b{re.escape(term)}\b", body)) for term in _HEDGE_TERMS)
    saturated = min(count, 5)
    score = 1.0 - (saturated / 5.0)
    return GateSignal(
        "hedge-phrase",
        score,
        hint=f"{count} hedge phrase{'s' if count != 1 else ''} in top body",
    )


_TERMINAL_SUCCESS_STATUSES = frozenset(("implemented", "accepted"))
_WARN_STATUSES = frozenset(("deprecated", "superseded", "rejected", "archived"))


def status_gate(query: Query, rows: list[RetrievalRow], db: IndexDB) -> GateSignal:
    """Status-driven veto: implemented/accepted → 1.0; deprecated/etc → 0.0; else 0.5."""
    if not rows:
        return GateSignal("status", 0.0, hint="no candidates")
    status = rows[0].status.lower()
    if status in _TERMINAL_SUCCESS_STATUSES:
        return GateSignal("status", 1.0, hint=f"status={status}")
    if status in _WARN_STATUSES:
        return GateSignal("status", 0.0, hint=f"status={status} (warn-on-reference)")
    return GateSignal("status", 0.5, hint=f"status={status} (active but not terminal)")


_RECENCY_HORIZON_DAYS = 540


def recency_gate(query: Query, rows: list[RetrievalRow], db: IndexDB) -> GateSignal:
    """1 - (days_since_date / 540), clamped to [0, 1]."""
    if not rows:
        return GateSignal("recency", 0.0, hint="no candidates")
    top = rows[0]
    parsed = _parse_date(top.date_str)
    if parsed is None:
        return GateSignal("recency", 0.5, hint="unparseable date")
    days = (date.today() - parsed).days
    if days < 0:
        # Future-dated doc; treat as max recency.
        return GateSignal("recency", 1.0, hint=f"date {top.date_str} is in the future")
    score = max(0.0, min(1.0, 1.0 - (days / _RECENCY_HORIZON_DAYS)))
    return GateSignal("recency", score, hint=f"{days} days since {top.date_str}")


def coverage_gate(query: Query, rows: list[RetrievalRow], db: IndexDB) -> GateSignal:
    """Query path coverage in top doc's governs: exact 1.0; prefix 0.5; none 0.1.

    Only meaningful for ``file_path`` queries; concept queries fall back to 0.5
    (we have no path to check against).
    """
    if not rows:
        return GateSignal("coverage", 0.0, hint="no candidates")
    if query.kind != "file_path":
        return GateSignal("coverage", 0.5, hint="concept query (no path to match)")

    query_path, _, _ = query.query.partition("#")
    top = rows[0]
    for gp in top.governs_paths:
        if gp == query_path:
            return GateSignal("coverage", 1.0, hint=f"exact governs match: {gp}")
    for gp in top.governs_paths:
        if gp.endswith("/") and query_path.startswith(gp):
            return GateSignal("coverage", 0.5, hint=f"prefix governs match: {gp}")
    return GateSignal("coverage", 0.1, hint="path not in any governs entry")


_AUTHORSHIP_HORIZON_DAYS = 365


def authorship_gate(query: Query, rows: list[RetrievalRow], db: IndexDB) -> GateSignal:
    """Days since the doc's most recent commit on its own doc path.

    Uses ``git log -1 --format=%ct -- <doc_path>``. Linear decay to 0 over
    365 days. If git is unavailable or returns nothing, signal = 0.5 (don't
    penalize; gates should fail open).
    """
    if not rows:
        return GateSignal("authorship", 0.0, hint="no candidates")
    top = rows[0]
    if not top.doc_path:
        return GateSignal("authorship", 0.5, hint="no doc_path on top row")

    # Resolve git repo root by walking up from the DB path.
    repo_root = _git_repo_root(db)
    if repo_root is None:
        return GateSignal("authorship", 0.5, hint="not a git repo")

    try:
        completed = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--", top.doc_path],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return GateSignal("authorship", 0.5, hint="git unavailable")
    out = completed.stdout.strip()
    if not out:
        return GateSignal("authorship", 0.5, hint="no commits touch doc")
    try:
        commit_ts = int(out)
    except ValueError:
        return GateSignal("authorship", 0.5, hint="bad git timestamp")
    now_ts = datetime.utcnow().timestamp()
    days = max(0.0, (now_ts - commit_ts) / 86400)
    score = max(0.0, 1.0 - (days / _AUTHORSHIP_HORIZON_DAYS))
    return GateSignal("authorship", score, hint=f"{int(days)} days since last commit on doc")


def _git_repo_root(db: IndexDB) -> str | None:
    """Best-effort: walk up from the DB path to find a .git dir."""
    from pathlib import Path

    p = Path(db.db_path).resolve()
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return str(parent)
    return None


# ── Registry + composite ────────────────────────────────────


ALL_GATES: tuple[GateFn, ...] = (
    dominance_gate,
    identifier_citation_gate,
    hedge_phrase_gate,
    status_gate,
    recency_gate,
    coverage_gate,
    authorship_gate,
)


def compute_signals(
    query: Query,
    rows: list[RetrievalRow],
    db: IndexDB,
    *,
    gates: tuple[GateFn, ...] = ALL_GATES,
) -> list[GateSignal]:
    """Run every gate; return signals in registration order."""
    return [g(query, rows, db) for g in gates]


def composite(
    signals: list[GateSignal],
    weights: dict[str, float] | None = None,
) -> float:
    """Weighted geometric mean across signals.

    Property: if any signal is ~0, composite ~0 (veto). Equivalent to:

        composite = exp( Σ w_i · log(max(s_i, eps)) / Σ w_i )

    Default uniform weights (1.0 each). Missing weights default to 1.0.
    Unknown weight keys are ignored (we only weight signals that exist).
    """
    if not signals:
        return 0.0
    eps = 1e-6
    total_w = 0.0
    weighted_log_sum = 0.0
    for s in signals:
        w = 1.0 if weights is None else float(weights.get(s.name, 1.0))
        if w <= 0:
            continue
        s_clipped = max(min(s.score, 1.0), eps)
        weighted_log_sum += w * math.log(s_clipped)
        total_w += w
    if total_w == 0:
        return 0.0
    return math.exp(weighted_log_sum / total_w)


__all__ = [
    "ALL_GATES",
    "GateFn",
    "GateSignal",
    "RetrievalRow",
    "authorship_gate",
    "composite",
    "compute_signals",
    "coverage_gate",
    "dominance_gate",
    "enrich_rows",
    "hedge_phrase_gate",
    "identifier_citation_gate",
    "recency_gate",
    "status_gate",
]
