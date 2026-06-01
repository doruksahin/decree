"""`decree why` and `decree refs` — queries against the SQLite provenance index.

Both commands are *read-only* against `.decree/index.sqlite`. They never re-parse
markdown or walk frontmatter. If the index is missing or stale, they bail out
with a clear message pointing at `decree index rebuild`.

Library API (re-exported by SPEC-01KT22NMRYJ4482K92AX9GJTMA's MCP server):

    why(db: IndexDB, path: str, *, limit: int = 20) -> list[GoverningDecision]
    refs(db: IndexDB, decision_id: str) -> RefsReport

CLI entry points (wired into cli.py):

    why_run(args)  → int
    refs_run(args) → int
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

import networkx as nx

from decree.config import load_doc_types
from decree.index_db import IndexDB, default_db_path
from decree.log import error

# ── Public dataclasses ───────────────────────────────────────


class MatchKind(StrEnum):
    EXACT = "exact"
    PREFIX = "prefix"


@dataclass(frozen=True)
class GoverningDecision:
    """One row in the `decree why` output."""

    decision_id: str
    type: str
    status: str
    date: str
    title: str
    match_kind: MatchKind
    matched_path: str
    symbol: str | None = None


@dataclass(frozen=True)
class DecisionMetadata:
    """Top-of-RefsReport block — pulled from the `decisions` table."""

    decision_id: str
    type: str
    status: str
    title: str
    date: str
    body_hash: str


@dataclass(frozen=True)
class RefRow:
    from_id: str
    to_id: str
    kind: str


@dataclass(frozen=True)
class GovernsRow:
    path: str
    symbol: str
    order_index: int


@dataclass(frozen=True)
class CommitRow:
    sha: str
    trailer_kind: str
    summary: str
    committed_at: str


@dataclass(frozen=True)
class RefsReport:
    """Result of `decree refs <id>` — five tuples plus metadata."""

    decision_id: str
    metadata: DecisionMetadata
    forward_refs: tuple[RefRow, ...] = ()
    reverse_refs: tuple[RefRow, ...] = ()
    supersedes_chain: tuple[str, ...] = ()
    governs: tuple[GovernsRow, ...] = ()
    commits: tuple[CommitRow, ...] = ()


# ── Status priority ─────────────────────────────────────────


def _status_priority(type_name: str, status: str) -> int:
    """Return a sort priority for a (type, status) pair. Lower is "better".

    Rules:
      0 — terminal-success: terminal status that is NOT warn-on-reference
          (e.g. `implemented` for spec, `accepted` for adr).
      1 — active states (`draft`, `approved`, `proposed`, …).
      2 — warn-on-reference statuses (`rejected`, `superseded`, `deprecated`).

    Unknown types/statuses default to priority 1.
    """
    for dt in load_doc_types():
        if dt.name == type_name:
            warn = set(dt.warn_on_reference)
            if status in warn:
                return 2
            if status in dt.terminal_statuses and status not in warn:
                return 0
            return 1
    return 1


# ── why() — library API ─────────────────────────────────────


def why(db: IndexDB, path: str, *, limit: int = 20) -> list[GoverningDecision]:
    """Return the set of decisions that govern `path`.

    `path` may include `#symbol` — the symbol part is stripped for matching
    but surfaced on each returned row.

    Results are deduplicated by decision_id (exact wins over prefix on
    conflict), then sorted by:
      1. Status priority (terminal-success → active → warn-on-reference)
      2. Doc date descending (newer first within the same status)
    """
    query_path, _, query_symbol = path.partition("#")

    conn = db.db.conn  # type: ignore[attr-defined]

    exact_sql = (
        "SELECT g.decision_id, g.path, g.symbol, d.status, d.title, d.date, d.type "
        "FROM governs g JOIN decisions d ON d.id = g.decision_id "
        "WHERE g.path = ?"
    )
    prefix_sql = (
        "SELECT g.decision_id, g.path, g.symbol, d.status, d.title, d.date, d.type "
        "FROM governs g JOIN decisions d ON d.id = g.decision_id "
        "WHERE substr(g.path, -1) = '/' AND ? LIKE g.path || '%'"
    )

    rows_by_id: dict[str, GoverningDecision] = {}

    for r in conn.execute(exact_sql, (query_path,)):
        decision_id, gpath, symbol, status, title, date, type_name = r
        rows_by_id[decision_id] = GoverningDecision(
            decision_id=decision_id,
            type=type_name,
            status=status,
            date=str(date),
            title=title,
            match_kind=MatchKind.EXACT,
            matched_path=gpath,
            symbol=query_symbol or (symbol or None) or None,
        )

    for r in conn.execute(prefix_sql, (query_path,)):
        decision_id, gpath, symbol, status, title, date, type_name = r
        if decision_id in rows_by_id:
            # exact wins over prefix
            continue
        rows_by_id[decision_id] = GoverningDecision(
            decision_id=decision_id,
            type=type_name,
            status=status,
            date=str(date),
            title=title,
            match_kind=MatchKind.PREFIX,
            matched_path=gpath,
            symbol=query_symbol or (symbol or None) or None,
        )

    results = list(rows_by_id.values())
    results.sort(
        key=lambda gd: (_status_priority(gd.type, gd.status), _negated_date(gd.date)),
    )
    return results[:limit]


def _negated_date(date_str: str) -> str:
    """Return a string that sorts descending when used as a sort key.

    Doc dates are ISO format (YYYY-MM-DD), so we just invert each digit's
    sort order. Using a tuple of negated codepoints is overkill for our
    fixed-width ISO dates; a simple trick: prefix with '\xff' minus the
    string. Easier: store as a tuple of (negated year, month, day).
    """
    # ISO dates sort ascending naturally; we want descending. Easiest: sort
    # by the negation tuple of the components. If the date is malformed we
    # fall back to an empty tuple (sorts before everything).
    try:
        y, m, d = date_str.split("-", 2)
        return f"{9999 - int(y):04d}-{99 - int(m):02d}-{99 - int(d):02d}"
    except (ValueError, AttributeError):
        return "9999-99-99"


# ── refs() — library API ────────────────────────────────────


def refs(db: IndexDB, decision_id: str) -> RefsReport | None:
    """Return a RefsReport for `decision_id`, or None if it doesn't exist."""
    conn = db.db.conn  # type: ignore[attr-defined]

    meta_row = next(
        conn.execute(
            "SELECT id, type, status, title, date, body_hash FROM decisions WHERE id = ?",
            (decision_id,),
        ),
        None,
    )
    if meta_row is None:
        return None

    metadata = DecisionMetadata(
        decision_id=meta_row[0],
        type=meta_row[1],
        status=meta_row[2],
        title=meta_row[3],
        date=str(meta_row[4]),
        body_hash=meta_row[5],
    )

    forward = tuple(
        RefRow(from_id=r[0], to_id=r[1], kind=r[2])
        for r in conn.execute(
            "SELECT from_id, to_id, kind FROM refs WHERE from_id = ? ORDER BY to_id, kind",
            (decision_id,),
        )
    )

    reverse = tuple(
        RefRow(from_id=r[0], to_id=r[1], kind=r[2])
        for r in conn.execute(
            "SELECT from_id, to_id, kind FROM refs WHERE to_id = ? ORDER BY from_id, kind",
            (decision_id,),
        )
    )

    governs_rows = tuple(
        GovernsRow(path=r[0], symbol=r[1] or "", order_index=r[2])
        for r in conn.execute(
            "SELECT path, symbol, order_index FROM governs WHERE decision_id = ? ORDER BY order_index",
            (decision_id,),
        )
    )

    commit_rows = tuple(
        CommitRow(sha=r[0], trailer_kind=r[1], summary=r[2], committed_at=str(r[3] or ""))
        for r in conn.execute(
            "SELECT sha, trailer_kind, summary, committed_at FROM commits WHERE decision_id = ? ORDER BY committed_at",
            (decision_id,),
        )
    )

    chain = _supersedes_chain(conn, decision_id)

    return RefsReport(
        decision_id=decision_id,
        metadata=metadata,
        forward_refs=forward,
        reverse_refs=reverse,
        supersedes_chain=chain,
        governs=governs_rows,
        commits=commit_rows,
    )


