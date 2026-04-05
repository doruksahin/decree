"""ADR toolkit CLI — MADR v4.0.0 management."""
import argparse
import sys
from madr_tools.commands import new, status, lint, index, graph

def main() -> int:
    parser = argparse.ArgumentParser(prog="adr", description="MADR v4.0.0 ADR management toolkit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_new = subparsers.add_parser("new", help="Create a new ADR")
    p_new.add_argument("title", help="Title of the decision")

    p_status = subparsers.add_parser("status", help="Transition ADR status")
    p_status.add_argument("action", choices=["accept", "reject", "deprecate", "supersede"])
    p_status.add_argument("adr_id", help="ADR ID (e.g. ADR-0004)")
    p_status.add_argument("target_id", nargs="?", default=None, help="Replacement ADR ID (for supersede)")

    subparsers.add_parser("lint", help="Validate all ADRs")
    subparsers.add_parser("index", help="Regenerate docs/adr/index.md")
    subparsers.add_parser("graph", help="Generate Mermaid diagrams (timeline, supersede chain, status)")

    args = parser.parse_args()
    commands = {"new": new.run, "status": status.run, "lint": lint.run, "index": index.run, "graph": graph.run}
    return commands[args.command](args)

def doc_main() -> int:
    """Multi-type document CLI."""
    parser = argparse.ArgumentParser(prog="doc", description="Structured document management toolkit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_new = subparsers.add_parser("new")
    p_new.add_argument("doc_type", help="Document type (adr, prd, spec, ...)")
    p_new.add_argument("title", help="Title of the document")

    p_status = subparsers.add_parser("status")
    p_status.add_argument("doc_id", help="Document ID (e.g., ADR-0001, PRD-001)")
    p_status.add_argument("action", help="Action to perform (e.g., accept, approve)")
    p_status.add_argument("target_id", nargs="?", default=None)

    subparsers.add_parser("lint")
    subparsers.add_parser("index")
    subparsers.add_parser("graph")

    args = parser.parse_args()
    commands = {"new": new.run, "status": status.run, "lint": lint.run, "index": index.run, "graph": graph.run}
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
