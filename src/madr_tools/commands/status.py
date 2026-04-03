"""Transition ADR status: accept, reject, deprecate, supersede."""
import argparse
import sys
from madr_tools.config import VALID_TRANSITIONS
from madr_tools.parser import find_by_id, save
from madr_tools.commands import index

STATUS_ACTION_MAP = {
    "accept": "accepted",
    "reject": "rejected",
    "deprecate": "deprecated",
    "supersede": "superseded",
}


def run(args: argparse.Namespace) -> int:
    action = args.action
    target_status = STATUS_ACTION_MAP[action]
    try:
        doc = find_by_id(args.adr_id)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    current = doc.meta.status
    valid = VALID_TRANSITIONS.get(current, ())
    if target_status not in valid:
        if not valid:
            print(f"Error: {doc.adr_id} has terminal status '{current}'. No transitions allowed.", file=sys.stderr)
        else:
            print(f"Error: {doc.adr_id} cannot transition from '{current}' to '{target_status}'. Valid transitions: {', '.join(valid)}.", file=sys.stderr)
        return 1

    if action == "supersede":
        if not args.target_id:
            print("Error: supersede requires a target ADR ID.", file=sys.stderr)
            return 1
        try:
            replacement = find_by_id(args.target_id)
        except (FileNotFoundError, ValueError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        doc.meta = doc.meta.evolve(status="superseded", **{"superseded-by": args.target_id})
        save(doc)
        replacement.meta = replacement.meta.evolve(supersedes=args.adr_id)
        save(replacement)
    else:
        doc.meta = doc.meta.evolve(status=target_status)
        save(doc)

    index.run(None)
    return 0