def _supersedes_chain(conn, decision_id: str) -> tuple[str, ...]:
    """Walk the supersedes graph bidirectionally and return the full chain.

    `refs` rows of kind `supersedes`: from_id supersedes to_id (from_id is newer).
    `refs` rows of kind `superseded-by`: from_id is superseded by to_id (to_id is newer).

    We normalize both kinds into directed edges `older → newer` and then walk both
    ancestors (older docs) and descendants (newer docs) from `decision_id`.
    Returns a chain ordered oldest → newest.
    """
    g = nx.DiGraph()
    for from_id, to_id, kind in conn.execute(
        "SELECT from_id, to_id, kind FROM refs WHERE kind IN ('supersedes', 'superseded-by')"
    ):
        if kind == "supersedes":
            # from_id supersedes to_id  →  to_id (older) → from_id (newer)
            g.add_edge(to_id, from_id)
        elif kind == "superseded-by":
            # from_id is superseded by to_id  →  from_id (older) → to_id (newer)
            g.add_edge(from_id, to_id)

    if decision_id not in g:
        return ()

    ancestors = nx.ancestors(g, decision_id)  # older docs
    descendants = nx.descendants(g, decision_id)  # newer docs

    # Build the chain as oldest → newest. Topological sort over the subgraph
    # induced by ancestors + self + descendants gives us the order.
    nodes = ancestors | {decision_id} | descendants
    subgraph = g.subgraph(nodes)
    try:
        order = list(nx.topological_sort(subgraph))
    except nx.NetworkXUnfeasible:
        # Cycle — shouldn't happen for a real supersedes chain, but be defensive.
        order = sorted(nodes)
    return tuple(order)


