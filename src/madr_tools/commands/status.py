"""Transition ADR status: accept, reject, deprecate, supersede."""
import argparse

from madr_tools.config import VALID_TRANSITIONS
from madr_tools.log import info, error, success, fail
from madr_tools.parser import find_by_id, save
from madr_tools.commands import index

STATUS_ACTION_MAP = {
    "accept": "accepted",
    "reject": "rejected",
    "deprecate": "deprecated",
    "supersede": "superseded",
}


def run(args: argparse.Namespace) -> int:
    prefix = "status"
    action = args.action
    target_status = STATUS_ACTION_MAP[action]

    info(prefix, f"loading {args.adr_id}")
    try:
        doc = find_by_id(args.adr_id)
    except (FileNotFoundError, ValueError) as e:
        error(prefix, str(e))
        return 1

    info(prefix, f"loading {args.adr_id} → {doc.path.name}")

    current = doc.meta.status
    valid = VALID_TRANSITIONS.get(current, ())

    if target_status not in valid:
        if not valid:
            error(prefix, f"{doc.adr_id} has terminal status '{current}'. No transitions allowed.")
        else:
            error(prefix, f"{doc.adr_id} cannot transition from '{current}' to '{target_status}'. Valid transitions: {', '.join(valid)}.")
        fail(f"{doc.adr_id} status unchanged.")
        return 1

    if action == "supersede":
        if not args.target_id:
            error(prefix, "supersede requires a target ADR ID.")
            return 1

        info(prefix, f"loading replacement {args.target_id}")
        try:
            replacement = find_by_id(args.target_id)
        except (FileNotFoundError, ValueError) as e:
            error(prefix, str(e))
            return 1

        info(prefix, f"transition: {current} → superseded (superseded-by {args.target_id})")
        doc.meta = doc.meta.evolve(status="superseded", **{"superseded-by": args.target_id})
        save(doc)
        info(prefix, f"saved {doc.path.name}")

        info(prefix, f"linking {args.target_id} → supersedes {args.adr_id}")
        replacement.meta = replacement.meta.evolve(supersedes=args.adr_id)
        save(replacement)
        info(prefix, f"saved {replacement.path.name}")
    else:
        info(prefix, f"transition: {current} → {target_status}")
        doc.meta = doc.meta.evolve(status=target_status)
        save(doc)
        info(prefix, f"saved {doc.path.name}")

    index.run(None)
    success(f"{doc.adr_id} {target_status}")
    return 0
