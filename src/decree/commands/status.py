"""Transition document status: accept, reject, deprecate, supersede, or any custom action."""

import argparse

from decree.commands import index
from decree.log import error, fail, info, success
from decree.parser import find_by_id, save


def run(args: argparse.Namespace) -> int:
    prefix = "status"
    action = args.action

    doc_id = args.doc_id

    # Resolve DocType from the ID prefix
    from decree.config import find_doc_type

    try:
        doc_type = find_doc_type(doc_id)
    except ValueError as e:
        error(prefix, str(e))
        return 1

    # Look up target status from doc_type's actions map
    if action not in doc_type.actions:
        error(
            prefix,
            f"Unknown action '{action}' for type '{doc_type.name}'. Valid actions: {', '.join(doc_type.actions)}.",
        )
        return 1

    target_status = doc_type.actions[action]

    info(prefix, f"loading {doc_id}")
    try:
        doc = find_by_id(doc_id)
    except (FileNotFoundError, ValueError) as e:
        error(prefix, str(e))
        return 1

    info(prefix, f"loading {doc_id} → {doc.path.name}")

    current = doc.meta.status
    valid = doc_type.transitions.get(current, ())

    if target_status not in valid:
        if not valid:
            error(
                prefix,
                f"{doc.doc_id} has terminal status '{current}'. No transitions allowed.",
            )
        else:
            error(
                prefix,
                f"{doc.doc_id} cannot transition from '{current}' to '{target_status}'. "
                f"Valid transitions: {', '.join(valid)}.",
            )
        fail(f"{doc.doc_id} status unchanged.")
        return 1

    if target_status == "superseded":
        if not args.target_id:
            error(prefix, "supersede requires a target document ID.")
            return 1

        info(prefix, f"loading replacement {args.target_id}")
        try:
            replacement = find_by_id(args.target_id)
        except (FileNotFoundError, ValueError) as e:
            error(prefix, str(e))
            return 1

        info(
            prefix,
            f"transition: {current} → superseded (superseded-by {args.target_id})",
        )
        doc.meta = doc.meta.evolve(doc_type=doc_type, status="superseded", **{"superseded-by": args.target_id})
        save(doc)
        info(prefix, f"saved {doc.path.name}")

        info(prefix, f"linking {args.target_id} → supersedes {doc_id}")
        replacement.meta = replacement.meta.evolve(doc_type=replacement.doc_type, supersedes=doc_id)
        save(replacement)
        info(prefix, f"saved {replacement.path.name}")
    else:
        info(prefix, f"transition: {current} → {target_status}")
        doc.meta = doc.meta.evolve(doc_type=doc_type, status=target_status)
        save(doc)
        info(prefix, f"saved {doc.path.name}")

    index.run(None)

    # Generate completion report if transitioning to a terminal-success status
    from decree.commands.report import generate_report, is_terminal_success
    from decree.config import get_project_root

    if is_terminal_success(doc_type, target_status):
        try:
            report_path = generate_report(doc, get_project_root(), target_status)
            if report_path:
                info(prefix, f"completion report written to {report_path.name}")
        except Exception as e:
            error(prefix, f"completion report failed (status transition kept): {e}")

    success(f"{doc.doc_id} {target_status}")
    return 0
