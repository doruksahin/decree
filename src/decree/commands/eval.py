"""`decree retrieval-eval` — labeled-query retrieval-quality command (SPEC-012).

Wires the eval/ package into the CLI:

    decree retrieval-eval [--queries PATH] [--method NAME]... [--baseline NAME]
                          [--output PATH] [--json] [--bootstrap-iterations N]
                          [--k K]... [--freeze] [--project PATH] [--verbose]

Exit codes:
    0 — eval ran cleanly.
    1 — at least one method failed (others still reported).
    2 — config error (query set missing, no methods registered, …).
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from decree.commands.queries import _open_db_or_error
from decree.eval.runner import (
    freeze_baseline,
    read_baseline,
    render_markdown,
    report_to_json,
    run_evaluation,
    select_methods,
)
from decree.eval.schema import load_query_set
from decree.log import error, info, success


def _default_output(root: Path) -> Path:
    return root / "docs" / "evaluation" / f"{date.today().isoformat()}.md"


def eval_run(args: argparse.Namespace) -> int:
    """`decree retrieval-eval` handler."""
    db, root, rc = _open_db_or_error(getattr(args, "project", None))
    if db is None:
        return rc
    assert root is not None

    # ── Resolve query set ────────────────────────────────
    queries_path = Path(args.queries) if args.queries else (root / "eval" / "queries.yaml")
    if not queries_path.is_absolute():
        queries_path = (root / queries_path).resolve()
    if not queries_path.exists():
        error("retrieval-eval", f"query set not found: {queries_path}")
        return 2

    try:
        query_set = load_query_set(queries_path)
    except Exception as e:  # noqa: BLE001
        error("retrieval-eval", f"failed to load {queries_path}: {e}")
        return 2

    info(
        "retrieval-eval",
        f"loaded {len(query_set.queries)} queries from {queries_path.relative_to(root) if queries_path.is_relative_to(root) else queries_path}",
    )

    # ── Resolve methods ─────────────────────────────────
    try:
        methods = select_methods(args.method)
    except KeyError as e:
        error("retrieval-eval", str(e))
        return 2

    if not methods:
        error("retrieval-eval", "no methods registered")
        return 2

    # ── Resolve baseline snapshot ───────────────────────
    baseline_name = args.baseline or "keyword-v1"
    baseline_path = root / "eval" / "baselines" / f"{baseline_name}.json"
    baseline_snapshot = read_baseline(baseline_path) if not args.freeze else None

    # ── Run ──────────────────────────────────────────────
    report = run_evaluation(
        db=db,
        query_set=query_set,
        methods=methods,
        k_values=args.k or [1, 3, 5, 10],
        bootstrap_iterations=args.bootstrap_iterations,
        baseline_name=baseline_name,
        baseline_snapshot=baseline_snapshot,
    )

    # ── Write report ─────────────────────────────────────
    output_path = Path(args.output) if args.output else _default_output(root)
    if not output_path.is_absolute():
        output_path = (root / output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_markdown(report, verbose=args.verbose))
    info(
        "retrieval-eval",
        f"wrote report → {output_path.relative_to(root) if output_path.is_relative_to(root) else output_path}",
    )

    if args.json:
        json_path = output_path.with_suffix(output_path.suffix + ".json")
        json_path.write_text(report_to_json(report))
        info(
            "retrieval-eval",
            f"wrote JSON  → {json_path.relative_to(root) if json_path.is_relative_to(root) else json_path}",
        )

    # ── Freeze baseline ──────────────────────────────────
    if args.freeze:
        target = next(
            (mr for mr in report.methods if mr.method_name == baseline_name), None
        )
        if target is None:
            error(
                "retrieval-eval",
                f"baseline {baseline_name!r} not in evaluated methods — cannot freeze",
            )
            return 2
        if target.error:
            error(
                "retrieval-eval",
                f"baseline {baseline_name!r} failed during run — refusing to freeze a broken snapshot",
            )
            return 1
        freeze_baseline(target, baseline_path)
        success(
            f"[retrieval-eval] froze baseline {baseline_name!r} → {baseline_path.relative_to(root) if baseline_path.is_relative_to(root) else baseline_path}",
        )

    # ── Print summary table to stdout ────────────────────
    _print_summary(report)

    # ── Exit code ────────────────────────────────────────
    any_failed = any(mr.error for mr in report.methods)
    return 1 if any_failed else 0


def _print_summary(report) -> None:
    print()
    print(f"# Retrieval eval — {report.corpus} ({report.query_count} queries)")
    print()
    header = f"{'Method':22s} {'Metric':10s} {'Mean':>8s}  {'CI':>22s}  N"
    print(header)
    print("-" * len(header))
    for mr in report.methods:
        if mr.error:
            print(f"{mr.method_name:22s} ERROR: {mr.error}")
            continue
        for s in mr.stats:
            ci = f"[{s.ci_low:.4f}, {s.ci_high:.4f}]"
            print(f"{mr.method_name:22s} {s.metric:10s} {s.mean:8.4f}  {ci:>22s}  {s.n}")
    print()
