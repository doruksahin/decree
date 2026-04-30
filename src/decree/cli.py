"""Decree CLI — software decision lifecycle toolkit."""

import argparse
import sys

from decree.commands import graph, index, lint, new, progress, status

EPILOG = """\
document chain:
  PRD (what/why) → ADR (how) → SPEC (blueprint) → Implementation

examples:
  decree new prd "User Authentication"
  decree new adr "Auth via JWT"
  decree new spec "Token Storage API"
  decree status ADR-0001 accept
  decree status PRD-001 approve
  decree lint
  decree progress

config:
  Document types are defined in decree.toml under [types.*].
  Each type has: prefix, digits, statuses, transitions, warn_on_reference.
  C4 architecture support: add [types.spec.c4] with enabled, id_field, levels.

claude code skills (if decree plugin is installed):
  /decree:init   Scaffold decree/ folder with working PRD/ADR/SPEC examples
  /decree:prd    Create a PRD with section guidance and lint validation
  /decree:adr    Create an ADR with reference discovery across existing docs
  /decree:spec   Create a SPEC with stale-reference warnings
  /decree:lint   Validate all documents, create tasks per error found
"""


def main() -> int:
    """Multi-type document CLI (the `decree` entry point)."""
    parser = argparse.ArgumentParser(
        prog="decree",
        description="Decree — software decision lifecycle toolkit. "
        "Manage PRDs, ADRs, and SPECs with cross-type references, "
        "status enforcement, and validation.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── new ──────────────────────────────────────────────────
    p_new = subparsers.add_parser(
        "new",
        help="Create a new document (PRD, ADR, or SPEC)",
        description="Create a new document from the type's template. "
        "Auto-numbers, slugifies the title, stamps today's date, "
        "and regenerates the type's index.",
    )
    p_new.add_argument(
        "doc_type",
        help="Document type: adr, prd, spec (must be configured in decree.toml)",
    )
    p_new.add_argument(
        "title",
        help='Document title (e.g. "Use Redis for caching")',
    )

    # ── status ───────────────────────────────────────────────
    p_status = subparsers.add_parser(
        "status",
        help="Transition a document's status",
        description="Enforce status lifecycle transitions. "
        "Only valid transitions are allowed (e.g. proposed → accepted). "
        "For supersede: pass the replacement ID as the third argument.",
    )
    p_status.add_argument(
        "doc_id",
        help="Document ID (e.g. ADR-0001, PRD-001, SPEC-001). Type is auto-detected from prefix.",
    )
    p_status.add_argument(
        "action",
        help="Action to perform. Available actions depend on the document type "
        "(e.g. accept, reject, approve, implement, archive, supersede).",
    )
    p_status.add_argument(
        "target_id",
        nargs="?",
        default=None,
        help="Replacement document ID (required for supersede action only).",
    )

    # ── lint ─────────────────────────────────────────────────
    p_lint = subparsers.add_parser(
        "lint",
        help="Validate all documents and cross-type references",
        description="Validate all configured document types. Checks: "
        "frontmatter validity, required sections, supersede symmetry, "
        "duplicate IDs, dangling references, stale references "
        "(to rejected/deprecated/superseded/archived docs), "
        "and self-references.",
    )
    p_lint.add_argument(
        "--check-attachments",
        action="store_true",
        help="Validate that attachment file paths exist on disk",
    )

    # ── index ────────────────────────────────────────────────
    subparsers.add_parser(
        "index",
        help="Regenerate index.md for each document type",
        description="Generate a markdown table listing all documents per type, sorted by status priority then number.",
    )

    # ── graph ────────────────────────────────────────────────
    subparsers.add_parser(
        "graph",
        help="Generate Mermaid diagrams (timeline, supersede chain, status distribution)",
        description="Append Mermaid diagram blocks to each type's index.md. "
        "Preserves hand-authored content above the GENERATED marker.",
    )

    # ── progress ─────────────────────────────────────────────
    subparsers.add_parser(
        "progress",
        help="Show checkbox completion across all documents",
        description="Scan all documents for markdown checkboxes (- [ ] / - [x]) "
        "and report per-document and overall completion with progress bars.",
    )

    args = parser.parse_args()
    commands = {
        "new": new.run,
        "status": status.run,
        "lint": lint.run,
        "index": index.run,
        "graph": graph.run,
        "progress": progress.run,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
