"""List documents by type or physical bucket."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from decree.buckets import BucketPathError, bucket_for_path, normalize_bucket
from decree.checklists import parse_checkboxes_by_section
from decree.commands.report import load_report_config
from decree.config import get_project_root, load_doc_types
from decree.log import error
from decree.parser import DocDocument, load_all_types


def run(args: argparse.Namespace) -> int:
    prefix = "list"
    root = get_project_root()
    doc_types = load_doc_types()
    doc_types_by_name = {dt.name: dt for dt in doc_types}

    selected_type = getattr(args, "doc_type", None)
    if selected_type and selected_type not in doc_types_by_name:
        error(prefix, f"unknown document type: {selected_type}")
        return 1

    bucket_arg = getattr(args, "bucket", None)
    bucket_filter: Path | None = None
    if bucket_arg is not None:
        try:
            bucket_filter = normalize_bucket(bucket_arg)
        except BucketPathError as e:
            error(prefix, f"invalid --bucket: {e}")
            return 1

    try:
        docs = load_all_types()
    except Exception as e:
        error(prefix, f"failed to load documents: {e}")
        return 1

    filtered = [
        doc
        for doc in docs
        if _matches_type(doc, selected_type)
        and _matches_status(doc, getattr(args, "status", None))
        and _matches_bucket(doc, root, bucket_filter)
    ]
    filtered.sort(key=lambda doc: (_bucket_for_doc(doc, root), doc.doc_type.name, doc.doc_id))

    if getattr(args, "json", False):
        payload = {
            "schema": "decree.list.v1",
            "filters": {
                "type": selected_type,
                "bucket": _bucket_string(bucket_filter) if bucket_filter is not None else None,
                "status": getattr(args, "status", None),
            },
            "documents": [_document_payload(doc, root) for doc in filtered],
        }
        print(json.dumps(payload, indent=2, sort_keys=False))
        return 0

    if not filtered:
        print("No documents found.")
        return 0

    if getattr(args, "tree", False):
        _print_tree(filtered, root, doc_types, with_progress=getattr(args, "with_progress", False))
    else:
        _print_flat(filtered, root, doc_types, with_progress=getattr(args, "with_progress", False))
    return 0


def _matches_type(doc: DocDocument, selected_type: str | None) -> bool:
    return selected_type is None or (doc.doc_type is not None and doc.doc_type.name == selected_type)


def _matches_status(doc: DocDocument, selected_status: str | None) -> bool:
    return selected_status is None or doc.meta.status == selected_status


def _matches_bucket(doc: DocDocument, root: Path, bucket_filter: Path | None) -> bool:
    if bucket_filter is None:
        return True
    type_dir = root / doc.doc_type.dir
    return doc.path.parent.relative_to(type_dir) == bucket_filter


def _bucket_for_doc(doc: DocDocument, root: Path) -> str:
    return bucket_for_path(doc.path, root / doc.doc_type.dir)


def _bucket_string(bucket: Path | None) -> str:
    if bucket is None or bucket == Path():
        return "."
    return bucket.as_posix()


def _document_payload(doc: DocDocument, root: Path) -> dict:
    try:
        rel_path = doc.path.relative_to(root).as_posix()
    except ValueError:
        rel_path = doc.path.as_posix()
    return {
        "bucket": _bucket_for_doc(doc, root),
        "type": doc.doc_type.name,
        "id": doc.doc_id,
        "title": doc.title,
        "status": doc.meta.status,
        "path": rel_path,
        "references": list(doc.meta.references or []),
        "progress": _progress_payload(doc, root),
    }


def _progress_payload(doc: DocDocument, root: Path) -> dict:
    cfg = load_report_config(root, doc.doc_type.name)
    parsed = parse_checkboxes_by_section(doc.body, cfg.deferred_section_patterns)
    percent = round(parsed.primary_done / parsed.primary_total * 100) if parsed.primary_total else None
    return {
        "primary": {
            "done": parsed.primary_done,
            "total": parsed.primary_total,
            "percent": percent,
        },
        "deferred": {
            "done": parsed.deferred_done,
            "total": parsed.deferred_total,
        },
    }


def _docs_by_type(docs: list[DocDocument], doc_types) -> list[tuple[str, list[DocDocument]]]:
    by_type: dict[str, list[DocDocument]] = defaultdict(list)
    for doc in docs:
        by_type[doc.doc_type.name].append(doc)
    return [(dt.name, by_type[dt.name]) for dt in doc_types if by_type[dt.name]]


def _print_flat(docs: list[DocDocument], root: Path, doc_types, *, with_progress: bool) -> None:
    for type_name, type_docs in _docs_by_type(docs, doc_types):
        print(f"{type_name.upper()}:")
        for doc in type_docs:
            bucket = _bucket_for_doc(doc, root)
            suffix = _progress_suffix(doc, root) if with_progress else ""
            print(f"  {doc.doc_id}  {doc.meta.status:<12}  {bucket:<20}  {doc.title}{suffix}")


def _print_tree(docs: list[DocDocument], root: Path, doc_types, *, with_progress: bool) -> None:
    by_bucket: dict[str, list[DocDocument]] = defaultdict(list)
    for doc in docs:
        by_bucket[_bucket_for_doc(doc, root)].append(doc)

    for bucket in sorted(by_bucket, key=lambda b: (b != ".", b)):
        print(f"{bucket}/")
        for type_name, type_docs in _docs_by_type(by_bucket[bucket], doc_types):
            print(f"  {type_name.upper()}:")
            for doc in type_docs:
                suffix = _progress_suffix(doc, root) if with_progress else ""
                print(f"    {doc.doc_id}  {doc.meta.status:<12}  {doc.title}{suffix}")


def _progress_suffix(doc: DocDocument, root: Path) -> str:
    progress = _progress_payload(doc, root)["primary"]
    if progress["total"] == 0:
        return ""
    return f"  {progress['done']}/{progress['total']} primary"