# ── CLI wrappers ────────────────────────────────────────────


def _resolve_root(project_arg: str | None) -> Path:
    """Resolve the project root, identical to index_db_cli._resolve_root."""
    if project_arg:
        path = Path(project_arg).resolve()
        if not (path / "decree.toml").exists():
            raise FileNotFoundError(f"{path} has no decree.toml")
        return path

    from decree.config import get_project_root
    from decree.config import load_doc_types as _ldt

    get_project_root.cache_clear()
    _ldt.cache_clear()
    return get_project_root()


def _open_db_or_error(project_arg: str | None) -> tuple[IndexDB | None, Path | None, int]:
    """Resolve root, open DB, and return (db, root, status_exit_code).

    If the index is missing, prints an error and returns (None, root, 1).
    Otherwise returns (db, root, 0). Drift checking is the caller's
    responsibility and must fail closed before returning indexed results.
    """
    try:
        root = _resolve_root(project_arg)
    except FileNotFoundError as e:
        error("queries", str(e))
        return None, None, 1

    import os

    os.chdir(root)
    from decree.config import get_project_root
    from decree.config import load_doc_types as _ldt

    get_project_root.cache_clear()
    _ldt.cache_clear()

    db = IndexDB(default_db_path(root))
    status = db.status()
    if not status.exists:
        error(
            "queries",
            f"index not found at {db.db_path.relative_to(root) if db.db_path.is_relative_to(root) else db.db_path}\n"
            f"  Run `decree index rebuild` first.",
        )
        return None, root, 1
    return db, root, 0


def _ensure_fresh_index(db: IndexDB, root: Path) -> bool:
    """Return False and print an error if `verify()` reports drift."""
    findings = db.verify(root)
    # `verify` returns one `index_missing` finding when there's no DB; in that
    # case we never reach here, but be defensive.
    real_drift = [f for f in findings if f.kind != "index_missing"]
    if real_drift:
        error(
            "queries",
            f"index is stale ({len(real_drift)} drift findings). Run `decree index rebuild` before querying.",
        )
        return False
    return True


# ── Formatters: why ─────────────────────────────────────────


def _format_why_human(
    query: str,
    matches: list[GoverningDecision],
    *,
    abstention: dict | None = None,
) -> str:
    if abstention is not None and abstention.get("abstained"):
        return _format_abstention_human(query, abstention, matches=matches)

    if not matches:
        return f"{query} — no governing decisions"

    lines = [f"{query} — {len(matches)} governing decision{'s' if len(matches) != 1 else ''}", ""]
    for m in matches:
        sym = f"#{m.symbol}" if m.symbol else ""
        lines.append(f"  ▸ {m.decision_id}  {m.status}  {m.date}  {m.match_kind.value}")
        lines.append(f"    {m.title}")
        lines.append(f"    governs: {m.matched_path}{sym}")
    return "\n".join(lines)


def _format_why_json(
    query: str,
    matches: list[GoverningDecision],
    *,
    abstention: dict | None = None,
) -> str:
    payload: dict = {
        "query": query,
        "match_count": len(matches),
        "matches": [
            {
                "decision_id": m.decision_id,
                "type": m.type,
                "status": m.status,
                "date": m.date,
                "title": m.title,
                "match_kind": m.match_kind.value,
                "matched_path": m.matched_path,
                "symbol": m.symbol,
            }
            for m in matches
        ],
    }
    if abstention is not None:
        payload.update(abstention)
    return json.dumps(payload, indent=2, sort_keys=False)


# ── Formatters: refs ────────────────────────────────────────


def _format_refs_human(report: RefsReport) -> str:
    md = report.metadata
    lines = [
        f"{md.decision_id}  {md.status}  {md.date}",
        f"  {md.title}",
        "",
    ]

    lines.append(f"  Forward refs ({len(report.forward_refs)}):")
    if report.forward_refs:
        for r in report.forward_refs:
            lines.append(f"    → {r.to_id}  ({r.kind})")
    else:
        lines.append("    (none)")
    lines.append("")

    lines.append(f"  Reverse refs ({len(report.reverse_refs)}):")
    if report.reverse_refs:
        for r in report.reverse_refs:
            lines.append(f"    ← {r.from_id}  ({r.kind})")
    else:
        lines.append("    (none)")
    lines.append("")

    lines.append(f"  Supersedes chain ({len(report.supersedes_chain)}):")
    if report.supersedes_chain:
        lines.append(f"    {' → '.join(report.supersedes_chain)}")
    else:
        lines.append("    (none)")
    lines.append("")

    lines.append(f"  Governs ({len(report.governs)}):")
    if report.governs:
        for g in report.governs:
            sym = f"#{g.symbol}" if g.symbol else ""
            lines.append(f"    {g.path}{sym}")
    else:
        lines.append("    (none)")
    lines.append("")

    lines.append(f"  Commits ({len(report.commits)}):")
    if report.commits:
        for c in report.commits:
            lines.append(f"    {c.sha[:8]}  {c.trailer_kind}  {c.summary}")
    else:
        lines.append("    (none — populated by SPEC-01KT22NMRY8YK9RP4323KX4RQG)")
    return "\n".join(lines)


def _format_refs_json(report: RefsReport) -> str:
    payload = {
        "decision_id": report.decision_id,
        "metadata": asdict(report.metadata),
        "forward_refs": [asdict(r) for r in report.forward_refs],
        "reverse_refs": [asdict(r) for r in report.reverse_refs],
        "supersedes_chain": list(report.supersedes_chain),
        "governs": [asdict(g) for g in report.governs],
        "commits": [asdict(c) for c in report.commits],
    }
    return json.dumps(payload, indent=2, sort_keys=False)


# ── CLI entry points ────────────────────────────────────────


# ── SPEC-01KT22NMS0VWCTYPFPHP8M8V36 calibrated assessment ──────────────────────────


def _calibrated_assess(
    db: IndexDB,
    *,
    kind: str,
    text: str,
    target_precision: float | None = None,
) -> dict | None:
    """Run the calibrated method for a (kind, text) query; return abstention dict or None.

    Returns:
        - A dict ``{"abstained": bool, "composite_score": float, "threshold": float,
          "signals": {name: score}, "signal_hints": {name: hint},
          "abstention_reason": str | None, "would_have_returned": [decision_id, ...]}``.
        - Raises if calibration is unavailable or malformed. Callers must
          surface that explicitly instead of silently disabling abstention.
    """
    from decree.eval.methods import KeywordCalibrated
    from decree.eval.schema import Query

    # Build a Query object compatible with the method protocol. Use a stable
    # synthetic id; relevant set empty (not used in gating).
    qid = "cli-runtime"
    query = Query(id=qid, kind=kind, query=text, relevant=[])

    method = KeywordCalibrated()

    decision_ids = method.query(db, query, k=10)
    diag = method.last_diagnostics()
    abstained = method.last_abstention_reason() is not None

    signals_map: dict[str, float] = {}
    hints_map: dict[str, str | None] = {}
    for s in diag["signals"]:  # type: ignore[index]
        signals_map[s["name"]] = float(s["score"])
        hints_map[s["name"]] = s.get("hint")

    return {
        "abstained": abstained,
        "composite_score": float(diag["composite"]),
        "threshold": float(diag["threshold"]),
        "signals": signals_map,
        "signal_hints": hints_map,
        "abstention_reason": method.last_abstention_reason(),
        "would_have_returned": (
            list(diag["would_return"]) if abstained else []  # type: ignore[arg-type]
        ),
        "returned": [] if abstained else list(decision_ids),
    }


def _format_abstention_human(
    query: str,
    abstention: dict,
    *,
    matches: list[GoverningDecision] | None = None,
) -> str:
    comp = abstention.get("composite_score", 0.0)
    tau = abstention.get("threshold", 0.0)
    lines = [
        f"no governance found (composite confidence {comp:.2f}; threshold {tau:.2f})",
    ]
    reason = abstention.get("abstention_reason")
    if reason:
        lines.append(f"  reason: {reason}")
    sigs = abstention.get("signals", {})
    hints = abstention.get("signal_hints", {})
    if sigs:
        lines.append("")
        lines.append("  signals:")
        # Pad names so the column lines up; preserve insertion order.
        name_width = max(len(n) for n in sigs)
        for name, score in sigs.items():
            hint = hints.get(name)
            suffix = f"  ({hint})" if hint else ""
            lines.append(f"    {name.ljust(name_width)}  {float(score):.2f}{suffix}")
    would = abstention.get("would_have_returned") or []
    if would:
        lines.append("")
        lines.append(f"  closest non-abstaining hit: {would[0]} (would have been returned without --with-abstention)")
    return "\n".join(lines)


def why_run(args: argparse.Namespace) -> int:
    """`decree why <path> [--json] [--with-abstention]` — print governing decisions.

    With ``--with-abstention``, the query is routed through the SPEC-01KT22NMS0VWCTYPFPHP8M8V36
    calibrated method (``keyword-v1-calibrated``). On a low-confidence
    answer the calibrated method returns ``[]`` and we print the abstention
    block (human) or the abstention shape (json).
    """
    db, root, rc = _open_db_or_error(getattr(args, "project", None))
    if db is None:
        return rc
    assert root is not None

    if not _ensure_fresh_index(db, root):
        return 1

    with_abstention = bool(getattr(args, "with_abstention", False))
    target_precision = getattr(args, "target_precision", None)

    matches = why(db, args.path)

    if with_abstention:
        try:
            abstention = _calibrated_assess(
                db,
                kind="file_path",
                text=args.path,
                target_precision=target_precision,
            )
        except Exception as e:
            error("why", f"calibrated abstention unavailable: {e}")
            return 1
        if getattr(args, "json", False):
            print(_format_why_json(args.path, matches, abstention=abstention))
        else:
            print(_format_why_human(args.path, matches, abstention=abstention))
        return 0

    if getattr(args, "json", False):
        print(_format_why_json(args.path, matches))
    else:
        print(_format_why_human(args.path, matches))

    # Empty result is not an error — abstention is a valid answer.
    return 0


def refs_run(args: argparse.Namespace) -> int:
    """`decree refs <id> [--json] [--with-abstention]` — print the reverse graph.

    With ``--with-abstention``, ``refs`` first asks the calibrated method
    whether *any* governance lookup against the decision_id-as-query has
    enough confidence. If not, we print the abstention block and skip the
    full reverse-graph fetch. The intent is parity with ``why``: the user
    asked for guidance, the calibrator said "don't trust me here".
    """
    db, root, rc = _open_db_or_error(getattr(args, "project", None))
    if db is None:
        return rc
    assert root is not None

    if not _ensure_fresh_index(db, root):
        return 1

    with_abstention = bool(getattr(args, "with_abstention", False))
    target_precision = getattr(args, "target_precision", None)

    if with_abstention:
        try:
            abstention = _calibrated_assess(
                db,
                kind="concept",
                text=args.decision_id,
                target_precision=target_precision,
            )
        except Exception as e:
            error("refs", f"calibrated abstention unavailable: {e}")
            return 1
        if abstention is not None and abstention.get("abstained"):
            if getattr(args, "json", False):
                payload = {
                    "decision_id": args.decision_id,
                    **abstention,
                }
                print(json.dumps(payload, indent=2, sort_keys=False))
            else:
                print(_format_abstention_human(args.decision_id, abstention))
            return 0

    report = refs(db, args.decision_id)
    if report is None:
        error("refs", f"unknown decision: {args.decision_id}")
        return 1

    if getattr(args, "json", False):
        print(_format_refs_json(report))
    else:
        print(_format_refs_human(report))
    return 0
